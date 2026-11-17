from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_cli_op  # noqa: E402
import argus_totp  # noqa: E402
from argus_api_client import ApiClient, ApiUnavailable, normalize_base_url  # noqa: E402
from argus_cli import run  # noqa: E402

TOKEN = "BOOTSTRAP-TOKEN-DO-NOT-LEAK-0123456789"
DIGEST = "ab" * 32
PHRASE = "deploy demo sha256:feed"
OP_ID = str(uuid.uuid4())
SECRET = "JBSWY3DPEHPK3PXP"


class FakeApi(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FakeHandler)
        self.origin = f"http://127.0.0.1:{self.server_address[1]}"
        self.log: list[str] = []
        self.requests: list[tuple[str, str, str]] = []  # method, path, header dump
        self.stepped = False
        self.expire_step_up_once = False
        self.allowed = True
        self.states = ["queued", "running", "succeeded"]
        self.poll = 0
        self.codes: list[str] = []  # totp sent with each exchange/step-up


class FakeHandler(BaseHTTPRequestHandler):
    server: FakeApi

    def log_message(self, *args: object) -> None:
        return

    def reply(self, status: int, body: dict, cookies: tuple[str, ...] = ()) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length)) if length else {}

    def authed(self, csrf: bool) -> bool:
        cookies = dict(part.strip().split("=", 1) for part in self.headers.get("Cookie", "").split(";") if "=" in part)
        if cookies.get("argus_session") != "SESSION":
            self.reply(401, {"error": "session required"})
            return False
        if csrf and (not self.headers.get("X-Argus-CSRF") or self.headers.get("X-Argus-CSRF") != cookies.get("argus_csrf")):
            self.reply(403, {"error": "CSRF validation failed"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        self.server.requests.append(("GET", self.path, str(self.headers)))
        if not self.authed(False):
            return
        states = self.server.states
        state = states[min(self.server.poll, len(states) - 1)]
        self.server.poll += 1
        self.reply(200, {"operation_id": OP_ID, "state": state, "workload_id": "demo", "operation_type": "workload.deploy", "redacted_summary": "fake summary", "preview_digest": DIGEST, "expected_revision": "r1", "parameters": {"targetRevision": "sha256:feed"}, "preview": {"confirmationPhrase": PHRASE, "expectedBlastRadius": "brief"}})

    def do_POST(self) -> None:  # noqa: N802
        self.server.requests.append(("POST", self.path, str(self.headers)))
        body = self.body()
        if self.headers.get("Origin") != self.server.origin:
            self.reply(403, {"error": "trusted operator origin required"})
            return
        if self.path in ("/api/session/exchange", "/api/session/step-up"):
            self.server.codes.append(str(body.get("totp", "")))
        if self.path == "/api/session/exchange":
            if body.get("bootstrapToken") != TOKEN or len(self.headers.get("X-Argus-CSRF-Bootstrap", "")) < 32:
                self.reply(401, {"error": "bootstrap credential required"})
                return
            self.reply(201, {"authenticated": True}, ("argus_session=SESSION; Path=/; Secure; HttpOnly", "argus_csrf=CSRFVALUE; Path=/; Secure"))
            return
        if not self.authed(True):
            return
        if self.path == "/api/session/step-up":
            if body.get("bootstrapToken") != TOKEN:
                self.reply(401, {"error": "step-up credential rejected"})
                return
            self.server.stepped = True
            self.reply(200, {"ok": True})
        elif self.path.endswith("/operations/preview"):
            self.reply(200, {"workloadId": "demo", "operationType": body["operationType"], "previewDigest": DIGEST, "expectedRevision": "r1", "policyVersion": "p1", "allowed": self.server.allowed, "reason": "frozen", "expectedBlastRadius": "brief", "rollbackBehavior": "redeploy", "confirmationPhrase": PHRASE})
        elif self.path == "/api/workloads/demo/operations":
            if body.get("previewDigest") != DIGEST or "Idempotency-Key" not in self.headers:
                self.reply(409, {"error": "preview or canonical revision is stale"})
                return
            self.reply(202, {"operation_id": OP_ID, "state": "awaiting-approval"})
        elif self.path == f"/api/operations/{OP_ID}/approve":
            if not self.server.stepped or self.server.expire_step_up_once:
                self.server.stepped = self.server.expire_step_up_once = False
                self.reply(403, {"error": "step-up reauthentication required"})
            elif body.get("confirmation") != PHRASE:
                self.reply(403, {"error": "exact preview confirmation required"})
            else:
                self.reply(202, {"state": "queued"})
        else:
            self.reply(404, {"error": "not found"})


class FakeTty:
    def __init__(self, *, lines: list[str] | None = None) -> None:
        self.secrets_asked: list[str] = []
        self.lines = list(lines or [])
        self.output = ""

    def write(self, text: str) -> None:
        self.output += text

    def read_line(self, prompt: str) -> str:
        self.output += prompt
        return self.lines.pop(0)

    def read_secret(self, prompt: str) -> str:
        if "Authenticator" in prompt:
            return ""
        self.secrets_asked.append(prompt)
        return TOKEN

    def close(self) -> None:
        return


class ApiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeApi()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_exchange_stores_cookies_and_sends_csrf_header(self) -> None:
        client = ApiClient(self.server.origin)
        self.assertEqual(201, client.exchange(TOKEN).status)
        self.assertEqual(200, client.step_up(TOKEN).status)
        self.assertIn("X-Argus-Csrf: CSRFVALUE", self.server.requests[-1][2])

    def test_wrong_token_is_rejected_without_a_session(self) -> None:
        client = ApiClient(self.server.origin)
        self.assertEqual(401, client.exchange("wrong").status)
        self.assertEqual(401, client.operation(OP_ID).status)

    def test_origin_is_enforced_and_csrf_is_required(self) -> None:
        client = ApiClient(self.server.origin)
        client.exchange(TOKEN)
        client._cookies.pop("argus_csrf")
        self.assertEqual(403, client.step_up(TOKEN).status)
        self.assertEqual(403, ApiClient(self.server.origin).request("POST", "/api/session/exchange", {"bootstrapToken": TOKEN}, headers={"Origin": "https://evil.example"}).status)

    def test_unreachable_server_raises_payload_free_error(self) -> None:
        client = ApiClient("http://127.0.0.1:1")
        with self.assertRaises(ApiUnavailable) as raised:
            client.exchange(TOKEN)
        self.assertNotIn(TOKEN, repr(raised.exception) + str(raised.exception))

    def test_base_url_validation(self) -> None:
        self.assertEqual("https://h.ts.net:8448", normalize_base_url("https://h.ts.net:8448/"))
        for bad in ("http://h.ts.net", "https://h.ts.net/x", "ftp://h", "https://u@h", "https://h?q=1", "https://h:99999"):
            with self.subTest(bad), self.assertRaises(ValueError):
                normalize_base_url(bad)


class OpCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeApi()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        for patcher in (
            mock.patch.object(argus_cli_op, "POLL_SECONDS", 0),
            mock.patch.object(argus_cli_op, "keychain_totp_secret", return_value=""),  # never the developer's real Keychain
            mock.patch.object(argus_cli_op, "COUNTER_FILE", Path(self.enterContext(tempfile.TemporaryDirectory())) / "argus" / "totp-last-counter"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self, argv: list[str], tty: FakeTty | None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(argus_cli_op, "open_tty", return_value=tty):
            code = run([*argv, "--base-url", self.server.origin, "--json"], repo=ROOT, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.server.requests if not path.startswith("/api/operations/") or path.endswith("/approve")]

    def test_preview_prints_digest_and_asks_for_the_token_once(self) -> None:
        tty = FakeTty()
        code, out, _ = self.invoke(["op", "preview", "demo", "deploy", "--revision", "sha256:feed"], tty)
        self.assertEqual(0, code, out)
        self.assertEqual(DIGEST, json.loads(out)["data"]["previewDigest"])
        self.assertEqual(1, len(tty.secrets_asked))
        self.assertNotIn("/step-up", " ".join(self.paths()))

    def test_create_runs_the_full_flow_after_typed_confirmation(self) -> None:
        tty = FakeTty(lines=["demo"])
        code, out, _ = self.invoke(["workload", "deploy", "demo", "--revision", "sha256:feed"], tty)
        self.assertEqual(0, code, out)
        self.assertEqual("succeeded", json.loads(out)["data"]["state"])
        self.assertEqual(
            ["/api/session/exchange", "/api/workloads/demo/operations/preview", "/api/session/step-up", "/api/workloads/demo/operations", f"/api/operations/{OP_ID}/approve"],
            self.paths(),
        )
        self.assertEqual(2, len(tty.secrets_asked))

    def test_wrong_typed_confirmation_creates_nothing(self) -> None:
        code, out, _ = self.invoke(["op", "create", "demo", "workload.deploy"], FakeTty(lines=["nope"]))
        self.assertEqual(3, code)
        self.assertEqual("op-confirmation-mismatch", json.loads(out)["error"]["code"])
        self.assertNotIn("/api/workloads/demo/operations", self.paths())

    def test_yes_digest_must_match_the_previewed_digest(self) -> None:
        code, out, _ = self.invoke(["op", "create", "demo", "deploy", "--yes-digest", "sha256:" + "00" * 32], FakeTty())
        self.assertEqual(3, code)
        self.assertEqual("op-digest-mismatch", json.loads(out)["error"]["code"])
        self.assertNotIn("/api/workloads/demo/operations", self.paths())
        code, out, _ = self.invoke(["op", "create", "demo", "deploy", "--yes-digest", "sha256:" + DIGEST], FakeTty())
        self.assertEqual(0, code, out)

    def test_no_terminal_exits_2_before_any_request(self) -> None:
        code, out, _ = self.invoke(["op", "preview", "demo", "deploy"], None)
        self.assertEqual(2, code)
        self.assertEqual("op-tty-required", json.loads(out)["error"]["code"])
        self.assertEqual([], self.server.requests)

    def test_policy_denial_is_a_refusal(self) -> None:
        self.server.allowed = False
        code, out, _ = self.invoke(["op", "preview", "demo", "deploy"], FakeTty())
        self.assertEqual(3, code)
        self.assertEqual("op-policy-denied", json.loads(out)["error"]["code"])

    def test_terminal_states_map_to_exit_classes(self) -> None:
        for state, expected in {"succeeded": 0, "denied": 3, "expired": 3, "failed": 4, "rolled-back": 4, "indeterminate": 5}.items():
            with self.subTest(state):
                self.server.poll = 0
                self.server.states = ["running", state]
                code, out, _ = self.invoke(["op", "create", "demo", "deploy", "--yes-digest", DIGEST], FakeTty())
                self.assertEqual(expected, code, out)

    def test_unobservable_operation_is_indeterminate(self) -> None:
        self.server.states = ["running"]
        code, out, _ = self.invoke(["op", "watch", OP_ID, "--timeout", "0"], FakeTty())
        self.assertEqual(5, code)
        self.assertEqual("op-watch-lost", json.loads(out)["error"]["code"])

    def test_expired_step_up_reprompts_once_before_approve(self) -> None:
        self.server.expire_step_up_once = True
        tty = FakeTty()
        code, out, _ = self.invoke(["op", "create", "demo", "deploy", "--yes-digest", DIGEST], tty)
        self.assertEqual(0, code, out)
        self.assertEqual(3, len(tty.secrets_asked))

    def test_rejected_step_up_is_a_refusal_and_creates_nothing(self) -> None:
        with mock.patch.object(FakeTty, "read_secret", side_effect=[TOKEN, "", "wrong", ""]):
            code, out, _ = self.invoke(["op", "create", "demo", "deploy", "--yes-digest", DIGEST], FakeTty())
        self.assertEqual(3, code)
        self.assertEqual("op-step-up-rejected", json.loads(out)["error"]["code"])
        self.assertNotIn("/api/workloads/demo/operations", self.paths())

    def test_show(self) -> None:
        code, out, _ = self.invoke(["op", "show", OP_ID], FakeTty())
        self.assertEqual(0, code, out)
        self.assertEqual("op.show", json.loads(out)["data"]["command"])

    def test_invalid_arguments_and_base_url_exit_2(self) -> None:
        self.assertEqual(2, self.invoke(["op", "show", "not-a-uuid"], FakeTty())[0])
        self.assertEqual(2, self.invoke(["op", "preview", "demo", "Bad Type"], FakeTty())[0])
        stdout = io.StringIO()
        with mock.patch.object(argus_cli_op, "open_tty", return_value=FakeTty()):
            code = run(["op", "show", OP_ID, "--base-url", "http://example.com", "--json"], repo=ROOT, stdout=stdout, stderr=io.StringIO())
        self.assertEqual(2, code)

    def test_foreign_https_base_url_refused_before_any_prompt(self) -> None:
        for bad in ("https://evil.example", "https://evil.example:8448", "https://h.ts.net.evil.example"):
            tty = FakeTty()
            stdout = io.StringIO()
            with mock.patch.object(argus_cli_op, "open_tty", return_value=tty):
                code = run(["op", "show", OP_ID, "--base-url", bad, "--json"], repo=ROOT, stdout=stdout, stderr=io.StringIO())
            self.assertEqual(2, code, bad)
            self.assertEqual([], tty.secrets_asked, bad)

    def test_approve_and_cancel_verbs_do_not_exist(self) -> None:
        for verb in ("approve", "cancel"):
            code = run(["op", verb, OP_ID], repo=ROOT, stdout=io.StringIO(), stderr=io.StringIO())
            self.assertEqual(2, code, verb)

    def test_token_never_reaches_output_headers_or_paths(self) -> None:
        captured = ""
        for argv, tty in (
            (["op", "create", "demo", "deploy", "--yes-digest", DIGEST], FakeTty()),
            (["op", "preview", "demo", "deploy"], FakeTty()),
        ):
            captured += "".join(map(str, self.invoke(argv, tty))) + tty.output
        with mock.patch.object(FakeTty, "read_secret", side_effect=lambda prompt: "" if "Authenticator" in prompt else TOKEN + "x"):
            captured += "".join(map(str, self.invoke(["op", "show", OP_ID], FakeTty())))
        dead = ApiClient("http://127.0.0.1:1")
        try:
            dead.exchange(TOKEN)
        except ApiUnavailable as exc:
            captured += repr(exc) + str(exc)
        captured += "".join(path + headers for _, path, headers in self.server.requests)
        self.assertNotIn(TOKEN, captured)


class FakeClock:
    """Stands in for argus_cli_op's time module: sleep advances the wall clock."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class KeychainCodeTests(unittest.TestCase):
    """The authenticator code comes from the Keychain secret; only the bootstrap token is typed."""

    setUp = OpCommandTests.setUp
    invoke = OpCommandTests.invoke

    def invoke_with(self, secret: str, argv: list[str], tty: FakeTty, clock: FakeClock) -> tuple[int, str, str]:
        with mock.patch.object(argus_cli_op, "keychain_totp_secret", return_value=secret), mock.patch.object(argus_cli_op, "time", clock):
            return self.invoke(argv, tty)

    def test_create_sends_keychain_codes_and_never_prompts_for_one(self) -> None:
        clock = FakeClock(1_800_000_010.0)
        tty = FakeTty()
        with mock.patch.object(FakeTty, "read_secret", autospec=True, side_effect=lambda self, prompt: self.secrets_asked.append(prompt) or TOKEN):
            code, out, _ = self.invoke_with(SECRET, ["op", "create", "demo", "deploy", "--yes-digest", DIGEST], tty, clock)
        self.assertEqual(0, code, out)
        self.assertFalse([p for p in tty.secrets_asked if "Authenticator" in p], tty.secrets_asked)
        first = argus_totp.counter_at(1_800_000_010.0)
        # Step-up in the same window waits for the next code instead of reusing the spent one.
        self.assertEqual([argus_totp.hotp(SECRET, first), argus_totp.hotp(SECRET, first + 1)], self.server.codes)
        self.assertEqual([20.5], [s for s in clock.slept if s])  # 10 s into the window: wait out the other 20 s
        self.assertIn("Waiting", tty.output)

    def test_next_run_in_the_same_window_waits_instead_of_resending_a_spent_code(self) -> None:
        clock = FakeClock(1_800_000_010.0)
        first = argus_totp.counter_at(clock.now)
        self.assertEqual(0, self.invoke_with(SECRET, ["op", "show", OP_ID], FakeTty(), clock)[0])
        self.assertEqual(str(first), argus_cli_op.COUNTER_FILE.read_text().strip())
        tty = FakeTty()
        self.assertEqual(0, self.invoke_with(SECRET, ["op", "show", OP_ID], tty, clock)[0])
        self.assertEqual([argus_totp.hotp(SECRET, first), argus_totp.hotp(SECRET, first + 1)], self.server.codes)
        self.assertIn("Waiting", tty.output)

    def test_recorded_counter_far_ahead_of_the_clock_is_ignored(self) -> None:
        clock = FakeClock(1_800_000_010.0)
        now = argus_totp.counter_at(clock.now)
        argus_cli_op.COUNTER_FILE.parent.mkdir(parents=True)
        argus_cli_op.COUNTER_FILE.write_text(f"{now + 1000}\n")
        self.assertEqual(0, self.invoke_with(SECRET, ["op", "show", OP_ID], FakeTty(), clock)[0])
        self.assertEqual([argus_totp.hotp(SECRET, now)], self.server.codes)
        self.assertEqual([], [s for s in clock.slept if s])

    def test_missing_keychain_item_falls_back_to_the_prompt(self) -> None:
        tty = FakeTty()
        with mock.patch.object(FakeTty, "read_secret", autospec=True, side_effect=lambda self, prompt: self.secrets_asked.append(prompt) or ("" if "Authenticator" in prompt else TOKEN)):
            code, out, _ = self.invoke_with("", ["op", "show", OP_ID], tty, FakeClock(1_800_000_010.0))
        self.assertEqual(0, code, out)
        self.assertTrue([p for p in tty.secrets_asked if "Authenticator" in p])

    def test_invalid_keychain_secret_stops_before_any_request(self) -> None:
        code, out, _ = self.invoke_with("not base32!", ["op", "show", OP_ID], FakeTty(), FakeClock(1_800_000_010.0))
        self.assertEqual(2, code, out)
        self.assertEqual("op-exchange-keychain-invalid", json.loads(out)["error"]["code"])
        self.assertEqual([], self.server.requests)


class KeychainLookupTests(unittest.TestCase):
    def run_security(self, returncode: int, stdout: str = "") -> tuple[str, str]:
        stderr = io.StringIO()
        result = mock.Mock(returncode=returncode, stdout=stdout)
        with mock.patch.object(argus_cli_op.sys, "platform", "darwin"), mock.patch.object(argus_cli_op.subprocess, "run", return_value=result) as run_mock, mock.patch.object(argus_cli_op.sys, "stderr", stderr):
            secret = argus_cli_op.keychain_totp_secret()
        self.assertEqual(["/usr/bin/security", "find-generic-password", "-s", "argus-totp", "-w"], run_mock.call_args.args[0])
        return secret, stderr.getvalue()

    def test_found_item_returns_the_secret(self) -> None:
        self.assertEqual((SECRET, ""), self.run_security(0, SECRET + "\n"))

    def test_missing_item_is_quiet_and_other_failures_are_reported(self) -> None:
        self.assertEqual(("", ""), self.run_security(44))
        secret, warning = self.run_security(51)
        self.assertEqual("", secret)
        self.assertIn("security exit 51", warning)

    def test_other_platforms_never_call_security(self) -> None:
        with mock.patch.object(argus_cli_op.sys, "platform", "linux"), mock.patch.object(argus_cli_op.subprocess, "run") as run_mock:
            self.assertEqual("", argus_cli_op.keychain_totp_secret())
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(hasattr(__import__("os"), "openpty"), "needs a pseudo-terminal")
class RealTerminalTests(unittest.TestCase):
    """open_tty against a real (non-seekable) terminal device, not a fake."""

    def test_open_tty_works_on_a_real_terminal(self) -> None:
        import os

        master, slave = os.openpty()
        try:
            tty = argus_cli_op.open_tty(os.ttyname(slave))
            self.assertIsNotNone(tty, "a non-seekable terminal must still open")
            tty.write("prompt> ")
            self.assertIn(b"prompt> ", os.read(master, 1024))
            os.write(master, b"nodens-staging\n")
            self.assertEqual("nodens-staging", tty.read_line(""))
            tty.close()
        finally:
            os.close(master)
            os.close(slave)

    def test_open_tty_returns_none_without_a_terminal(self) -> None:
        self.assertIsNone(argus_cli_op.open_tty("/nonexistent/argus-tty"))
