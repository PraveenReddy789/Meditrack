"""CSV export of the no-show analysis."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from app.db import AppointmentRepository
from app.errors import ValidationFailedError
from app.services.dashboard import DashboardService

MAX_RANGE_DAYS = 366
KINDS = ("appointments", "daily")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

APPOINTMENT_COLUMNS = (
    "date", "time", "patient_name", "appointment_type", "lead_days", "status",
    "risk_score", "risk_level", "predicted_no_show", "model_version", "reconciled_by",
)
DAILY_COLUMNS = (
    "date", "total", "attended", "no_shows", "scheduled", "no_show_rate",
    "rate_7d", "expected_no_shows", "flagged",
)


def safe_cell(value):
    """Neutralise spreadsheet formula injection (a cell starting with = + - @ runs as a formula in Excel)."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


class ReportService:
    def __init__(self, repo: AppointmentRepository, dashboard: DashboardService):
        self.repo = repo
        self.dashboard = dashboard

    @staticmethod
    def resolve_range(start: date | None, end: date | None) -> tuple[date, date]:
        end = end or date.today()
        start = start or end - timedelta(days=29)
        if start > end:
            raise ValidationFailedError("start must not be after end")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ValidationFailedError(f"date range may not exceed {MAX_RANGE_DAYS} days")
        return start, end

    def build_csv(self, kind: str, start: date, end: date) -> str:
        if kind not in KINDS:
            raise ValidationFailedError(f"kind must be one of: {', '.join(KINDS)}")
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        if kind == "appointments":
            writer.writerow(APPOINTMENT_COLUMNS)
            for r in self.repo.list(start=start.isoformat(), end=end.isoformat(), limit=50_000):
                writer.writerow([safe_cell(v) for v in (
                    r["appointment_date"], r["appointment_time"], r["patient_name"], r["appointment_type"],
                    r["lead_days"], r["status"], r["risk_score"], r["risk_level"], r["predicted_no_show"],
                    r["model_version"], r["reconciled_by"] or "",
                )])
        else:
            data = self.dashboard.build((end - start).days + 1, today=end)
            writer.writerow(DAILY_COLUMNS)
            for p in data["trend"]:
                writer.writerow([safe_cell("" if p.get(c) is None else p[c]) for c in DAILY_COLUMNS])
        return buf.getvalue()
