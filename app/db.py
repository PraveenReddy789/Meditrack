"""SQLite access: schema plus small repositories.

Each operation opens its own short-lived connection, which keeps the code safe
under FastAPI's thread pool without sharing a connection across threads.
All SQL uses bound parameters.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from app.errors import ConflictError

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'auditor')),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_name      TEXT NOT NULL,
    patient_key       TEXT NOT NULL,
    appointment_date  TEXT NOT NULL,
    appointment_time  TEXT NOT NULL,
    appointment_type  TEXT NOT NULL CHECK (appointment_type IN
                        ('checkup', 'follow_up', 'specialist', 'vaccination', 'lab_test')),
    booked_on         TEXT NOT NULL,
    lead_days         INTEGER NOT NULL CHECK (lead_days >= 0),
    status            TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled', 'attended', 'no_show')),
    risk_score        REAL,
    risk_level        TEXT,
    predicted_no_show INTEGER NOT NULL DEFAULT 0,
    model_version     TEXT,
    created_by        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    reconciled_by     TEXT,
    reconciled_at     TEXT,
    UNIQUE (patient_key, appointment_date, appointment_time)
);

CREATE INDEX IF NOT EXISTS idx_appt_date ON appointments (appointment_date);
CREATE INDEX IF NOT EXISTS idx_appt_patient ON appointments (patient_key, appointment_date);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_by_username(self, username: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def create(self, username: str, password_hash: str, role: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, role, utcnow_iso()),
            )

    def count(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


class SessionRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, token_hash: str, user_id: int, expires_at: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (utcnow_iso(),))
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash, user_id, utcnow_iso(), expires_at),
            )

    def get_user(self, token_hash: str) -> dict | None:
        """Return the owning user for a live session, or None if unknown/expired."""
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT u.id, u.username, u.role, s.expires_at
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ?""",
                (token_hash,),
            ).fetchone()
        if row is None or row["expires_at"] <= utcnow_iso():
            return None
        return dict(row)

    def delete(self, token_hash: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


class AppointmentRepository:
    def __init__(self, db: Database):
        self.db = db

    # ---- writes -----------------------------------------------------------
    def insert_many(self, rows: list[dict]) -> list[int]:
        """Insert atomically. A duplicate slot aborts the whole batch."""
        ids: list[int] = []
        with self.db.connect() as conn:
            try:
                for r in rows:
                    cur = conn.execute(
                        """INSERT INTO appointments
                           (patient_name, patient_key, appointment_date, appointment_time,
                            appointment_type, booked_on, lead_days, risk_score, risk_level,
                            predicted_no_show, model_version, created_by, created_at)
                           VALUES (:patient_name, :patient_key, :appointment_date, :appointment_time,
                                   :appointment_type, :booked_on, :lead_days, :risk_score, :risk_level,
                                   :predicted_no_show, :model_version, :created_by, :created_at)""",
                        {**r, "created_at": utcnow_iso()},
                    )
                    ids.append(cur.lastrowid)
            except sqlite3.IntegrityError as exc:
                if "UNIQUE" in str(exc):
                    raise ConflictError(
                        f"{r['patient_name']} already has an appointment on "
                        f"{r['appointment_date']} at {r['appointment_time']}"
                    ) from exc
                raise
        return ids

    def update_status(self, appt_id: int, status: str, username: str) -> bool:
        reconciled = status != "scheduled"
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE appointments SET status = ?, reconciled_by = ?, reconciled_at = ? WHERE id = ?",
                (status, username if reconciled else None, utcnow_iso() if reconciled else None, appt_id),
            )
            return cur.rowcount == 1

    def update_prediction(self, appt_id: int, risk: float, level: str, flagged: bool, version: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE appointments SET risk_score = ?, risk_level = ?, predicted_no_show = ?,
                   model_version = ? WHERE id = ?""",
                (risk, level, int(flagged), version, appt_id),
            )

    def delete(self, appt_id: int) -> bool:
        with self.db.connect() as conn:
            return conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,)).rowcount == 1

    # ---- reads ------------------------------------------------------------
    def get(self, appt_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        return dict(row) if row else None

    def list(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._filters(start, end, status)
        sql = (
            f"SELECT * FROM appointments {where} "
            "ORDER BY appointment_date, appointment_time, id LIMIT ? OFFSET ?"
        )
        with self.db.connect() as conn:
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def count(self, *, start: str | None = None, end: str | None = None, status: str | None = None) -> int:
        where, params = self._filters(start, end, status)
        with self.db.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM appointments {where}", params).fetchone()[0]

    @staticmethod
    def _filters(start, end, status) -> tuple[str, list]:
        clauses, params = [], []
        if start:
            clauses.append("appointment_date >= ?")
            params.append(start)
        if end:
            clauses.append("appointment_date <= ?")
            params.append(end)
        if status:
            clauses.append("status = ?")
            params.append(status)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def history_for(self, keys: Iterable[str]) -> dict[str, list[tuple[str, str]]]:
        """Reconciled visits per patient key as [(date, status)], oldest first."""
        keys = sorted(set(keys))
        out: dict[str, list[tuple[str, str]]] = {k: [] for k in keys}
        with self.db.connect() as conn:
            for i in range(0, len(keys), 400):  # stay well below SQLite's variable limit
                chunk = keys[i : i + 400]
                marks = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""SELECT patient_key, appointment_date, status FROM appointments
                        WHERE status IN ('attended', 'no_show') AND patient_key IN ({marks})
                        ORDER BY appointment_date""",
                    chunk,
                ).fetchall()
                for r in rows:
                    out[r["patient_key"]].append((r["appointment_date"], r["status"]))
        return out

    def reconciled_for_training(self) -> list[dict]:
        """All reconciled rows in chronological order (training input)."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT patient_key, appointment_date, appointment_time, appointment_type,
                          lead_days, status
                   FROM appointments WHERE status IN ('attended', 'no_show')
                   ORDER BY appointment_date, appointment_time, id"""
            ).fetchall()
        return [dict(r) for r in rows]

    def scheduled_rows(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE status = 'scheduled' ORDER BY appointment_date, id"
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- aggregates (used by the dashboard) -------------------------------
    def daily_stats(self, start: str, end: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT appointment_date AS day,
                          COUNT(*) AS total,
                          SUM(status = 'attended') AS attended,
                          SUM(status = 'no_show') AS no_shows,
                          SUM(status = 'scheduled') AS scheduled,
                          COALESCE(SUM(risk_score), 0.0) AS expected_no_shows,
                          SUM(predicted_no_show) AS flagged
                   FROM appointments
                   WHERE appointment_date BETWEEN ? AND ?
                   GROUP BY appointment_date ORDER BY appointment_date""",
                (start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    def breakdown(self, start: str, end: str, expr: str) -> list[dict]:
        """Reconciled outcome counts grouped by a fixed, code-defined SQL expression."""
        allowed = {
            "type": "appointment_type",
            "weekday": "CAST(strftime('%w', appointment_date) AS INTEGER)",
            "hour": "CAST(substr(appointment_time, 1, 2) AS INTEGER)",
        }
        column = allowed[expr]  # KeyError for anything unexpected; never user-supplied SQL
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT {column} AS bucket,
                           COUNT(*) AS reconciled,
                           SUM(status = 'no_show') AS no_shows
                    FROM appointments
                    WHERE status IN ('attended', 'no_show') AND appointment_date BETWEEN ? AND ?
                    GROUP BY bucket ORDER BY bucket""",
                (start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    def prediction_quality(self, start: str, end: str) -> dict:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT
                     COALESCE(SUM(predicted_no_show = 1 AND status = 'no_show'), 0) AS tp,
                     COALESCE(SUM(predicted_no_show = 1 AND status = 'attended'), 0) AS fp,
                     COALESCE(SUM(predicted_no_show = 0 AND status = 'no_show'), 0) AS fn,
                     COALESCE(SUM(predicted_no_show = 0 AND status = 'attended'), 0) AS tn
                   FROM appointments
                   WHERE status IN ('attended', 'no_show') AND appointment_date BETWEEN ? AND ?""",
                (start, end),
            ).fetchone()
        return dict(row)
