import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import appt, make_settings, PASSWORDS


def test_create_single_appointment_is_scored_and_stored(clients):
    r = clients["staff"].post("/api/appointments", json=appt(days=3, typ="specialist"))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "scheduled" and body["created_by"] == "staff"
    assert body["lead_days"] == 3 and body["appointment_type"] == "specialist"
    assert 0.0 <= body["risk_score"] <= 1.0
    assert body["risk_level"] in {"low", "medium", "high"}
    assert body["model_version"].startswith("logistic-")


def test_bulk_create_scores_every_row(clients):
    rows = [appt(name=f"Patient {c}", time=f"{9 + i:02d}:00") for i, c in enumerate("Alpha Bravo Charlie".split())]
    r = clients["staff"].post("/api/appointments/bulk", json={"appointments": rows})
    assert r.status_code == 201 and len(r.json()) == 3
    assert all(a["risk_score"] is not None for a in r.json())


def test_bulk_is_all_or_nothing_when_a_row_is_invalid(clients):
    rows = [appt(name="Good Patient"), appt(name="Bad Patient", time="23:00")]
    r = clients["staff"].post("/api/appointments/bulk", json={"appointments": rows})
    assert r.status_code == 422
    assert clients["staff"].get("/api/appointments").json()["total"] == 0


def test_bulk_respects_row_limit(tmp_path):
    app = create_app(make_settings(tmp_path, max_bulk_rows=2))
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"username": "staff", "password": PASSWORDS["staff"]})
        rows = [appt(name=f"Patient {n}", time=f"{9 + i:02d}:00") for i, n in enumerate(["One", "Two", "Three"])]
        r = c.post("/api/appointments/bulk", json={"appointments": rows})
        assert r.status_code == 422 and "At most 2" in r.json()["detail"]


def test_empty_bulk_is_rejected(clients):
    assert clients["staff"].post("/api/appointments/bulk", json={"appointments": []}).status_code == 422


@pytest.mark.parametrize("bad", [
    {"patient_name": "<script>x</script>"},
    {"appointment_time": "25:99"},
    {"appointment_type": "dentist"},
    {"unexpected": "field"},
])
def test_invalid_input_is_rejected_with_422(clients, bad):
    r = clients["staff"].post("/api/appointments", json={**appt(), **bad})
    assert r.status_code == 422
    assert clients["staff"].get("/api/appointments").json()["total"] == 0


def test_duplicate_slot_is_a_conflict_even_with_different_case(clients):
    staff = clients["staff"]
    assert staff.post("/api/appointments", json=appt(name="Asha Rao")).status_code == 201
    r = staff.post("/api/appointments", json=appt(name="  ASHA   rao "))
    assert r.status_code == 409 and "already has an appointment" in r.json()["detail"]


def test_duplicate_inside_one_upload_is_rejected_and_nothing_saved(clients):
    rows = [appt(name="Twin Patient"), appt(name="twin patient")]
    r = clients["staff"].post("/api/appointments/bulk", json={"appointments": rows})
    assert r.status_code == 409
    assert clients["staff"].get("/api/appointments").json()["total"] == 0


def test_reconcile_and_undo(clients):
    staff = clients["staff"]
    appt_id = staff.post("/api/appointments", json=appt()).json()["id"]
    r = staff.patch(f"/api/appointments/{appt_id}", json={"status": "no_show"})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["reconciled_by"]) == ("no_show", "staff")
    assert r.json()["reconciled_at"]
    r = staff.patch(f"/api/appointments/{appt_id}", json={"status": "scheduled"})
    assert r.json()["status"] == "scheduled" and r.json()["reconciled_by"] is None


def test_reconcile_unknown_or_invalid(clients):
    staff = clients["staff"]
    assert staff.patch("/api/appointments/424242", json={"status": "attended"}).status_code == 404
    appt_id = staff.post("/api/appointments", json=appt()).json()["id"]
    assert staff.patch(f"/api/appointments/{appt_id}", json={"status": "cancelled"}).status_code == 422
    assert staff.patch("/api/appointments/0", json={"status": "attended"}).status_code == 422


def test_list_filters_and_pagination(clients):
    staff = clients["staff"]
    for i in range(5):
        staff.post("/api/appointments", json=appt(name=f"Person {'ABCDE'[i]}", time=f"{9 + i:02d}:00"))
    staff.post("/api/appointments", json=appt(name="Tomorrow Person", days=1))
    first = staff.get("/api/appointments").json()["items"][0]["id"]
    staff.patch(f"/api/appointments/{first}", json={"status": "attended"})

    from datetime import date
    today = date.today().isoformat()
    day = staff.get(f"/api/appointments?date={today}").json()
    assert day["total"] == 5
    assert staff.get("/api/appointments?status=attended").json()["total"] == 1
    page = staff.get("/api/appointments?limit=2&offset=1").json()
    assert len(page["items"]) == 2 and page["total"] == 6
    assert staff.get("/api/appointments?limit=0").status_code == 422
    assert staff.get("/api/appointments?limit=501").status_code == 422
    assert staff.get("/api/appointments?start=2026-02-01&end=2026-01-01").status_code == 422


def test_patient_history_raises_predicted_risk(clients):
    staff = clients["staff"]

    def history(name, status):
        for d in (-40, -30, -20, -10):
            created = staff.post("/api/appointments", json=appt(name=name, days=d, time="09:00")).json()
            staff.patch(f"/api/appointments/{created['id']}", json={"status": status})

    history("Repeat Rita", "no_show")
    history("Reliable Ravi", "attended")
    rita = staff.post("/api/appointments", json=appt(name="Repeat Rita", days=7)).json()
    ravi = staff.post("/api/appointments", json=appt(name="Reliable Ravi", days=7)).json()
    assert rita["risk_score"] > ravi["risk_score"] + 0.1


def test_delete_is_admin_only(clients):
    appt_id = clients["staff"].post("/api/appointments", json=appt()).json()["id"]
    assert clients["staff"].delete(f"/api/appointments/{appt_id}").status_code == 403
    assert clients["admin"].delete(f"/api/appointments/{appt_id}").status_code == 204
    assert clients["admin"].delete(f"/api/appointments/{appt_id}").status_code == 404
    assert clients["staff"].get("/api/appointments").json()["total"] == 0
