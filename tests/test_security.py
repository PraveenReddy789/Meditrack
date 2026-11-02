import pytest

from app.config import Settings
from app.db import Database, SessionRepository, UserRepository
from app.errors import AuthenticationError, TooManyAttemptsError
from app.security import (
    ROLE_PERMISSIONS, AuthService, LoginThrottle, bootstrap_users, hash_password, hash_token, verify_password,
)


def test_hash_is_salted_and_verifies():
    a, b = hash_password("correct horse"), hash_password("correct horse")
    assert a != b
    assert verify_password("correct horse", a)
    assert not verify_password("wrong", a)


@pytest.mark.parametrize("garbage", ["", "plain", "scrypt$1$2", "bcrypt$a$b$c$d$e", "scrypt$x$y$z$!!$??"])
def test_verify_rejects_malformed_hashes(garbage):
    assert verify_password("anything", garbage) is False


def test_token_hash_is_stable_and_not_the_token():
    assert hash_token("abc") == hash_token("abc") != "abc"


def test_throttle_blocks_after_max_failures_and_recovers():
    now = [0.0]
    t = LoginThrottle(3, 60, clock=lambda: now[0])
    for _ in range(3):
        t.check("u")
        t.record_failure("u")
    with pytest.raises(TooManyAttemptsError):
        t.check("u")
    t.check("someone-else")  # other keys unaffected
    now[0] = 61
    t.check("u")  # window passed


def test_throttle_reset_clears_failures():
    t = LoginThrottle(2, 60)
    t.record_failure("u")
    t.record_failure("u")
    t.reset("u")
    t.check("u")


@pytest.fixture()
def auth(tmp_path):
    db = Database(tmp_path / "a.db")
    db.init_schema()
    users, sessions = UserRepository(db), SessionRepository(db)
    settings = Settings(bootstrap_passwords={"admin": "admin-password-1", "staff": "staff-password-1"})
    bootstrap_users(users, settings)
    return AuthService(users, sessions, settings, LoginThrottle(3, 60)), users


def test_bootstrap_creates_three_roles_and_generates_missing_password(auth, caplog):
    service, users = auth
    assert users.count() == 3
    assert users.get_by_username("auditor")["role"] == "auditor"
    # the auditor had no configured password, so a random one was created and logged once
    assert users.get_by_username("auditor")["password_hash"].startswith("scrypt$")


def test_bootstrap_rejects_short_password(tmp_path):
    db = Database(tmp_path / "b.db")
    db.init_schema()
    with pytest.raises(ValueError):
        bootstrap_users(UserRepository(db), Settings(bootstrap_passwords={"admin": "short"}))


def test_login_logout_session_lifecycle(auth):
    service, _ = auth
    token, user = service.login("admin", "admin-password-1", "1.2.3.4")
    assert user.role == "admin"
    assert service.user_for_token(token).username == "admin"
    service.logout(token)
    assert service.user_for_token(token) is None
    assert service.user_for_token(None) is None
    assert service.user_for_token("forged") is None


def test_login_failure_is_generic_and_throttled(auth):
    service, _ = auth
    for _ in range(3):
        with pytest.raises(AuthenticationError) as exc:
            service.login("admin", "nope", "ip")
        assert exc.value.message == "Invalid username or password."
    with pytest.raises(TooManyAttemptsError):
        service.login("admin", "admin-password-1", "ip")  # even the right password is blocked


def test_unknown_user_gets_same_error_as_wrong_password(auth):
    service, _ = auth
    with pytest.raises(AuthenticationError) as exc:
        service.login("ghost", "whatever", "ip")
    assert exc.value.message == "Invalid username or password."


def test_expired_session_is_rejected(tmp_path):
    db = Database(tmp_path / "e.db")
    db.init_schema()
    users, sessions = UserRepository(db), SessionRepository(db)
    settings = Settings(session_ttl_minutes=-1, bootstrap_passwords={"admin": "admin-password-1"})
    bootstrap_users(users, settings)
    service = AuthService(users, sessions, settings, LoginThrottle(5, 60))
    token, _ = service.login("admin", "admin-password-1", "ip")
    assert service.user_for_token(token) is None


def test_role_permission_matrix():
    assert "appointments:write" in ROLE_PERMISSIONS["staff"]
    assert "appointments:write" not in ROLE_PERMISSIONS["auditor"]
    assert "reports:read" in ROLE_PERMISSIONS["auditor"]
    assert "model:train" in ROLE_PERMISSIONS["admin"]
    assert "model:train" not in ROLE_PERMISSIONS["staff"]
    assert "appointments:delete" not in ROLE_PERMISSIONS["staff"]
