from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_sessions import SessionStore, parse_cookie  # noqa: E402


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

    def test_cookie_parser_extracts_only_named_values(self) -> None:
        self.assertEqual(
            parse_cookie("theme=dark; argus_session=opaque; malformed"),
            {"theme": "dark", "argus_session": "opaque"},
        )


if __name__ == "__main__":
    unittest.main()
