from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_sessions import SESSION_RESTORATION_FAILURES  # noqa: E402


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "argus_m5_session_ui_generator",
        ROOT / "control-plane" / "dashboard" / "generate_dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OperatorSessionUiTests(unittest.TestCase):
    def setUp(self) -> None:
        generator = load_generator()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        public = Path(self.temporary.name)
        with patch.object(generator, "PUBLIC", public):
            self.assertEqual(0, generator.main())
        self.html = (public / "index.html").read_text()
        self.css = (public / "style.css").read_text()
        self.javascript = (public / "app.js").read_text()

    def test_startup_exposes_one_accessible_five_state_session_control(self) -> None:
        self.assertIn('id="session-control" data-state="checking"', self.html)
        self.assertIn('role="status" aria-live="polite" aria-atomic="true"', self.html)
        self.assertIn('id="admin-toggle" type="button" disabled', self.html)
        for state in (
            "checking",
            "authenticated",
            "unauthenticated",
            "expired",
            "unavailable",
        ):
            self.assertIn(f'"{state}"', self.javascript)
        restore = self.javascript[self.javascript.index("async function restoreOperatorSession()") :]
        self.assertLess(
            restore.index('setOperatorSessionState("checking")'),
            restore.index('fetch("/api/session"'),
        )

    def test_api_reason_contract_is_exhaustively_mapped(self) -> None:
        match = re.search(
            r"const SESSION_REASON_STATES = Object\.freeze\((\{.*?\})\);",
            self.javascript,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        reason_states = json.loads(match.group(1))
        self.assertEqual(set(SESSION_RESTORATION_FAILURES), set(reason_states))
        self.assertEqual("expired", reason_states["session-expired"])
        self.assertEqual("expired", reason_states["session-revoked"])
        self.assertEqual("unavailable", reason_states["session-store-unavailable"])

    def test_unavailable_and_missing_csrf_are_not_presented_as_logout(self) -> None:
        for marker in (
            "It was not treated as a logout.",
            'reason: "csrf-missing"',
            "Mutation protection missing",
            "Sign in again before making changes.",
            'operatorSessionReason !== "csrf-missing"',
            'if (!cookieCsrf && endpoint !== "/api/session/exchange")',
            "Authentication completed without mutation protection. Sign in again.",
        ):
            self.assertIn(marker, self.javascript)
        self.assertIn('credentials: "same-origin"', self.javascript)
        self.assertIn('cache: "no-store"', self.javascript)

    def test_session_secrets_are_cookie_only_and_controls_have_state_signals(self) -> None:
        non_theme_storage = self.javascript.replace(
            'localStorage.setItem("argus-theme", theme);',
            "",
        ).replace(
            'localStorage.getItem("argus-theme")',
            "",
        )
        self.assertNotIn("localStorage", non_theme_storage)
        self.assertNotIn("sessionStorage", self.javascript)
        self.assertNotIn("headers.Authorization", self.javascript)
        for state in ("authenticated", "expired", "unavailable"):
            self.assertIn(f'.session-control[data-state="{state}"]', self.css)
        self.assertIn(".session-control{grid-column:1/-1", self.css)
        self.assertIn(".session-control button{min-height:44px}", self.css)


if __name__ == "__main__":
    unittest.main()
