"""Feature definition shared by training and serving.

Keeping one encoder for both paths avoids train/serve skew. Every feature is
known at booking time, so there is no label leakage.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from typing import Iterable, Sequence

import numpy as np

APPOINTMENT_TYPES = ("checkup", "follow_up", "specialist", "vaccination", "lab_test")

# Smoothed prior no-show rate: shrinks small histories towards a clinic-wide base rate.
PRIOR_BASE_RATE = 0.2
PRIOR_STRENGTH = 2.0

MAX_LEAD_DAYS = 60
MAX_PRIOR_COUNT = 30

FEATURE_NAMES: tuple[str, ...] = (
    "lead_days",
    "hour",
    *(f"weekday_{d}" for d in range(7)),
    *(f"type_{t}" for t in APPOINTMENT_TYPES),
    "prior_visits",
    "prior_no_shows",
    "prior_no_show_rate",
    "first_visit",
)


@dataclass(frozen=True)
class AppointmentFeatures:
    lead_days: int
    hour: int
    weekday: int  # Monday = 0
    appointment_type: str
    prior_visits: int
    prior_no_shows: int


def smoothed_rate(visits: int, no_shows: int) -> float:
    return (no_shows + PRIOR_BASE_RATE * PRIOR_STRENGTH) / (visits + PRIOR_STRENGTH)


def encode(rows: Sequence[AppointmentFeatures]) -> np.ndarray:
    """Turn feature records into a dense float matrix (n_rows x len(FEATURE_NAMES))."""
    X = np.zeros((len(rows), len(FEATURE_NAMES)), dtype=np.float64)
    type_index = {t: i for i, t in enumerate(APPOINTMENT_TYPES)}
    for i, r in enumerate(rows):
        if r.appointment_type not in type_index:
            raise ValueError(f"unknown appointment type: {r.appointment_type!r}")
        visits = min(max(r.prior_visits, 0), MAX_PRIOR_COUNT)
        no_shows = min(max(r.prior_no_shows, 0), visits)
        X[i, 0] = min(max(r.lead_days, 0), MAX_LEAD_DAYS)
        X[i, 1] = r.hour
        X[i, 2 + (r.weekday % 7)] = 1.0
        X[i, 9 + type_index[r.appointment_type]] = 1.0
        X[i, 14] = visits
        X[i, 15] = no_shows
        X[i, 16] = smoothed_rate(visits, no_shows)
        X[i, 17] = 1.0 if visits == 0 else 0.0
    return X


def prior_counts(history: Iterable[tuple[str, str]], before: str) -> tuple[int, int]:
    """(visits, no_shows) among reconciled visits strictly before an ISO date."""
    visits = no_shows = 0
    for day, status in history:
        if day < before:
            visits += 1
            no_shows += status == "no_show"
    return visits, no_shows


def features_for_new(
    *, appointment_date: date, hour: int, appointment_type: str, lead_days: int,
    history: Iterable[tuple[str, str]],
) -> AppointmentFeatures:
    visits, no_shows = prior_counts(history, appointment_date.isoformat())
    return AppointmentFeatures(
        lead_days=lead_days, hour=hour, weekday=appointment_date.weekday(),
        appointment_type=appointment_type, prior_visits=visits, prior_no_shows=no_shows,
    )


def training_set_from_rows(rows: Sequence[dict]) -> tuple[list[AppointmentFeatures], np.ndarray]:
    """Build (features, labels) from reconciled DB rows.

    Rows are processed one day at a time: prior counts for a day only include
    earlier days, exactly mirroring what was knowable at booking time.
    """
    ordered = sorted(rows, key=lambda r: (r["appointment_date"], r["appointment_time"]))
    seen: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # key -> [visits, no_shows]
    feats: list[AppointmentFeatures] = []
    labels: list[int] = []
    for day, group in groupby(ordered, key=lambda r: r["appointment_date"]):
        group = list(group)
        d = date.fromisoformat(day)
        for r in group:
            visits, no_shows = seen[r["patient_key"]]
            feats.append(AppointmentFeatures(
                lead_days=r["lead_days"], hour=int(r["appointment_time"][:2]), weekday=d.weekday(),
                appointment_type=r["appointment_type"], prior_visits=visits, prior_no_shows=no_shows,
            ))
            labels.append(1 if r["status"] == "no_show" else 0)
        for r in group:
            counts = seen[r["patient_key"]]
            counts[0] += 1
            counts[1] += r["status"] == "no_show"
    return feats, np.asarray(labels, dtype=np.int64)
