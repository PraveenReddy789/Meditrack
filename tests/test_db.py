import pytest

from app.db import AppointmentRepository, Database
from app.errors import ConflictError


@pytest.fixture()
def repo(tmp_path):
    db = Database(tmp_path / "t.db")
    db.init_schema()
    return AppointmentRepository(db)


def row(name="asha rao", day="2026-01-05", time="09:30", **kw):
    base = dict(
        patient_name=name.title(), patient_key=name, appointment_date=day, appointment_time=time,
        appointment_type="checkup", booked_on=day, lead_days=0, risk_score=0.2, risk_level="low",
        predicted_no_show=0, model_version="v1", created_by="staff",
    )
    base.update(kw)
    return base


def test_insert_and_get(repo):
    (appt_id,) = repo.insert_many([row()])
    got = repo.get(appt_id)
    assert got["patient_name"] == "Asha Rao"
    assert got["status"] == "scheduled"


def test_duplicate_slot_is_conflict_and_batch_is_atomic(repo):
    repo.insert_many([row()])
    with pytest.raises(ConflictError):
        repo.insert_many([row(name="new person", time="10:00"), row()])
    # the valid first row of the failed batch must not have been committed
    assert repo.count() == 1


def test_update_status_sets_and_clears_reconciliation(repo):
    (appt_id,) = repo.insert_many([row()])
    assert repo.update_status(appt_id, "no_show", "staff")
    got = repo.get(appt_id)
    assert (got["status"], got["reconciled_by"]) == ("no_show", "staff")
    assert got["reconciled_at"]
    assert repo.update_status(appt_id, "scheduled", "staff")
    got = repo.get(appt_id)
    assert got["reconciled_by"] is None and got["reconciled_at"] is None
    assert not repo.update_status(9999, "attended", "staff")


def test_list_filters_and_pagination(repo):
    repo.insert_many([row(name=f"p{i}", day=f"2026-01-0{i}") for i in range(1, 6)])
    assert len(repo.list(start="2026-01-02", end="2026-01-04")) == 3
    assert [r["appointment_date"] for r in repo.list(limit=2, offset=1)] == ["2026-01-02", "2026-01-03"]
    assert repo.count(status="scheduled") == 5


def test_history_only_includes_reconciled_visits(repo):
    ids = repo.insert_many([
        row(day="2026-01-01"), row(day="2026-01-02"), row(day="2026-01-03"),
    ])
    repo.update_status(ids[0], "attended", "s")
    repo.update_status(ids[1], "no_show", "s")
    hist = repo.history_for(["asha rao", "nobody"])
    assert hist["asha rao"] == [("2026-01-01", "attended"), ("2026-01-02", "no_show")]
    assert hist["nobody"] == []


def test_breakdown_rejects_unknown_expression(repo):
    with pytest.raises(KeyError):
        repo.breakdown("2026-01-01", "2026-01-31", "1; DROP TABLE appointments")
