from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


SESSION_IDLE_TTL_SECONDS = 30 * 60
SESSION_ABSOLUTE_TTL_SECONDS = 8 * 60 * 60
STEP_UP_TTL_SECONDS = 5 * 60
SESSION_RETENTION_SECONDS = 30 * 24 * 60 * 60
SCHEMA_VERSION = 1


def _format_timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str | None) -> int:
    if not value:
        return 0
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


@dataclass(frozen=True)
class Session:
    session_id: str
    identity: str
    csrf_token: str
    created_at: int
    expires_at: int
    step_up_at: int
    role: str = "owner"
    last_seen_at: int = 0
    absolute_expires_at: int = 0

    @property
    def step_up_valid(self) -> bool:
        age = int(time.time()) - self.step_up_at
        return self.step_up_at > 0 and 0 <= age <= STEP_UP_TTL_SECONDS


class SessionStore:
    def __init__(
        self,
        path: Path,
        *,
        ttl_seconds: int = SESSION_IDLE_TTL_SECONDS,
        absolute_ttl_seconds: int = SESSION_ABSOLUTE_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.absolute_ttl_seconds = absolute_ttl_seconds
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _backup_before_migration(self, source: sqlite3.Connection, version: int) -> None:
        tables = source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if not tables:
            return
        backup_path = self.path.with_name(f"{self.path.name}.pre-v{version + 1}.bak")
        if backup_path.exists():
            return
        descriptor, temporary = tempfile.mkstemp(prefix=f".{backup_path.name}.", dir=backup_path.parent)
        os.close(descriptor)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
            destination.close()
            os.chmod(temporary, 0o600)
            os.replace(temporary, backup_path)
        finally:
            try:
                destination.close()
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _initialize(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"session database schema {version} is newer than supported {SCHEMA_VERSION}")
            if version < SCHEMA_VERSION:
                self._backup_before_migration(connection, version)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            session_hash TEXT PRIMARY KEY,
                            csrf_hash TEXT NOT NULL,
                            tailnet_login TEXT NOT NULL,
                            role TEXT NOT NULL CHECK (role = 'owner'),
                            created_at TEXT NOT NULL,
                            last_seen_at TEXT NOT NULL,
                            expires_at TEXT NOT NULL,
                            absolute_expires_at TEXT NOT NULL,
                            step_up_at TEXT,
                            revoked_at TEXT
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS sessions_login_active
                          ON sessions(tailnet_login, revoked_at, expires_at)
                        """
                    )
                    connection.execute("DROP TABLE IF EXISTS operator_sessions")
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        os.chmod(self.path, 0o600)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _now(self) -> int:
        return int(self.clock())

    def create(self, identity: str, *, role: str = "owner", stepped_up: bool = True) -> Session:
        if not identity or role != "owner":
            raise ValueError("enabled owner identity is required")
        current = self._now()
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = min(current + self.ttl_seconds, current + self.absolute_ttl_seconds)
        session = Session(
            session_id=session_id,
            identity=identity,
            csrf_token=csrf_token,
            created_at=current,
            last_seen_at=current,
            expires_at=expires_at,
            absolute_expires_at=current + self.absolute_ttl_seconds,
            step_up_at=current if stepped_up else 0,
            role=role,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE sessions
                SET revoked_at = ?
                WHERE tailnet_login = ? AND revoked_at IS NULL
                """,
                (_format_timestamp(current), identity),
            )
            connection.execute(
                """
                INSERT INTO sessions (
                    session_hash, csrf_hash, tailnet_login, role, created_at,
                    last_seen_at, expires_at, absolute_expires_at, step_up_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    self._hash(session_id),
                    self._hash(csrf_token),
                    identity,
                    role,
                    _format_timestamp(session.created_at),
                    _format_timestamp(session.last_seen_at),
                    _format_timestamp(session.expires_at),
                    _format_timestamp(session.absolute_expires_at),
                    _format_timestamp(session.step_up_at) if session.step_up_at else None,
                ),
            )
            connection.commit()
        return session

    def get(self, session_id: str, identity: str, *, role: str = "owner") -> Session | None:
        if not session_id or not identity or role != "owner":
            return None
        current = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT tailnet_login, role, created_at, last_seen_at, expires_at,
                       absolute_expires_at, step_up_at
                FROM sessions
                WHERE session_hash = ? AND tailnet_login = ? AND role = ?
                  AND revoked_at IS NULL
                """,
                (self._hash(session_id), identity, role),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            expires_at = _parse_timestamp(str(row["expires_at"]))
            absolute_expires_at = _parse_timestamp(str(row["absolute_expires_at"]))
            if expires_at <= current or absolute_expires_at <= current:
                connection.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE session_hash = ?",
                    (_format_timestamp(current), self._hash(session_id)),
                )
                connection.commit()
                return None
            refreshed_expiry = min(current + self.ttl_seconds, absolute_expires_at)
            connection.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?, expires_at = ?
                WHERE session_hash = ? AND revoked_at IS NULL
                """,
                (
                    _format_timestamp(current),
                    _format_timestamp(refreshed_expiry),
                    self._hash(session_id),
                ),
            )
            connection.commit()
        return Session(
            session_id=session_id,
            identity=str(row["tailnet_login"]),
            role=str(row["role"]),
            csrf_token="",
            created_at=_parse_timestamp(str(row["created_at"])),
            last_seen_at=current,
            expires_at=refreshed_expiry,
            absolute_expires_at=absolute_expires_at,
            step_up_at=_parse_timestamp(row["step_up_at"]),
        )

    def csrf_valid(self, session_id: str, csrf_token: str) -> bool:
        if not session_id or not csrf_token:
            return False
        current = _format_timestamp(self._now())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT csrf_hash FROM sessions
                WHERE session_hash = ? AND revoked_at IS NULL
                  AND expires_at > ? AND absolute_expires_at > ?
                """,
                (
                    self._hash(session_id),
                    current,
                    current,
                ),
            ).fetchone()
        return row is not None and secrets.compare_digest(str(row["csrf_hash"]), self._hash(csrf_token))

    def rotate_csrf(self, session_id: str) -> str:
        csrf_token = secrets.token_urlsafe(32)
        current = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions SET csrf_hash = ?
                WHERE session_hash = ? AND revoked_at IS NULL
                  AND expires_at > ? AND absolute_expires_at > ?
                """,
                (
                    self._hash(csrf_token),
                    self._hash(session_id),
                    _format_timestamp(current),
                    _format_timestamp(current),
                ),
            )
        return csrf_token if cursor.rowcount == 1 else ""

    def revoke(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_hash = ? AND revoked_at IS NULL",
                (_format_timestamp(self._now()), self._hash(session_id)),
            )

    def revoke_identity(self, identity: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions SET revoked_at = ?
                WHERE tailnet_login = ? AND revoked_at IS NULL
                """,
                (_format_timestamp(self._now()), identity),
            )
        return int(cursor.rowcount)

    def step_up(self, session_id: str) -> bool:
        current = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions SET step_up_at = ?
                WHERE session_hash = ? AND revoked_at IS NULL
                  AND expires_at > ? AND absolute_expires_at > ?
                """,
                (
                    _format_timestamp(current),
                    self._hash(session_id),
                    _format_timestamp(current),
                    _format_timestamp(current),
                ),
            )
        return cursor.rowcount == 1

    def purge(self) -> int:
        cutoff = _format_timestamp(self._now() - SESSION_RETENTION_SECONDS)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM sessions
                WHERE (revoked_at IS NOT NULL AND revoked_at <= ?)
                   OR absolute_expires_at <= ?
                """,
                (cutoff, cutoff),
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
        "role": session.role,
        "expiresAt": session.expires_at,
        "absoluteExpiresAt": session.absolute_expires_at,
        "stepUpValid": session.step_up_valid,
    }
