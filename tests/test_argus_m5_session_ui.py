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

    def test_authenticator_code_input_is_one_time_code_and_cleared_after_use(self) -> None:
        self.assertRegex(self.html, r'<input id="admin-totp"[^>]*autocomplete="one-time-code"[^>]*aria-label="Authenticator code"')
        self.assertIn("function clearCredentialInputs()", self.javascript)
        # exchange, failed step-up, finished or cancelled step-up, logout
        self.assertEqual(4, self.javascript.count("clearCredentialInputs();"))
        for endpoint in ('"/api/session/step-up", credentialBody(credential)', "credentialBody(credential),\n      { \"X-Argus-CSRF-Bootstrap\""):
            self.assertIn(endpoint, self.javascript)

    def test_sign_in_is_a_password_manager_form(self) -> None:
        # A real form with username/current-password/one-time-code lets Passwords save the token and offer the code.
        form = re.search(r'<form id="signin-form"[^>]*hidden>(.*?)</form>', self.html, re.S)
        self.assertIsNotNone(form)
        body = form.group(1)
        self.assertRegex(body, r'<input id="signin-user"[^>]*autocomplete="username"')
        self.assertRegex(body, r'<input id="admin-token"[^>]*type="password"[^>]*autocomplete="current-password"')
        self.assertRegex(body, r'<input id="admin-totp"[^>]*autocomplete="one-time-code"')
        self.assertRegex(body, r'<button id="signin-submit"[^>]*type="submit"')
        self.assertNotIn('autocomplete="off"', body)
        self.assertIn('signinForm.addEventListener("submit"', self.javascript)
        self.assertIn("event.preventDefault();", self.javascript)
        # The login field only feeds the password manager; the API keeps using the tailnet identity.
        self.assertNotIn("signin-user", self.javascript)

    def test_step_up_opens_the_form_and_continues_the_change(self) -> None:
        self.assertIn("return requestStepUp();", self.javascript)
        self.assertIn("if (pendingStepUp) {\n      await submitStepUp();", self.javascript)
        self.assertIn('signinCancel.addEventListener("click", () => finishStepUp(false));', self.javascript)
        self.assertNotIn("then retry the mutation", self.javascript)

    def test_pending_step_up_is_settled_when_the_session_ends(self) -> None:
        # Review finding: logout or expiry left the form in Confirm mode and sent the next sign-in to step-up.
        self.assertIn('if (pendingStepUp && operatorSessionState !== "checking") finishStepUp(false);', self.javascript)
        self.assertLess(self.javascript.index("let pendingStepUp = null;"), self.javascript.index("function setOperatorSessionState"))
        self.assertIn("Your session ended, so the change was not made. Sign in again.", self.javascript)

    def test_credentials_are_cleared_even_when_the_request_throws(self) -> None:
        self.assertEqual(2, self.javascript.count("  } finally {\n    clearCredentialInputs();\n  }"))

    def test_sign_in_cannot_double_submit_or_submit_natively_with_get(self) -> None:
        self.assertIn("if (signinSubmit.disabled) return;", self.javascript)
        self.assertIn("if (!signinSubmit.disabled) signinForm.requestSubmit();", self.javascript)
        self.assertRegex(self.html, r'<form id="signin-form"[^>]*method="post"')

    def test_sign_in_failures_explain_fresh_codes_and_lockout(self) -> None:
        self.assertIn('response.headers.get("Retry-After")', self.javascript)
        self.assertIn("each code works once", self.javascript)
        self.assertIn("Too many attempts. Try again in", self.javascript)


if __name__ == "__main__":
    unittest.main()
