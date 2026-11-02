from datetime import date, timedelta

from app.services.dashboard import DashboardService
from tests.conftest import appt


def _state(clients):
    return clients["anon"].app.state.ctx


def _seed_day(staff, day_offset, outcomes):
    """Create one appointment per outcome on a day and reconcile it ('scheduled' stays open)."""
    for i, outcome in enumerate(outcomes):
        created = staff.post(
            "/api/appointments",
            json=appt(name=f"Seed {'abcdefghij'[abs(day_offset)]} {'abcdefghij'[i]}", days=day_offset, time=f"{9 + i:02d}:00"),
        ).json()
        if outcome != "scheduled":
            staff.patch(f"/api/appointments/{created['id']}", json={"status": outcome})


def test_empty_dashboard_has_zeroes_and_no_division_errors(clients):
    r = clients["staff"].get("/api/dashboard?days=14")
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["appointments"] == 0 and d["summary"]["no_show_rate"] is None
    assert len(d["trend"]) == 14 and d["trend"][-1]["date"] == date.today().isoformat()
    assert d["prediction_quality"]["precision"] is None
    assert len(d["upcoming"]) == 7


def test_summary_counts_and_rate_exclude_unreconciled_visits(clients):
    staff = clients["staff"]
    _seed_day(staff, 0, ["attended", "attended", "no_show", "scheduled"])
    d = staff.get("/api/dashboard?days=7").json()
    s = d["summary"]
    assert (s["appointments"], s["reconciled"], s["attended"], s["no_shows"], s["scheduled"]) == (4, 3, 2, 1, 1)
    assert s["no_show_rate"] == round(1 / 3, 4)  # the open visit is not counted as attendance
    assert d["today"]["no_shows"] == 1 and d["today"]["total"] == 4
    assert s["expected_no_shows"] > 0  # model risk scores are aggregated
    q = d["prediction_quality"]
    assert q["tp"] + q["fp"] + q["fn"] + q["tn"] == 3  # only reconciled visits are scored against reality


def test_upcoming_days_show_predicted_load_without_outcomes(clients):
    staff = clients["staff"]
    _seed_day(staff, 2, ["scheduled", "scheduled"])
    up = staff.get("/api/dashboard").json()["upcoming"]
    target = (date.today() + timedelta(days=2)).isoformat()
    row = next(u for u in up if u["date"] == target)
    assert row["total"] == 2 and row["expected_no_shows"] > 0


def test_breakdowns_group_reconciled_visits(clients):
    staff = clients["staff"]
    _seed_day(staff, -1, ["no_show", "attended"])
    d = staff.get("/api/dashboard?days=7").json()
    assert d["by_type"] == [{"label": "checkup", "reconciled": 2, "no_shows": 1, "no_show_rate": 0.5}]
    assert sum(b["reconciled"] for b in d["by_weekday"]) == 2
    assert {b["label"] for b in d["by_hour"]} == {"09:00", "10:00"}


def test_rolling_rate_uses_a_seven_day_window(clients):
    state = _state(clients)
    repo = state.appointments_repo
    rows, today = [], date(2026, 3, 10)
    for offset, status in ((0, "no_show"), (1, "attended"), (8, "no_show")):  # day 8 is outside the window
        d = (today - timedelta(days=offset)).isoformat()
        rows.append(dict(
            patient_name="P", patient_key=f"p{offset}", appointment_date=d, appointment_time="09:00",
            appointment_type="checkup", booked_on=d, lead_days=0, risk_score=0.3, risk_level="medium",
            predicted_no_show=1, model_version="v", created_by="t",
        ))
    ids = repo.insert_many(rows)
    for i, (_, status) in zip(ids, ((0, "no_show"), (1, "attended"), (8, "no_show"))):
        repo.update_status(i, status, "t")
    data = DashboardService(repo, state.model).build(10, today=today)
    assert data["trend"][-1]["rate_7d"] == 0.5  # 1 no-show of 2 reconciled in the last 7 days
    assert data["trend"][1]["rate_7d"] == 1.0   # day 8: the old no-show on its own
    assert data["trend"][8]["rate_7d"] == 0.0   # day 1: the day-8 no-show has dropped out of the window


def test_dashboard_is_cached_and_invalidated_by_writes(clients):
    staff = clients["staff"]
    assert staff.get("/api/dashboard?days=30").headers["x-cache"] == "MISS"
    assert staff.get("/api/dashboard?days=30").headers["x-cache"] == "HIT"
    assert staff.get("/api/dashboard?days=7").headers["x-cache"] == "MISS"  # separate key per window

    created = staff.post("/api/appointments", json=appt()).json()
    after_create = staff.get("/api/dashboard?days=30")
    assert after_create.headers["x-cache"] == "MISS"
    assert after_create.json()["summary"]["appointments"] == 1  # fresh data, not the cached empty result

    assert staff.get("/api/dashboard?days=30").headers["x-cache"] == "HIT"
    staff.patch(f"/api/appointments/{created['id']}", json={"status": "no_show"})
    after_reconcile = staff.get("/api/dashboard?days=30")
    assert after_reconcile.headers["x-cache"] == "MISS"
    assert after_reconcile.json()["summary"]["no_shows"] == 1

    assert staff.get("/api/dashboard?days=30").headers["x-cache"] == "HIT"
    clients["admin"].delete(f"/api/appointments/{created['id']}")
    assert staff.get("/api/dashboard?days=30").headers["x-cache"] == "MISS"


def test_failed_write_does_not_invalidate_cache(clients):
    staff = clients["staff"]
    staff.get("/api/dashboard")
    assert staff.post("/api/appointments", json=appt(time="23:00")).status_code == 422
    assert staff.get("/api/dashboard").headers["x-cache"] == "HIT"


def test_dashboard_window_validation(clients):
    staff = clients["staff"]
    assert staff.get("/api/dashboard?days=0").status_code == 422
    assert staff.get("/api/dashboard?days=366").status_code == 422
    assert staff.get("/api/dashboard?days=abc").status_code == 422


def test_retrain_refreshes_model_and_invalidates_cache(clients):
    staff, admin = clients["staff"], clients["admin"]
    staff.post("/api/appointments", json=appt(days=3))
    old = staff.get("/api/model").json()["version"]
    staff.get("/api/dashboard")
    r = admin.post("/api/model/retrain")
    assert r.status_code == 200 and r.json()["rescored_appointments"] == 1
    assert staff.get("/api/dashboard").headers["x-cache"] == "MISS"
    new = staff.get("/api/model").json()
    assert new["version"] != old or new["trained_at"] >= r.json()["trained_at"]
    assert staff.get("/api/appointments").json()["items"][0]["model_version"] == r.json()["version"]


def test_concurrent_retrain_is_refused(clients):
    state = _state(clients)
    assert state.retrain_lock.acquire(blocking=False)
    try:
        r = clients["admin"].post("/api/model/retrain")
        assert r.status_code == 409
    finally:
        state.retrain_lock.release()
