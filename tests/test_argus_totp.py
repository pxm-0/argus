from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_cli  # noqa: E402
import argus_totp  # noqa: E402
from argus_sessions import SessionStore, TOTP_LOCK_SECONDS  # noqa: E402

LOGIN = "owner@example.invalid"
TOKEN = "bootstrap-value"
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()
NOW = 1_700_000_010


class RfcVectorTests(unittest.TestCase):
    def test_rfc_6238_sha1_vectors_truncated_to_six_digits(self) -> None:
        for moment, expected in (
            (59, "287082"),
            (1111111109, "081804"),
            (1111111111, "050471"),
            (1234567890, "005924"),
            (2000000000, "279037"),
            (20000000000, "353130"),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(expected, argus_totp.hotp(RFC_SECRET, argus_totp.counter_at(moment)))

    def test_secret_is_160_bits_and_uri_names_the_parameters(self) -> None:
        self.assertEqual(20, len(base64.b32decode(argus_totp.generate_secret())))
        uri = argus_totp.otpauth_uri(LOGIN, RFC_SECRET)
        for part in ("otpauth://totp/Argus:", "algorithm=SHA1", "digits=6", "period=30", f"secret={RFC_SECRET}"):
            self.assertIn(part, uri)

    def test_skew_of_one_step_is_accepted_and_two_rejected(self) -> None:
        center = argus_totp.counter_at(NOW)
        for offset, accepted in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
            with self.subTest(offset=offset):
                code = argus_totp.hotp(RFC_SECRET, center + offset)
                found = argus_totp.matching_counter(RFC_SECRET, code, NOW)
                self.assertEqual(center + offset if accepted else None, found)

    def test_wrong_length_and_non_digit_codes_never_match(self) -> None:
        for bad in ("", "12345", "1234567", "abcdef", "      "):
            self.assertIsNone(argus_totp.matching_counter(RFC_SECRET, bad, NOW))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = [NOW]
        self.store = SessionStore(Path(self.directory.name) / "s.sqlite3", clock=lambda: self.now[0])
        self.entry, self.codes = argus_totp.new_enrollment(LOGIN)

    def verify(self, code: str) -> bool:
        return self.store.verify_second_factor(
            LOGIN, code, secret=self.entry["secret"], recovery_hashes=self.entry["recoveryCodeHashes"]
        )

    def code(self, offset: int = 0) -> str:
        return argus_totp.hotp(self.entry["secret"], argus_totp.counter_at(self.now[0]) + offset)

    def test_replayed_code_is_identified_but_a_wrong_code_is_not(self) -> None:
        secret = self.entry["secret"]
        self.assertFalse(self.store.is_replayed_code(LOGIN, self.code(), secret=secret))
        self.assertTrue(self.verify(self.code()))
        self.assertTrue(self.store.is_replayed_code(LOGIN, self.code(), secret=secret))
        self.assertFalse(self.store.is_replayed_code(LOGIN, "000000" if self.code() != "000000" else "111111", secret=secret))
        self.assertFalse(self.store.is_replayed_code(LOGIN, self.codes[0], secret=secret))

    def test_replay_and_older_counters_are_rejected(self) -> None:
        self.assertTrue(self.verify(self.code()))
        self.assertFalse(self.verify(self.code()))
        self.assertFalse(self.verify(self.code(-1)))
        self.assertTrue(self.verify(self.code(1)))
        self.assertFalse(self.verify(self.code(1)))

    def test_concurrent_submissions_of_one_code_accept_exactly_one(self) -> None:
        code, results, barrier = self.code(), [], threading.Barrier(8)

        def attempt() -> None:
            barrier.wait()
            results.append(self.verify(code))

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, results.count(True))

    def test_recovery_code_is_single_use_and_other_codes_fail(self) -> None:
        self.assertTrue(self.verify(self.codes[0].lower().replace("-", " ")))
        self.assertFalse(self.verify(self.codes[0]))
        self.assertTrue(self.verify(self.codes[1]))
        self.assertFalse(self.verify("AAAAA-AAAAA"))

    def test_five_failures_lock_for_fifteen_minutes_then_expire(self) -> None:
        for _ in range(4):
            self.assertEqual(0, self.store.record_failure(LOGIN))
        self.assertEqual(0, self.store.lockout_remaining(LOGIN))
        self.assertEqual(TOTP_LOCK_SECONDS, self.store.record_failure(LOGIN))
        self.assertEqual(TOTP_LOCK_SECONDS, self.store.lockout_remaining(LOGIN))
        self.now[0] += TOTP_LOCK_SECONDS - 1
        self.assertEqual(1, self.store.lockout_remaining(LOGIN))
        self.now[0] += 1
        self.assertEqual(0, self.store.lockout_remaining(LOGIN))
        self.assertEqual(0, self.store.record_failure(LOGIN))

    def test_failures_outside_the_five_minute_window_do_not_accumulate(self) -> None:
        for _ in range(4):
            self.store.record_failure(LOGIN)
        self.now[0] += 301
        self.assertEqual(0, self.store.record_failure(LOGIN))
        self.assertEqual(0, self.store.lockout_remaining(LOGIN))

    def test_success_clears_failures_and_locks_are_per_login(self) -> None:
        for _ in range(4):
            self.store.record_failure(LOGIN)
        self.store.clear_failures(LOGIN)
        self.assertEqual(0, self.store.record_failure(LOGIN))
        for _ in range(5):
            self.store.record_failure("other@example.invalid")
        self.assertEqual(0, self.store.lockout_remaining(LOGIN))


