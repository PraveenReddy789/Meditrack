from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PASSWORDS = {"admin": "admin-test-pass-1", "staff": "staff-test-pass-1", "auditor": "auditor-test-pass-1"}


def make_settings(tmp_path, **overrides) -> Settings:
    base = dict(
        db_path=tmp_path / "test.db",
        bootstrap_passwords=dict(PASSWORDS),
        synthetic_rows=1500,  # keeps app start-up (model training) fast in tests
        cache_ttl_seconds=60,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def app(tmp_path):
    return create_app(make_settings(tmp_path))


@pytest.fixture()
def client(app):
    """Anonymous client. The lifespan runs (and the model trains) inside the with-block."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def clients(app):
    """One signed-in client per role, sharing one app and database."""
    with TestClient(app) as anon:
        made = {"anon": anon}
        for role in ("admin", "staff", "auditor"):
            c = TestClient(app)
            r = c.post("/api/auth/login", json={"username": role, "password": PASSWORDS[role]})
            assert r.status_code == 200, r.text
            made[role] = c
        yield made


def appt(name="Asha Rao", days=0, time="09:30", typ="checkup", **extra):
    return {
        "patient_name": name,
        "appointment_date": (date.today() + timedelta(days=days)).isoformat(),
        "appointment_time": time,
        "appointment_type": typ,
        **extra,
    }
