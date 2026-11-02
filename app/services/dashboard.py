"""Dashboard aggregation.

Definitions (also shown in the README):
* reconciled      = attended + no_show (the outcome is known)
* no-show rate    = no_shows / reconciled; still-scheduled visits are excluded so
                    today's pending appointments don't look like attendance
* expected        = sum of stored risk scores (calibrated probabilities), the
                    better estimate of how many no-shows to plan for
* flagged         = appointments at or above the model's alert threshold
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.db import AppointmentRepository
from app.ml.model import ModelService

WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")  # SQLite strftime('%w') order


def _rate(no_shows: int, reconciled: int) -> float | None:
    return round(no_shows / reconciled, 4) if reconciled else None


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


class DashboardService:
    def __init__(self, repo: AppointmentRepository, model: ModelService):
        self.repo = repo
        self.model = model

    def build(self, days: int, today: date | None = None) -> dict:
        today = today or date.today()
        start = today - timedelta(days=days - 1)
        stats = {r["day"]: r for r in self.repo.daily_stats(start.isoformat(), today.isoformat())}

        trend = []
        for offset in range(days):
            d = start + timedelta(days=offset)
            r = stats.get(d.isoformat())
            attended = int(r["attended"]) if r else 0
            no_shows = int(r["no_shows"]) if r else 0
            trend.append({
                "date": d.isoformat(),
                "total": int(r["total"]) if r else 0,
                "attended": attended,
                "no_shows": no_shows,
                "scheduled": int(r["scheduled"]) if r else 0,
                "no_show_rate": _rate(no_shows, attended + no_shows),
                "expected_no_shows": round(float(r["expected_no_shows"]), 2) if r else 0.0,
                "flagged": int(r["flagged"]) if r else 0,
            })

        # Rolling 7-day no-show rate smooths day-to-day noise to show the actual trend.
        for i, point in enumerate(trend):
            window = trend[max(0, i - 6): i + 1]
            ns = sum(p["no_shows"] for p in window)
            rec = sum(p["no_shows"] + p["attended"] for p in window)
            point["rate_7d"] = _rate(ns, rec)

        totals = {
            k: sum(p[k] for p in trend) for k in ("total", "attended", "no_shows", "scheduled", "flagged")
        }
        reconciled = totals["attended"] + totals["no_shows"]
        summary = {
            "appointments": totals["total"],
            "reconciled": reconciled,
            "attended": totals["attended"],
            "no_shows": totals["no_shows"],
            "scheduled": totals["scheduled"],
            "no_show_rate": _rate(totals["no_shows"], reconciled),
            "expected_no_shows": round(sum(p["expected_no_shows"] for p in trend), 1),
            "flagged": totals["flagged"],
        }

        upcoming_start, upcoming_end = today + timedelta(days=1), today + timedelta(days=7)
        up_stats = {r["day"]: r for r in self.repo.daily_stats(upcoming_start.isoformat(), upcoming_end.isoformat())}
        upcoming = []
        for offset in range(7):
            d = (upcoming_start + timedelta(days=offset)).isoformat()
            r = up_stats.get(d)
            upcoming.append({
                "date": d,
                "total": int(r["total"]) if r else 0,
                "expected_no_shows": round(float(r["expected_no_shows"]), 2) if r else 0.0,
                "flagged": int(r["flagged"]) if r else 0,
            })

        q = self.repo.prediction_quality(start.isoformat(), today.isoformat())
        flagged_total = q["tp"] + q["fp"]
        quality = {
            **{k: int(v) for k, v in q.items()},
            "precision": _ratio(q["tp"], flagged_total),
            "recall": _ratio(q["tp"], q["tp"] + q["fn"]),
            "accuracy": _ratio(q["tp"] + q["tn"], sum(q.values())),
        }

        def breakdown(kind: str, label) -> list[dict]:
            out = []
            for r in self.repo.breakdown(start.isoformat(), today.isoformat(), kind):
                out.append({
                    "label": label(r["bucket"]),
                    "reconciled": int(r["reconciled"]),
                    "no_shows": int(r["no_shows"]),
                    "no_show_rate": _rate(int(r["no_shows"]), int(r["reconciled"])),
                })
            return out

        info = self.model.info
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window": {"start": start.isoformat(), "end": today.isoformat(), "days": days},
            "summary": summary,
            "today": next(p for p in trend if p["date"] == today.isoformat()),
            "trend": trend,
            "upcoming": upcoming,
            "by_type": breakdown("type", str),
            "by_weekday": breakdown("weekday", lambda b: WEEKDAYS[int(b)]),
            "by_hour": breakdown("hour", lambda b: f"{int(b):02d}:00"),
            "prediction_quality": quality,
            "model": {
                "version": info.version, "kind": info.kind, "threshold": info.threshold,
                "auc": info.metrics["auc"], "n_real": info.n_real,
            },
        }
