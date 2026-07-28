from __future__ import annotations

import json
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_operation_worker import OperationWorker  # noqa: E402
from argus_operations import OperationLedger  # noqa: E402
from argus_domain_agent import AgentRequestHandler, AgentService  # noqa: E402


class OperationWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        # DrvFS does not support Unix sockets; use the Linux filesystem for
        # the transport contract even when the checkout is on /mnt/c.
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.directory.name)
        self.ledger = OperationLedger(self.root / "operations.sqlite3")
        self.socket_dir = self.root / "agents"
        self.socket_dir.mkdir()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create_health(self, key: str = "health") -> dict[str, object]:
        operation, _ = self.ledger.create(
            workload_id="demo",
            trust_domain="personal-sandbox",
            operation_type="health.refresh",
            requested_by="operator@example.com",
            parameters={},
            preview_digest="preview",
            expected_revision="revision",
            policy_version="1",
            idempotency_key=key,
        )
        return operation

    def fake_agent(
        self,
        response: dict[str, object],
    ) -> tuple[threading.Thread, list[dict[str, object]]]:
        socket_path = self.socket_dir / "personal-sandbox.sock"
        received: list[dict[str, object]] = []
        ready = threading.Event()

        def serve() -> None:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                ready.set()
                connection, _ = server.accept()
                with connection:
                    encoded = connection.makefile("rb").readline(65_537)
                    received.append(json.loads(encoded))
                    connection.sendall(
                        (
                            json.dumps(
                                response,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        ).encode()
                    )

        thread = threading.Thread(target=serve)
        thread.start()
        self.assertTrue(ready.wait(2))
        return thread, received

    def test_worker_claims_and_dispatches_only_an_operation_id(self) -> None:
        operation = self.create_health()
        thread, received = self.fake_agent({"accepted": True, "ok": True})
        worker = OperationWorker(self.ledger, self.socket_dir)
        self.assertEqual((1, 0, 0), worker.run_once())
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(
            [{"operationId": operation["operation_id"]}],
            received,
        )
        persisted = self.ledger.get(str(operation["operation_id"]))
        self.assertEqual("running", persisted["state"])
        self.assertIsNotNone(persisted["started_at"])
        self.assertIsNotNone(persisted["heartbeat_at"])
        self.assertEqual(
            ["queued", "running"],
            [
                event["state"]
                for event in self.ledger.events(str(operation["operation_id"]))
            ],
        )
        self.assertEqual((0, 0, 0), worker.run_once())

    def test_unavailable_agent_leaves_queued_intent_undispatched(self) -> None:
        operation = self.create_health()
        worker = OperationWorker(self.ledger, self.socket_dir)
        self.assertEqual((0, 0, 0), worker.run_once())
        self.assertEqual(
            "queued",
            self.ledger.get(str(operation["operation_id"]))["state"],
        )

    def test_unconfirmed_dispatch_becomes_indeterminate_without_retry(self) -> None:
        operation = self.create_health()
        thread, received = self.fake_agent({"accepted": False, "ok": False})
        worker = OperationWorker(self.ledger, self.socket_dir)
        self.assertEqual((0, 1, 0), worker.run_once())
        thread.join(timeout=2)
        self.assertEqual(
            [{"operationId": operation["operation_id"]}],
            received,
        )
        persisted = self.ledger.get(str(operation["operation_id"]))
        self.assertEqual("indeterminate", persisted["state"])
        self.assertEqual("agent-dispatch-unconfirmed", persisted["error_class"])
        self.assertEqual((0, 0, 0), worker.run_once())

    def test_agent_acknowledges_then_persists_outcome_asynchronously(self) -> None:
        operation = self.create_health("agent-integration")
        socket_path = self.socket_dir / "personal-sandbox.sock"
        with patch.dict(
            "os.environ",
            {"ARGUS_OPERATIONS_DB": str(self.ledger.path)},
        ):
            service = AgentService(
                ROOT,
                self.root / "runtime",
                "personal-sandbox",
                b"x" * 32,
            )
        with patch.object(
            service.agent,
            "execute",
            return_value={
                "summary": "Domain-local evidence refreshed.",
                "health": {"ok": True, "status": "healthy", "detail": "typed"},
            },
        ):
            server = socketserver.ThreadingUnixStreamServer(
                str(socket_path),
                AgentRequestHandler,
            )
            server.service = service  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                worker = OperationWorker(self.ledger, self.socket_dir)
                self.assertEqual((1, 0, 0), worker.run_once())
                deadline = time.monotonic() + 2
                persisted = self.ledger.get(str(operation["operation_id"]))
                while persisted["state"] == "running" and time.monotonic() < deadline:
                    time.sleep(0.01)
                    persisted = self.ledger.get(str(operation["operation_id"]))
                self.assertEqual("succeeded", persisted["state"])
                self.assertEqual(
                    ["queued", "running", "succeeded"],
                    [
                        event["state"]
                        for event in self.ledger.events(str(operation["operation_id"]))
                    ],
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_units_keep_runtime_sockets_out_of_api_and_worker(self) -> None:
        api = (ROOT / "control-plane" / "api" / "server.py").read_text()
        api_unit = (ROOT / "systemd" / "argus-control-api.service").read_text()
        worker_unit = (
            ROOT / "systemd" / "argus-operation-worker.service"
        ).read_text()
        self.assertNotIn("dispatch_operation", api)
        self.assertIn("ARGUS_LEDGER_REQUIRE_EXISTING=1", api_unit)
        self.assertIn("User=argus-worker", worker_unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", worker_unit)
        self.assertIn(
            "InaccessiblePaths=-/var/run/docker.sock -/run/docker.sock",
            worker_unit,
        )
        self.assertNotIn("DOCKER_HOST", worker_unit)

    def test_activation_is_acknowledged_backed_up_and_rolls_back(self) -> None:
        script_path = ROOT / "scripts" / "argus-m5-ledger-worker"
        script = script_path.read_text()
        self.assertTrue(script_path.stat().st_mode & 0o111)
        self.assertIn("--acknowledge-m5-ledger-worker", script)
        self.assertIn("/var/backups/argus-m5-phase1/ledger-worker", script)
        self.assertIn("backup_sqlite_if_present", script)
        self.assertIn("unresolved operation(s)", script)
        self.assertIn("trap rollback_on_exit EXIT", script)
        self.assertIn("LEDGER_WORKER_ROLLED_BACK", script)
        self.assertIn("wait_for_api_fail_closed", script)
        self.assertIn("LEDGER_API_READY", script)
        self.assertIn("control API did not become ready within 10 seconds", script)
        self.assertIn("wait_for_ledger_schema", script)
        self.assertIn("LEDGER_SCHEMA_OK", script)
        self.assertIn(
            "operation ledger did not reach schema version 1 within 10 seconds",
            script,
        )
        self.assertIn(
            "wait_for_ledger_schema\n  wait_for_api_fail_closed",
            script,
        )
        self.assertIn("systemd-analyze verify", script)
        self.assertIn("publicExposureChanged=false", script)
        self.assertIn("secretsPrinted=false", script)
        self.assertNotIn("tailscale funnel", script.lower())
        self.assertNotIn("cloudflared", script.lower())


if __name__ == "__main__":
    unittest.main()
