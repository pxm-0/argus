from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_sessions import (  # noqa: E402
    SESSION_RESTORATION_FAILURES,
    Session,
    SessionRestoration,
    SessionStore,
    parse_cookie,
)


class SessionStoreTests(unittest.TestCase):
    def test_session_requires_matching_identity_and_csrf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            session = store.create("operator@example.com")
            self.assertIsNotNone(store.get(session.session_id, "operator@example.com"))
            self.assertIsNone(store.get(session.session_id, "attacker@example.com"))
            self.assertTrue(store.csrf_valid(session.session_id, session.csrf_token))
            self.assertFalse(store.csrf_valid(session.session_id, "wrong"))
            rotated = store.rotate_csrf(session.session_id)
            self.assertTrue(store.csrf_valid(session.session_id, rotated))
            self.assertFalse(store.csrf_valid(session.session_id, session.csrf_token))
            self.assertTrue(session.step_up_valid)
            with sqlite3.connect(Path(directory) / "sessions.sqlite3") as connection:
                stored = connection.execute(
                    "SELECT session_hash, csrf_hash, tailnet_login, role FROM sessions"
                ).fetchone()
                self.assertEqual(3, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertNotIn(session.session_id, stored)
            self.assertNotIn(session.csrf_token, stored)
            self.assertEqual(("operator@example.com", "owner"), stored[2:])

    def test_operation_binding_is_hashed_and_requires_the_originating_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            store = SessionStore(database)
            first = store.create("operator@example.com")
            self.assertTrue(
                store.reserve_operation("idempotency-1", first.session_id)
            )
            self.assertTrue(store.bind_operation("operation-1", first.session_id))
            self.assertTrue(
                store.operation_bound_to(
                    "operation-1",
                    first.session_id,
                    idempotency_key="idempotency-1",
                )
            )
            replacement = store.create("operator@example.com")
            self.assertFalse(
                store.reserve_operation("idempotency-1", replacement.session_id)
            )
            self.assertFalse(
                store.operation_bound_to("operation-1", replacement.session_id)
            )
            self.assertFalse(
                store.bind_operation("operation-1", replacement.session_id)
            )
            with sqlite3.connect(database) as connection:
                stored_hash = connection.execute(
                    """
                    SELECT session_hash FROM operation_session_bindings
                    WHERE operation_id = 'operation-1'
                    """
                ).fetchone()[0]
            self.assertNotEqual(first.session_id, stored_hash)
            self.assertNotIn(first.session_id, database.read_bytes().decode(errors="ignore"))

    def test_operation_reservation_closes_the_pre_binding_crash_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            session = store.create("operator@example.com")
            self.assertTrue(
                store.reserve_operation("crash-window", session.session_id)
            )
            self.assertTrue(
                store.operation_bound_to(
                    "operation-created-before-api-crash",
                    session.session_id,
                    idempotency_key="crash-window",
                )
            )
            replacement = store.create(session.identity)
            self.assertFalse(
                store.operation_bound_to(
                    "operation-created-before-api-crash",
                    replacement.session_id,
                    idempotency_key="crash-window",
                )
            )

    def test_expiry_logout_revocation_and_step_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expired_store = SessionStore(Path(directory) / "expired.sqlite3", ttl_seconds=-1)
            expired = expired_store.create("operator@example.com")
            self.assertIsNone(expired_store.get(expired.session_id, expired.identity))

            store = SessionStore(Path(directory) / "active.sqlite3")
            first = store.create("operator@example.com", stepped_up=False)
            self.assertFalse(first.step_up_valid)
            store.step_up(first.session_id)
            self.assertTrue(store.get(first.session_id, first.identity).step_up_valid)
            store.revoke(first.session_id)
            self.assertIsNone(store.get(first.session_id, first.identity))

            second = store.create("operator@example.com")
            self.assertEqual(store.revoke_identity(second.identity), 1)
            self.assertIsNone(store.get(second.session_id, second.identity))

    def test_restoration_returns_safe_reasons_without_destructive_reads(self) -> None:
        current = [1_000_000]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            store = SessionStore(database, ttl_seconds=10, clock=lambda: current[0])
            self.assertEqual("cookie-missing", store.restore("", "operator@example.com").reason)
            self.assertEqual("session-not-found", store.restore("absent", "operator@example.com").reason)

            expired = store.create("operator@example.com")
            current[0] += 11
            self.assertEqual("session-expired", store.restore(expired.session_id, expired.identity).reason)
            with sqlite3.connect(database) as connection:
                self.assertIsNone(
                    connection.execute(
                        "SELECT revoked_at FROM sessions WHERE session_hash = ?",
                        (store._hash(expired.session_id),),
                    ).fetchone()[0]
                )

            active = store.create("operator@example.com")
            store.revoke(active.session_id)
            self.assertEqual("session-revoked", store.restore(active.session_id, active.identity).reason)
            with patch.object(store, "_connect", side_effect=sqlite3.OperationalError("unavailable")):
                self.assertEqual(
                    "session-store-unavailable",
                    store.restore(active.session_id, active.identity).reason,
                )

    def test_restoration_reason_contract_is_closed(self) -> None:
        self.assertEqual(
            {
                "identity-missing",
                "operator-disabled",
                "cookie-missing",
                "session-not-found",
                "session-expired",
                "session-revoked",
                "session-store-unavailable",
            },
            SESSION_RESTORATION_FAILURES,
        )
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            SessionRestoration(None, "raw-diagnostic-detail")

    def test_repeated_restoration_changes_only_last_seen_and_idle_expiry(self) -> None:
        current = [1_000_000]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            store = SessionStore(database, ttl_seconds=100, clock=lambda: current[0])
            session = store.create("operator@example.com")
            with sqlite3.connect(database) as connection:
                before = connection.execute("SELECT * FROM sessions").fetchone()
                columns = [item[0] for item in connection.execute("SELECT * FROM sessions").description]
            current[0] += 10
            self.assertIsNotNone(store.restore(session.session_id, session.identity).session)
            current[0] += 10
            self.assertIsNotNone(store.restore(session.session_id, session.identity).session)
            with sqlite3.connect(database) as connection:
                after = connection.execute("SELECT * FROM sessions").fetchone()
            changed = {
                name
                for name, old, new in zip(columns, before, after, strict=True)
                if old != new
            }
            self.assertEqual({"last_seen_at", "expires_at"}, changed)

    def test_create_rotates_existing_identity_and_absolute_expiry_does_not_slide(self) -> None:
        current = [1_000_000]
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(
                Path(directory) / "sessions.sqlite3",
                ttl_seconds=100,
                absolute_ttl_seconds=250,
                clock=lambda: current[0],
            )
            first = store.create("operator@example.com")
            second = store.create("operator@example.com")
            self.assertIsNone(store.get(first.session_id, first.identity))
            self.assertIsNotNone(store.get(second.session_id, second.identity))

            current[0] += 90
            refreshed = store.get(second.session_id, second.identity)
            self.assertEqual(1_000_250, refreshed.absolute_expires_at)
            self.assertEqual(1_000_190, refreshed.expires_at)

            current[0] = 1_000_251
            self.assertIsNone(store.get(second.session_id, second.identity))

    def test_schema_upgrade_is_backed_up_and_newer_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE legacy(value TEXT)")
                connection.execute("INSERT INTO legacy VALUES ('preserved')")
                connection.execute("CREATE TABLE operator_sessions(session_hash TEXT)")
                connection.execute("INSERT INTO operator_sessions VALUES ('retired-session')")
            SessionStore(database)
            backup = database.with_name("sessions.sqlite3.pre-v1.bak")
            self.assertTrue(backup.exists())
            with sqlite3.connect(backup) as connection:
                self.assertEqual("preserved", connection.execute("SELECT value FROM legacy").fetchone()[0])
                self.assertEqual(
                    "retired-session",
                    connection.execute("SELECT session_hash FROM operator_sessions").fetchone()[0],
                )
            with sqlite3.connect(database) as connection:
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='operator_sessions'"
                    ).fetchone()
                )

            with sqlite3.connect(database) as connection:
                connection.execute("PRAGMA user_version=4")
            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                SessionStore(database)

    def test_declared_current_session_schema_must_be_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE sessions (session_hash TEXT PRIMARY KEY)"
                )
                connection.execute("PRAGMA user_version=3")
            with self.assertRaisesRegex(
                RuntimeError,
                "missing sessions columns",
            ):
                SessionStore(database)

    def test_cookie_parser_extracts_only_named_values(self) -> None:
        self.assertEqual(
            parse_cookie("theme=dark; argus_session=opaque; malformed"),
            {"theme": "dark", "argus_session": "opaque"},
        )

    def test_future_step_up_timestamp_is_not_valid(self) -> None:
        session = Session(
            "session",
            "operator@example.com",
            "csrf",
            0,
            2**31,
            2**31,
        )
        self.assertFalse(session.step_up_valid)


if __name__ == "__main__":
    unittest.main()
