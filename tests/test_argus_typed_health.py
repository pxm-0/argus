from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_api_client import ApiResponse, ApiUnavailable  # noqa: E402

SCRIPT = ROOT / "scripts" / "argus-typed-health"
loader = importlib.machinery.SourceFileLoader("argus_typed_health", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
typed = importlib.util.module_from_spec(spec)
loader.exec_module(typed)

HEALTH_ALLOWED = {"operations": {"health": {"allowed": True}}}


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class FakeClient:
    """Stands in for ApiClient: scripted terminal operation, no network."""

    def __init__(self, *, operation: dict | None = None, preview: ApiResponse | None = None, unreachable_at: str = "") -> None:
        self.terminal = operation or {}
        self.unreachable_at = unreachable_at
        self.calls: list[str] = []
        self._preview = preview or ApiResponse(200, {"allowed": True, "previewDigest": "d", "confirmationPhrase": "refresh health demo"})

    def _maybe_fail(self, step: str) -> None:
        self.calls.append(step)
        if step == self.unreachable_at:
            raise ApiUnavailable("API request failed: URLError")

    def preview(self, workload_id, operation_type, parameters):
        self._maybe_fail("preview")
        return self._preview

    def create(self, workload_id, operation_type, parameters, preview):
        self._maybe_fail("create")
        return ApiResponse(202, {"operation_id": "op-1", "state": "awaiting-approval"})

    def approve(self, operation_id, confirmation):
        self._maybe_fail("approve")
        return ApiResponse(202, {"state": "queued"})

    def operation(self, operation_id):
        self._maybe_fail("operation")
        return ApiResponse(200, self.terminal)


def terminal(state: str, ok: bool | None, **extra: object) -> dict:
    result = {} if ok is None else {"health": {"ok": ok, "status": "healthy" if ok else "unhealthy", "detail": "1 approved service(s) observed"}}
    return {"state": state, "redactedResult": result, "redacted_summary": "summary", **extra}


class TypedTargetTests(unittest.TestCase):
    def test_only_active_non_legacy_health_allowed_workloads_are_targeted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            rows = [
                ("nodens-staging", "active", "personal-sandbox", HEALTH_ALLOWED),
                ("nodens-production", "active", "personal-managed", HEALTH_ALLOWED),
                ("hastur", "active", "personal-sandbox", HEALTH_ALLOWED),  # excluded by id
                ("kadath", "active", "personal-sandbox", HEALTH_ALLOWED),
                ("nodens", "active", "personal-sandbox", HEALTH_ALLOWED),
                ("legacy-app", "active", "legacy-rootful", HEALTH_ALLOWED),
                ("unclassified", "active", None, HEALTH_ALLOWED),
                ("discovered-app", "discovered", "personal-sandbox", HEALTH_ALLOWED),
                ("no-health", "active", "personal-sandbox", {"operations": {"health": {"allowed": False}}}),
            ]
            write(repo / "config" / "workloads.json", {"workloads": [{"id": row[0], "lifecycle": row[1]} for row in rows]})
            write(
                repo / "config" / "argus" / "workload-classification.json",
                {"workloads": {row[0]: {"trustDomain": row[2]} for row in rows if row[2]}},
            )
            for workload_id, _, _, manifest in rows:
                write(repo / "workloads" / workload_id / "manifest.json", manifest)
            self.assertEqual(["nodens-production", "nodens-staging"], typed.typed_targets(repo))

    def test_checked_in_estate_never_targets_the_m5_timer_workloads(self) -> None:
        self.assertFalse({"hastur", "kadath", "nodens"} & set(typed.typed_targets(ROOT)))


class ObserveTests(unittest.TestCase):
    def observe(self, client: FakeClient) -> dict:
        ticks = iter(range(0, 10_000, 40))
        return typed.observe(client, "demo", sleep=lambda _: None, clock=lambda: next(ticks), deadline_seconds=100)

    def test_healthy_terminal_state(self) -> None:
        result = self.observe(FakeClient(operation=terminal("succeeded", True)))
        self.assertEqual(("healthy", "op-1"), (result["status"], result["operationId"]))

    def test_unhealthy_runtime_is_reported_even_though_the_operation_succeeded(self) -> None:
        result = self.observe(FakeClient(operation=terminal("succeeded", False)))
        self.assertEqual("unhealthy", result["status"])

    def test_failed_operation_is_unhealthy(self) -> None:
        self.assertEqual("unhealthy", self.observe(FakeClient(operation=terminal("failed", None)))["status"])

    def test_unreachable_api_at_any_step_is_classified_not_raised(self) -> None:
        for step in ("preview", "create", "approve", "operation"):
            with self.subTest(step):
                result = self.observe(FakeClient(operation=terminal("succeeded", True), unreachable_at=step))
                self.assertEqual("unreachable", result["status"])

    def test_policy_denial_never_creates_an_operation(self) -> None:
        client = FakeClient(preview=ApiResponse(200, {"allowed": False, "reason": "dom agent unavailable"}))
        result = self.observe(client)
        self.assertEqual(("denied", ["preview"]), (result["status"], client.calls))

    def test_non_terminal_operation_times_out(self) -> None:
        self.assertEqual("timeout", self.observe(FakeClient(operation={"state": "running"}))["status"])


class RunAndMainTests(unittest.TestCase):
    def test_run_appends_one_health_observed_line_per_workload_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ARGUS_ROOT": directory}):
            results = typed.run(FakeClient(operation=terminal("succeeded", False)), ["demo"], sleep=lambda _: None)
            lines = [json.loads(line) for line in (Path(directory) / "runtime" / "audit.log").read_text().splitlines()]
        self.assertEqual("unhealthy", results[0]["status"])
        self.assertEqual(1, len(lines))
        self.assertEqual(("health.observed", "demo", "failed", typed.OBSERVER_LOGIN), (lines[0]["action"], lines[0]["workloadId"], lines[0]["result"], lines[0]["actor"]))
        self.assertEqual(("unhealthy", "op-1"), (lines[0]["status"], lines[0]["operationId"]))

    def test_exit_code_is_non_zero_when_any_workload_is_unhealthy(self) -> None:
        for statuses, expected in ((["healthy"], 0), (["healthy", "unhealthy"], 1), (["unreachable"], 1)):
            with self.subTest(statuses), patch.object(typed, "typed_targets", return_value=["a"] * len(statuses)), patch.object(
                typed, "connect", return_value=object()
            ), patch.object(typed, "run", return_value=[{"workloadId": "a", "status": s, "detail": ""} for s in statuses]), patch.object(
                sys, "argv", ["argus-typed-health"]
            ):
                self.assertEqual(expected, typed.main())

    def test_setup_failure_exits_two_without_observing(self) -> None:
        with patch.object(typed, "typed_targets", return_value=["a"]), patch.object(
            typed, "connect", side_effect=typed.SetupError("credential observer-token is unreadable")
        ), patch.object(typed, "run") as run, patch.object(sys, "argv", ["argus-typed-health"]):
            self.assertEqual(2, typed.main())
        run.assert_not_called()


class RecordingApi(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), RecordingHandler)
        self.seen: list[tuple[str, str, dict[str, str]]] = []


class RecordingHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.seen.append((self.command, self.path, dict(self.headers)))
        raw = b"{}"
        self.send_response(201)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Set-Cookie", "argus_session=s; Path=/; HttpOnly")
        self.send_header("Set-Cookie", "argus_csrf=c; Path=/")
        self.end_headers()
        self.wfile.write(raw)


class ConnectTests(unittest.TestCase):
    def test_exchange_presents_observer_identity_proxy_token_and_dashboard_origin(self) -> None:
        server = RecordingApi()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                creds = Path(directory)
                (creds / "observer-token").write_text("OBSERVER-SECRET\n")
                # the real proxy-token file carries a KEY= prefix
                (creds / "operator-proxy-token").write_text("ARGUS_OPERATOR_PROXY_TOKEN=PROXY-SECRET\n")
                with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": directory, "ARGUS_OPERATOR_ORIGIN": "https://argus.example.ts.net"}):
                    client = typed.connect(ROOT, f"http://127.0.0.1:{server.server_address[1]}")
                    client.operation("0a")
        finally:
            server.shutdown()
            server.server_close()
        method, path, headers = server.seen[0]
        self.assertEqual("/api/session/exchange", path)
        self.assertEqual("https://argus.example.ts.net", headers["Origin"])
        self.assertEqual(typed.OBSERVER_LOGIN, headers["X-Argus-Tailnet-Login"])
        self.assertEqual("PROXY-SECRET", headers["X-Argus-Proxy-Token"])

    def test_missing_credentials_fail_closed_without_echoing_paths_or_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": directory}):
            with self.assertRaises(typed.SetupError) as raised:
                typed.connect(ROOT, "http://127.0.0.1:1")
        self.assertNotIn(directory, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