class SecretsFileTests(unittest.TestCase):
    def test_atomic_0600_write_round_trips_and_rejects_bad_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operator-totp.json"
            entry, _ = argus_totp.new_enrollment(LOGIN)
            argus_totp.write_operators(path, {LOGIN: entry})
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual([path.name], os.listdir(directory))
            self.assertEqual({LOGIN: entry}, argus_totp.load_operators(path))
            path.write_text(json.dumps({"schemaVersion": 1, "operators": {LOGIN: {"secret": "!!"}}}))
            with self.assertRaises(argus_totp.TotpError):
                argus_totp.load_operators(path)
            with self.assertRaises(FileNotFoundError):
                argus_totp.load_operators(Path(directory) / "missing.json")


class FakeTty:
    def __init__(self, answers: list[str]) -> None:
        self.answers, self.output = list(answers), ""

    def write(self, text: str) -> None:
        self.output += text

    def read_line(self, prompt: str) -> str:
        self.output += prompt
        return self.answers.pop(0)


class EnrollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = Path(self.directory.name)
        self.operators = base / "operators.json"
        self.operators.write_text(json.dumps({"schemaVersion": 1, "operators": [{"tailnetLogin": LOGIN, "role": "owner", "enabled": True}]}))
        self.secrets = base / "operator-totp.json"

    def enroll(self, tty, *, euid: int = 0, stdin_is_tty: bool = True, rotate: bool = False, login: str = "", now=lambda: NOW) -> str:
        return argus_totp.enroll(login=login, rotate=rotate, tty=tty, euid=euid, stdin_is_tty=stdin_is_tty, secrets_file=self.secrets, operators_file=self.operators, now=now)

    def refused(self, code: str, tty, **kwargs) -> None:
        with self.assertRaises(argus_totp.EnrollRefused) as caught:
            self.enroll(tty, **kwargs)
        self.assertEqual(code, caught.exception.code)
        self.assertFalse(self.secrets.exists())

    def test_refuses_non_root_and_non_tty_before_anything_is_shown(self) -> None:
        tty = FakeTty([])
        self.refused("totp-root-required", tty, euid=1000)
        self.refused("totp-tty-required", tty, stdin_is_tty=False)
        self.refused("totp-tty-required", None)
        self.assertEqual("", tty.output)

    def test_wrong_code_writes_nothing_and_valid_code_commits_once(self) -> None:
        self.refused("totp-confirmation-failed", FakeTty(["000000", "111111", "222222"]))

        captured: list[str] = []

        class Tty(FakeTty):
            def read_line(self, prompt: str) -> str:
                uri = next(line for line in self.output.splitlines() if "otpauth://" in line)
                secret = uri.split("secret=")[1].split("&")[0]
                captured.append(secret)
                return argus_totp.hotp(secret, argus_totp.counter_at(NOW))

        tty = Tty([])
        self.assertEqual(LOGIN, self.enroll(tty))
        self.assertEqual(0o600, stat.S_IMODE(self.secrets.stat().st_mode))
        stored = argus_totp.load_operators(self.secrets)[LOGIN]
        self.assertEqual(captured[0], stored["secret"])
        self.assertEqual(10, len(stored["recoveryCodeHashes"]))
        self.assertEqual(10, sum(1 for line in tty.output.splitlines() if argus_totp.is_recovery_shape(line.strip()) and "-" in line))
        self.assertNotIn(stored["secret"], self.secrets.with_name("operators.json").read_text())

        with self.assertRaises(argus_totp.EnrollRefused) as again:
            self.enroll(Tty([]))
        self.assertEqual("totp-already-enrolled", again.exception.code)
        self.assertEqual(LOGIN, self.enroll(Tty([]), rotate=True))
        self.assertNotEqual(stored["secret"], argus_totp.load_operators(self.secrets)[LOGIN]["secret"])

    def test_unknown_operator_is_refused(self) -> None:
        self.refused("totp-operator-unknown", FakeTty([]), login="intruder@example.invalid")

    def test_cli_command_refuses_without_root_or_terminal(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("argus_cli_op.open_tty", return_value=None):
            code = argus_cli.run(["keys", "totp-enroll", "--json"], repo=ROOT, stdout=stdout, stderr=stderr)
        self.assertEqual(3, code)
        self.assertIn(json.loads(stdout.getvalue())["error"]["code"], {"totp-root-required", "totp-tty-required"})


def load_server(environment: dict[str, str]):
    with patch.dict(os.environ, environment):
        spec = importlib.util.spec_from_file_location("argus_control_totp", ROOT / "control-plane" / "api" / "server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = Path(self.directory.name)
        (base / "operators.json").write_text(json.dumps({"schemaVersion": 1, "operators": [{"tailnetLogin": LOGIN, "role": "owner", "enabled": True}]}))
        (base / "proxy").write_text("proxy-marker\n")
        (base / "token").write_text(TOKEN + "\n")
        self.totp_path = base / "operator-totp.json"
        self.entry, self.codes = argus_totp.new_enrollment(LOGIN)
        self.server = load_server({
            "ARGUS_RUNTIME": str(base / "runtime"),
            "ARGUS_OPERATORS_FILE": str(base / "operators.json"),
            "ARGUS_PROXY_TOKEN_FILE": str(base / "proxy"),
            "ARGUS_TOKEN_FILE": str(base / "token"),
            "ARGUS_TOTP_FILE": str(self.totp_path),
            "ARGUS_OPERATOR_ORIGIN": "https://argus.example.ts.net",
        })
        origin = patch.dict(os.environ, {"ARGUS_OPERATOR_ORIGIN": "https://argus.example.ts.net"})
        origin.start()
        self.addCleanup(origin.stop)
        self.clock = [NOW]
        self.server.SESSIONS.clock = lambda: self.clock[0]
        self.audit = Mock()
        patcher = patch.object(self.server, "audit", self.audit)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.next_counter = argus_totp.counter_at(NOW) - 1

    def enroll(self) -> None:
        argus_totp.write_operators(self.totp_path, {LOGIN: self.entry})

    def code(self) -> str:
        """A never-repeated code that is inside the server's accepted window."""
        self.next_counter = max(self.next_counter + 1, argus_totp.counter_at(self.clock[0]))
        overshoot = self.next_counter - argus_totp.counter_at(self.clock[0]) - 1
        if overshoot > 0:
            self.clock[0] += argus_totp.PERIOD * overshoot
        return argus_totp.hotp(self.entry["secret"], self.next_counter)

    def handler(self, path: str, body: dict, cookies: str = "", csrf: str = ""):
        handler = object.__new__(self.server.Handler)
        handler.client_address = ("127.0.0.1", 1)
        handler.path = path
        handler.headers = {
            "X-Argus-Tailnet-Login": LOGIN,
            "X-Argus-Proxy-Token": "proxy-marker",
            "X-Argus-CSRF-Bootstrap": "a" * 43,
            "Cookie": cookies,
            "X-Argus-CSRF": csrf,
            "Origin": "https://argus.example.ts.net",
        }
        handler.read_body = lambda: body
        handler.sent = []
        handler.send_json = lambda status, payload, headers=None: handler.sent.append((status, payload, dict(headers or [])))
        return handler

    def exchange(self, body: dict) -> tuple[int, dict, dict]:
        handler = self.handler("/api/session/exchange", body)
        handler.handle_post()
        return handler.sent[-1]

    def test_unenrolled_operator_needs_only_the_token_unless_required(self) -> None:
        self.assertEqual(201, self.exchange({"bootstrapToken": TOKEN})[0])
        with patch.dict(os.environ, {"ARGUS_TOTP_REQUIRED": "1"}):
            self.assertEqual(403, self.exchange({"bootstrapToken": TOKEN})[0])

    def test_enrolled_operator_needs_both_factors_with_generic_401(self) -> None:
        self.enroll()
        for body in ({"bootstrapToken": TOKEN}, {"bootstrapToken": TOKEN, "totp": "000000"}, {"bootstrapToken": "wrong", "totp": self.code()}, {"totp": self.code()}):
            status, payload, _ = self.exchange(body)
            self.assertEqual(401, status, body)
            self.assertEqual({"error": "verified tailnet identity and valid credentials required"}, payload)
        self.assertEqual(201, self.exchange({"bootstrapToken": TOKEN, "totp": self.code()})[0])

    def test_recovery_code_substitutes_once(self) -> None:
        self.enroll()
        self.assertEqual(201, self.exchange({"bootstrapToken": TOKEN, "totp": self.codes[0]})[0])
        self.assertEqual(401, self.exchange({"bootstrapToken": TOKEN, "totp": self.codes[0]})[0])

    def test_unknown_body_keys_are_rejected(self) -> None:
        with self.assertRaises(self.server.OperationValidationError):
            self.exchange({"bootstrapToken": TOKEN, "totp": "1", "extra": "x"})

    def test_lockout_returns_429_even_with_correct_credentials_and_before_reading_the_token(self) -> None:
        self.enroll()
        for _ in range(5):
            self.assertEqual(401, self.exchange({"bootstrapToken": "wrong", "totp": "000000"})[0])
        reads = Mock(side_effect=AssertionError("token file read while locked"))
        with patch.object(self.server, "bootstrap_token", reads):
            for _ in range(2):
                status, _, headers = self.exchange({"bootstrapToken": TOKEN, "totp": self.code()})
                self.assertEqual(429, status)
                self.assertEqual(str(TOTP_LOCK_SECONDS), headers["Retry-After"])
        reads.assert_not_called()
        self.clock[0] += TOTP_LOCK_SECONDS
        self.assertEqual(201, self.exchange({"bootstrapToken": TOKEN, "totp": self.code()})[0])

    def test_lockout_covers_unenrolled_token_guessing_too(self) -> None:
        for _ in range(5):
            self.exchange({"bootstrapToken": "wrong"})
        self.assertEqual(429, self.exchange({"bootstrapToken": TOKEN})[0])

    def test_step_up_applies_the_same_factors_and_lockout(self) -> None:
        self.enroll()
        created = self.server.SESSIONS.create(LOGIN, stepped_up=False)
        cookies = f"argus_session={created.session_id}; argus_csrf={created.csrf_token}"

        def step_up(body: dict) -> int:
            handler = self.handler("/api/session/step-up", body, cookies, created.csrf_token)
            handler.handle_post()
            return handler.sent[-1][0]

        self.assertEqual(401, step_up({"bootstrapToken": TOKEN, "totp": "000000"}))
        self.assertEqual(200, step_up({"bootstrapToken": TOKEN, "totp": self.code()}))
        for _ in range(5):
            step_up({"bootstrapToken": "wrong", "totp": "000000"})
        self.assertEqual(429, step_up({"bootstrapToken": TOKEN, "totp": self.code()}))

    def test_rejection_audit_contains_no_submitted_values(self) -> None:
        self.enroll()
        submitted = {"bootstrapToken": "tok-secret-value", "totp": "654321"}
        self.exchange(submitted)
        for _ in range(5):
            self.exchange(submitted)
        recorded = json.dumps(self.audit.call_args_list, default=str)
        self.assertTrue(self.audit.called)
        for value in submitted.values():
            self.assertNotIn(value, recorded)

    def test_malformed_secrets_file_fails_closed(self) -> None:
        self.totp_path.write_text("{not json")
        self.assertEqual(401, self.exchange({"bootstrapToken": TOKEN})[0])


if __name__ == "__main__":
    unittest.main()
