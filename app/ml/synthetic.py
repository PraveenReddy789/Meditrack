"""Synthetic baseline history.

The brief rules out external data sources, and a fresh install has no history,
so the model is bootstrapped from simulated clinic data and then blends in real
reconciled appointments as they accumulate. The generating process is simple
and documented in the README; it encodes plausible, widely reported patterns
(longer lead time, repeat no-shows, early/late slots, Mondays/Fridays), not
facts about any real clinic.
"""
from __future__ import annotations

import numpy as np

from app.ml.features import APPOINTMENT_TYPES, AppointmentFeatures

_TYPE_PROBS = (0.30, 0.25, 0.15, 0.10, 0.20)
_TYPE_EFFECT = {"checkup": 0.0, "follow_up": -0.25, "specialist": -0.40, "vaccination": 0.30, "lab_test": 0.25}
_WEEKDAY_EFFECT = (0.20, 0.0, 0.0, 0.0, 0.25, 0.15, 0.0)  # Mon, Fri and Sat are worse
_HOURS = np.arange(8, 18)
_HOUR_PROBS = np.array([0.12, 0.13, 0.12, 0.09, 0.06, 0.09, 0.12, 0.11, 0.09, 0.07])
_HOUR_PROBS = _HOUR_PROBS / _HOUR_PROBS.sum()


def _hour_effect(hour: int) -> float:
    if hour <= 8:
        return 0.25
    if hour in (12, 13):
        return 0.20
    if hour >= 16:
        return 0.30
    return 0.0


def generate(n: int, seed: int) -> tuple[list[AppointmentFeatures], np.ndarray]:
    feats, labels, _ = simulate(n, seed)
    return feats, labels


def simulate(n: int, seed: int) -> tuple[list[AppointmentFeatures], np.ndarray, np.ndarray]:
    """Like generate(), also returning the true no-show probabilities (used to measure the achievable ceiling)."""
    rng = np.random.default_rng(seed)

    types = rng.choice(APPOINTMENT_TYPES, size=n, p=_TYPE_PROBS)
    lead = np.clip(rng.exponential(10.0, size=n).round(), 0, 60).astype(int)
    hours = rng.choice(_HOURS, size=n, p=_HOUR_PROBS)
    weekdays = rng.choice(6, size=n, p=[0.19, 0.19, 0.19, 0.19, 0.19, 0.05])

    # Each patient has a latent no-show propensity; prior history is a noisy view of it.
    propensity = rng.beta(1.2, 5.0, size=n)
    prior_visits = rng.poisson(3.0, size=n)
    prior_no_shows = rng.binomial(prior_visits, propensity)

    logit = np.log(propensity / (1 - propensity)) - 0.55
    logit += 1.2 * (1 - np.exp(-lead / 14.0))  # saturating lead-time effect
    logit += np.array([_TYPE_EFFECT[t] for t in types])
    logit += np.array([_WEEKDAY_EFFECT[d] for d in weekdays])
    logit += np.array([_hour_effect(int(h)) for h in hours])
    logit += np.where((prior_visits == 0) & (lead > 21), 0.5, 0.0)  # new patient booked far ahead
    prob = 1 / (1 + np.exp(-logit))
    labels = (rng.random(n) < prob).astype(np.int64)

    feats = [
        AppointmentFeatures(
            lead_days=int(lead[i]), hour=int(hours[i]), weekday=int(weekdays[i]),
            appointment_type=str(types[i]), prior_visits=int(prior_visits[i]),
            prior_no_shows=int(prior_no_shows[i]),
        )
        for i in range(n)
    ]
    return feats, labels, prob
