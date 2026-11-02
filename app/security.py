"""Password hashing, sessions, login throttling and the role/permission model."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.config import Settings
from app.db import SessionRepository, UserRepository
from app.errors import AuthenticationError, TooManyAttemptsError

log = logging.getLogger("meditrack.security")

# ---------------------------------------------------------------------------
# Roles and permissions
# ---------------------------------------------------------------------------
APPOINTMENTS_READ = "appointments:read"
APPOINTMENTS_WRITE = "appointments:write"
APPOINTMENTS_DELETE = "appointments:delete"
REPORTS_READ = "reports:read"
MODEL_TRAIN = "model:train"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # Full access, including retraining the model and deleting records.
    "admin": frozenset({APPOINTMENTS_READ, APPOINTMENTS_WRITE, APPOINTMENTS_DELETE, REPORTS_READ, MODEL_TRAIN}),
    # Front-desk staff: enter appointments, reconcile them, read reports.
    "staff": frozenset({APPOINTMENTS_READ, APPOINTMENTS_WRITE, REPORTS_READ}),
    # Read-only reviewer: can see appointments and reports but cannot change data.
    "auditor": frozenset({APPOINTMENTS_READ, REPORTS_READ}),
}


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS.get(self.role, frozenset())

    def can(self, permission: str) -> bool:
        return permission in self.permissions


# ---------------------------------------------------------------------------
# Password hashing (scrypt from the standard library, no extra dependency)
# ---------------------------------------------------------------------------
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when the username is unknown so response time doesn't reveal it.
_DUMMY_HASH = hash_password("not-a-real-password")


def hash_token(token: str) -> str:
    """Sessions are stored as SHA-256 of the token; a DB leak doesn't leak live sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------
class LoginThrottle:
    """Blocks a (username, client) pair after too many failures in a sliding window."""

    def __init__(self, max_failures: int, window_seconds: int, clock: Callable[[], float] = time.monotonic):
        self.max_failures = max_failures
        self.window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str) -> deque[float]:
        q = self._failures[key]
        cutoff = self._clock() - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
            return self._failures[key]
        return q

    def check(self, key: str) -> None:
        with self._lock:
            if len(self._prune(key)) >= self.max_failures:
                raise TooManyAttemptsError("Too many failed sign-in attempts. Try again in a few minutes.")

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# ---------------------------------------------------------------------------
# Authentication service
# ---------------------------------------------------------------------------
class AuthService:
    def __init__(self, users: UserRepository, sessions: SessionRepository, settings: Settings,
                 throttle: LoginThrottle):
        self.users = users
        self.sessions = sessions
        self.ttl = timedelta(minutes=settings.session_ttl_minutes)
        self.throttle = throttle

    def login(self, username: str, password: str, client: str) -> tuple[str, AuthUser]:
        key = f"{username.casefold()}|{client}"
        self.throttle.check(key)
        row = self.users.get_by_username(username)
        ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
        if not (row and ok):
            self.throttle.record_failure(key)
            raise AuthenticationError("Invalid username or password.")
        self.throttle.reset(key)
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + self.ttl).isoformat(timespec="seconds")
        self.sessions.create(hash_token(token), row["id"], expires)
        return token, AuthUser(row["id"], row["username"], row["role"])

    def user_for_token(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        row = self.sessions.get_user(hash_token(token))
        return AuthUser(row["id"], row["username"], row["role"]) if row else None

    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.delete(hash_token(token))


def bootstrap_users(users: UserRepository, settings: Settings) -> None:
    """Create the three built-in accounts on first start.

    Passwords come from the environment. If one isn't set, a random password is
    generated and logged exactly once; no default password exists in the code.
    """
    for username, role in (("admin", "admin"), ("staff", "staff"), ("auditor", "auditor")):
        if users.get_by_username(username):
            continue
        password = settings.bootstrap_passwords.get(username)
        if password is None:
            password = secrets.token_urlsafe(12)
            log.warning("Generated password for '%s': %s (shown once; set MEDITRACK_%s_PASSWORD to choose one)",
                        username, password, username.upper())
        elif len(password) < 10:
            raise ValueError(f"Password for '{username}' must be at least 10 characters")
        users.create(username, hash_password(password), role)
