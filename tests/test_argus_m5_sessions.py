from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_sessions import Session, SessionStore, parse_cookie  # noqa: E402


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
                self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertNotIn(session.session_id, stored)
            self.assertNotIn(session.csrf_token, stored)
            self.assertEqual(("operator@example.com", "owner"), stored[2:])

    def test_operation_binding_is_hashed_and_requires_the_originating_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            store = SessionStore(database)
            first = store.create("operator@example.com")
            self.assertTrue(store.bind_operation("operation-1", first.session_id))
            self.assertTrue(
                store.operation_bound_to("operation-1", first.session_id)
            )
            replacement = store.create("operator@example.com")
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
                connection.execute("PRAGMA user_version=3")
            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                SessionStore(database)

    def test_declared_current_session_schema_must_be_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE sessions (session_hash TEXT PRIMARY KEY)"
                )
                connection.execute("PRAGMA user_version=2")
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
