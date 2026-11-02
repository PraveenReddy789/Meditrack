"""Role-based access control: every protected endpoint against every role."""
import pytest

from tests.conftest import appt

# (method, path, json body, roles allowed to reach the handler)
ENDPOINTS = [
    ("GET", "/api/auth/me", None, {"admin", "staff", "auditor"}),
    ("GET", "/api/appointments", None, {"admin", "staff", "auditor"}),
    ("POST", "/api/appointments", "appt", {"admin", "staff"}),
    ("POST", "/api/appointments/bulk", "bulk", {"admin", "staff"}),
    ("PATCH", "/api/appointments/999", {"status": "attended"}, {"admin", "staff"}),
    ("DELETE", "/api/appointments/999", None, {"admin"}),
    ("GET", "/api/dashboard", None, {"admin", "staff", "auditor"}),
    ("GET", "/api/reports/no-show.csv", None, {"admin", "staff", "auditor"}),
    ("GET", "/api/model", None, {"admin", "staff", "auditor"}),
    ("POST", "/api/model/retrain", None, {"admin"}),
]


def body_for(spec, n):
    if spec == "appt":
        return appt(name=f"Test Person {'abcdefghij'[n]}")
    if spec == "bulk":
        return {"appointments": [appt(name=f"Bulk Person {'abcdefghij'[n]}")]}
    return spec


@pytest.mark.parametrize("method,path,spec,allowed", ENDPOINTS, ids=[f"{m} {p}" for m, p, _, _ in ENDPOINTS])
def test_endpoint_access_by_role(clients, method, path, spec, allowed):
    n = ENDPOINTS.index((method, path, spec, allowed))

    anon = clients["anon"].request(method, path, json=body_for(spec, n))
    assert anon.status_code == 401, "unauthenticated requests must be rejected"

    for role in ("admin", "staff", "auditor"):
        r = clients[role].request(method, path, json=body_for(spec, n))
        if role in allowed:
            assert r.status_code not in (401, 403), f"{role} should be allowed: {r.status_code} {r.text}"
        else:
            assert r.status_code == 403, f"{role} must be forbidden, got {r.status_code}"


def test_auditor_cannot_change_data_but_can_read_it(clients):
    created = clients["staff"].post("/api/appointments", json=appt()).json()
    aud = clients["auditor"]
    assert aud.get("/api/appointments").json()["total"] == 1
    assert aud.patch(f"/api/appointments/{created['id']}", json={"status": "no_show"}).status_code == 403
    assert aud.post("/api/appointments", json=appt(name="Someone Else")).status_code == 403
    # and nothing changed
    assert clients["staff"].get("/api/appointments").json()["items"][0]["status"] == "scheduled"


def test_forged_or_stale_session_cookie_is_rejected(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        c.cookies.set("meditrack_session", "not-a-real-token")
        assert c.get("/api/appointments").status_code == 401


def test_logout_revokes_the_session_server_side(clients):
    staff = clients["staff"]
    token = staff.cookies.get("meditrack_session")
    assert staff.get("/api/auth/me").status_code == 200
    assert staff.post("/api/auth/logout").status_code == 200
    staff.cookies.set("meditrack_session", token)  # replay the old token
    assert staff.get("/api/auth/me").status_code == 401
