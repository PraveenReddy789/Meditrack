from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from app.deps import AppState, get_state, require
from app.security import REPORTS_READ, AuthUser

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/dashboard")
def dashboard(
    response: Response,
    days: int = Query(30, ge=1, le=365, description="Look-back window ending today"),
    _: AuthUser = Depends(require(REPORTS_READ)),
    state: AppState = Depends(get_state),
):
    key = ("dashboard", days, date.today().isoformat())
    data, hit = state.cache.get_or_compute(key, lambda: state.dashboard.build(days))
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    return data


@router.get("/reports/no-show.csv")
def export_no_show_report(
    kind: str = Query("appointments", description="'appointments' (one row per visit) or 'daily' (one row per day)"),
    start: date | None = None,
    end: date | None = None,
    _: AuthUser = Depends(require(REPORTS_READ)),
    state: AppState = Depends(get_state),
):
    s, e = state.reports.resolve_range(start, end)
    body = state.reports.build_csv(kind, s, e)
    filename = f"meditrack-no-show-{kind}-{s.isoformat()}_{e.isoformat()}.csv"
    # BOM so Excel opens UTF-8 names (e.g. accented characters) correctly.
    return Response(
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
