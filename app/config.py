"""Runtime configuration.

Settings are an immutable dataclass so tests can build an isolated app with
explicit values instead of mutating the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VALID_MODEL_KINDS = ("logistic", "gbm")


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=VALUE per line). Never overrides real env vars."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/meditrack.db")

    # Auth / sessions
    session_ttl_minutes: int = 480
    cookie_secure: bool = False
    login_max_failures: int = 5
    login_window_seconds: int = 300
    # username -> password. Missing entries get a random password at first start.
    bootstrap_passwords: dict[str, str] = field(default_factory=dict)

    # Model
    model_kind: str = "logistic"
    synthetic_rows: int = 6000
    real_sample_weight: float = 3.0
    random_seed: int = 42

    # Dashboard cache
    cache_ttl_seconds: int = 60
    cache_max_entries: int = 128

    # Input limits
    max_bulk_rows: int = 200

    def __post_init__(self) -> None:
        if self.model_kind not in VALID_MODEL_KINDS:
            raise ValueError(f"model_kind must be one of {VALID_MODEL_KINDS}, got {self.model_kind!r}")
        if self.synthetic_rows < 500:
            raise ValueError("synthetic_rows must be at least 500 to train a usable model")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        passwords = {}
        for user in ("admin", "staff", "auditor"):
            value = os.environ.get(f"MEDITRACK_{user.upper()}_PASSWORD")
            if value:
                passwords[user] = value
        return cls(
            db_path=Path(os.environ.get("MEDITRACK_DB_PATH", "data/meditrack.db")),
            cookie_secure=_env_bool("MEDITRACK_COOKIE_SECURE", False),
            model_kind=os.environ.get("MEDITRACK_MODEL_KIND", "logistic"),
            cache_ttl_seconds=int(os.environ.get("MEDITRACK_CACHE_TTL_SECONDS", "60")),
            bootstrap_passwords=passwords,
        )
