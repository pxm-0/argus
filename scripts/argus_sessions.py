from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SESSION_TTL_SECONDS = 15 * 60
STEP_UP_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class Session:
    session_id: str
    identity: str
    csrf_token: str
    created_at: int
    expires_at: int
    step_up_at: int

    @property
    def step_up_valid(self) -> bool:
        return self.step_up_at > 0 and int(time.time()) - self.step_up_at <= STEP_UP_TTL_SECONDS


class SessionStore:
    def __init__(self, path: Path, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_sessions (
                    session_hash TEXT PRIMARY KEY,
                    identity TEXT NOT NULL,
                    csrf_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    step_up_at INTEGER NOT NULL DEFAULT 0,
                    revoked_at INTEGER
                )
                """
            )

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def create(self, identity: str, *, stepped_up: bool = True) -> Session:
        current = int(time.time())
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session = Session(
            session_id=session_id,
            identity=identity,
            csrf_token=csrf_token,
            created_at=current,
            expires_at=current + self.ttl_seconds,
            step_up_at=current if stepped_up else 0,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO operator_sessions VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    self._hash(session_id),
                    identity,
                    self._hash(csrf_token),
                    session.created_at,
                    session.expires_at,
                    session.step_up_at,
                ),
            )
        return session

    def get(self, session_id: str, identity: str) -> Session | None:
        if not session_id or not identity:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT identity, created_at, expires_at, step_up_at
                FROM operator_sessions
                WHERE session_hash = ? AND identity = ? AND revoked_at IS NULL
                """,
                (self._hash(session_id), identity),
            ).fetchone()
        if row is None or int(row["expires_at"]) <= int(time.time()):
            return None
        return Session(
            session_id=session_id,
            identity=str(row["identity"]),
            csrf_token="",
            created_at=int(row["created_at"]),
            expires_at=int(row["expires_at"]),
            step_up_at=int(row["step_up_at"]),
        )

    def csrf_valid(self, session_id: str, csrf_token: str) -> bool:
        if not session_id or not csrf_token:
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT csrf_hash FROM operator_sessions WHERE session_hash = ? AND revoked_at IS NULL",
                (self._hash(session_id),),
            ).fetchone()
        return row is not None and secrets.compare_digest(str(row["csrf_hash"]), self._hash(csrf_token))

    def rotate_csrf(self, session_id: str) -> str:
        csrf_token = secrets.token_urlsafe(32)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operator_sessions SET csrf_hash = ?
                WHERE session_hash = ? AND revoked_at IS NULL AND expires_at > ?
                """,
                (self._hash(csrf_token), self._hash(session_id), int(time.time())),
            )
        return csrf_token if cursor.rowcount == 1 else ""

    def revoke(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE operator_sessions SET revoked_at = ? WHERE session_hash = ?",
                (int(time.time()), self._hash(session_id)),
            )

    def revoke_identity(self, identity: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE operator_sessions SET revoked_at = ? WHERE identity = ? AND revoked_at IS NULL",
                (int(time.time()), identity),
            )
        return int(cursor.rowcount)

    def step_up(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE operator_sessions SET step_up_at = ? WHERE session_hash = ? AND revoked_at IS NULL",
                (int(time.time()), self._hash(session_id)),
            )

    def purge(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM operator_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                (int(time.time()),),
            )
        return int(cursor.rowcount)


def parse_cookie(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value.split(";"):
        key, separator, cookie_value = item.strip().partition("=")
        if separator and key:
            result[key] = cookie_value
    return result


def public_session(session: Session) -> dict[str, Any]:
    return {
        "authenticated": True,
        "identity": session.identity,
        "expiresAt": session.expires_at,
        "stepUpValid": session.step_up_valid,
    }
