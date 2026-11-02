import csv
import io
from datetime import date

from app.services.reports import safe_cell
from tests.conftest import appt


def parse(response):
    text = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_appointment_report_contains_every_visit_with_risk_and_outcome(clients):
    staff = clients["staff"]
    a = staff.post("/api/appointments", json=appt(name="Asha Rao")).json()
    staff.post("/api/appointments", json=appt(name="Ben Cole", time="10:00"))
    staff.patch(f"/api/appointments/{a['id']}", json={"status": "no_show"})

    r = staff.get("/api/reports/no-show.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    today = date.today().isoformat()
    assert f"meditrack-no-show-appointments-" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("attachment;")
    rows = parse(r)
    assert [x["patient_name"] for x in rows] == ["Asha Rao", "Ben Cole"]
    first = rows[0]
    assert (first["date"], first["time"], first["status"]) == (today, "09:30", "no_show")
    assert 0 <= float(first["risk_score"]) <= 1 and first["reconciled_by"] == "staff"
    assert first["model_version"].startswith("logistic-")


def test_daily_report_matches_dashboard_numbers(clients):
    staff = clients["staff"]
    for i, status in enumerate(["no_show", "attended", "attended"]):
        c = staff.post("/api/appointments", json=appt(name=f"Daily {'ABC'[i]}", time=f"{9 + i:02d}:00")).json()
        staff.patch(f"/api/appointments/{c['id']}", json={"status": status})
    rows = parse(staff.get("/api/reports/no-show.csv?kind=daily"))
    assert len(rows) == 30  # one row per day, including empty days
    last = rows[-1]
    assert last["date"] == date.today().isoformat()
    assert (last["total"], last["no_shows"], last["attended"]) == ("3", "1", "2")
    assert float(last["no_show_rate"]) == round(1 / 3, 4)
    assert rows[0]["no_show_rate"] == ""  # no reconciled visits -> blank rather than 0 or an error


def test_date_range_filter(clients):
    staff = clients["staff"]
    staff.post("/api/appointments", json=appt(name="Today Person"))
    staff.post("/api/appointments", json=appt(name="Future Person", days=5))
    today = date.today().isoformat()
    rows = parse(staff.get(f"/api/reports/no-show.csv?start={today}&end={today}"))
    assert [r["patient_name"] for r in rows] == ["Today Person"]


def test_auditor_can_export_and_anon_cannot(clients):
    assert clients["auditor"].get("/api/reports/no-show.csv").status_code == 200
    assert clients["anon"].get("/api/reports/no-show.csv").status_code == 401


def test_report_input_validation(clients):
    staff = clients["staff"]
    assert staff.get("/api/reports/no-show.csv?kind=everything").status_code == 422
    assert staff.get("/api/reports/no-show.csv?start=2026-02-01&end=2026-01-01").status_code == 422
    assert staff.get("/api/reports/no-show.csv?start=2020-01-01&end=2026-01-01").status_code == 422
    assert staff.get("/api/reports/no-show.csv?start=banana").status_code == 422


def test_empty_report_still_has_a_header_row(clients):
    r = clients["staff"].get("/api/reports/no-show.csv")
    assert r.content.decode("utf-8-sig").splitlines()[0].startswith("date,time,patient_name")
    assert parse(r) == []


def test_formula_injection_is_neutralised():
    assert safe_cell("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    for dangerous in ("+1+1", "-2+3", "@SUM(A1)", "\tcmd"):
        assert safe_cell(dangerous).startswith("'")
    assert safe_cell("Asha Rao") == "Asha Rao"
    assert safe_cell(0.25) == 0.25


def test_hostile_stored_value_is_escaped_in_the_export(clients):
    """Even if a dangerous string reached the database, the CSV must not carry a live formula."""
    state = clients["anon"].app.state.ctx
    d = date.today().isoformat()
    state.appointments_repo.insert_many([dict(
        patient_name="=cmd|' /C calc'!A0", patient_key="evil", appointment_date=d, appointment_time="09:00",
        appointment_type="checkup", booked_on=d, lead_days=0, risk_score=0.1, risk_level="low",
        predicted_no_show=0, model_version="v", created_by="t",
    )])
    rows = parse(clients["staff"].get("/api/reports/no-show.csv"))
    assert rows[0]["patient_name"].startswith("'=")
