"""Error handling, headers, session cookie flags and sign-in throttling."""
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import PASSWORDS, appt, make_settings


def test_wrong_credentials_get_a_generic_401(client):
    r = client.post("/api/auth/login", json={"username": "staff", "password": "wrong"})
    assert r.status_code == 401 and r.json() == {"detail": "Invalid username or password."}
    r = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
    assert r.status_code == 401 and r.json() == {"detail": "Invalid username or password."}


def test_repeated_failures_lock_the_account_for_that_client(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "staff", "password": "bad"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "staff", "password": PASSWORDS["staff"]})
    assert r.status_code == 429
    # a different account is unaffected
    assert client.post("/api/auth/login", json={"username": "auditor", "password": PASSWORDS["auditor"]}).status_code == 200


def test_validation_errors_never_echo_submitted_secrets(client):
    r = client.post("/api/auth/login", json={"username": "staff", "password": "my-secret-pw", "extra": 1})
    assert r.status_code == 422
    assert "my-secret-pw" not in r.text
    assert all(set(e) == {"loc", "msg", "type"} for e in r.json()["detail"])


def test_session_cookie_flags(client):
    r = client.post("/api/auth/login", json={"username": "staff", "password": PASSWORDS["staff"]})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "secure" not in cookie.replace("samesite", "")  # off for plain-http local demo


def test_cookie_is_secure_when_configured(tmp_path):
    app = create_app(make_settings(tmp_path, cookie_secure=True))
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "staff", "password": PASSWORDS["staff"]})
        assert "secure" in r.headers["set-cookie"].lower()


def test_security_headers_on_every_response(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_unexpected_server_errors_do_not_leak_details(app):
    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret internals: /home/user/db.sqlite")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/boom")
        assert r.status_code == 500
        assert r.json() == {"detail": "Internal server error."}
        assert "secret" not in r.text


def test_api_rejects_sql_injection_shaped_input_safely(clients):
    staff = clients["staff"]
    staff.post("/api/appointments", json=appt(name="Safe Person"))
    assert staff.get("/api/appointments?status=scheduled' OR '1'='1").status_code == 422
    assert staff.get("/api/appointments?date=2026-01-01'; DROP TABLE appointments;--").status_code == 422
    assert staff.get("/api/appointments").json()["total"] == 1


def test_health_endpoint_is_public_and_minimal(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"status", "model_version"}
