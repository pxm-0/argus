import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-control-plane-reconcile"
DROPIN = ROOT / "systemd" / "caddy.service.d" / "argus-tailnet-readiness.conf"


def load_server():
    spec = importlib.util.spec_from_file_location("argus_control_server", ROOT / "control-plane" / "api" / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ControlPlaneReconcileTests(unittest.TestCase):
    def test_reconcile_is_acknowledged_backed_up_and_private(self) -> None:
        text = SCRIPT.read_text()
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertIn("--acknowledge-control-plane-reconcile", text)
        self.assertIn("control-plane-backups", text)
        self.assertIn("caddy validate", text)
        self.assertIn("publicExposureChanged=false", text)
        self.assertNotIn("tailscale funnel", text.lower())
        self.assertNotIn("cloudflared tunnel run", text.lower())

    def test_caddy_retries_after_late_tailnet_start(self) -> None:
        text = DROPIN.read_text()
        self.assertIn("After=tailscaled.service", text)
        self.assertIn("Restart=on-failure", text)

    def test_get_state_failure_returns_secret_safe_json_error(self) -> None:
        server = load_server()
        handler = object.__new__(server.Handler)
        handler.path = "/api/dashboard-state"
        responses = []
        handler.send_json = lambda status, payload: responses.append((status, payload))
        with patch.object(server, "dashboard_state", side_effect=PermissionError("sensitive path")):
            handler.do_GET()
        self.assertEqual(responses, [(500, {"error": "PermissionError"})])

    def test_only_requesting_operator_can_cancel_pending_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ARGUS_RUNTIME": directory}):
            server = load_server()
            operation, _ = server.LEDGER.create(
                workload_id="hello-nginx",
                trust_domain="personal-sandbox",
                operation_type="workload.restart",
                requested_by="operator@example.com",
                parameters={},
                preview_digest="preview",
                expected_revision="revision",
                policy_version="1",
                idempotency_key="cancel-owner-test",
            )
            handler = object.__new__(server.Handler)
            responses = []
            handler.send_json = lambda status, payload: responses.append((status, payload))
            other = server.Session("other", "other@example.com", "csrf", 0, int(time.time()) + 60, 0)
            handler.handle_operation_cancel(operation["operation_id"], other)
            self.assertEqual(responses[-1], (403, {"error": "operation belongs to another operator"}))
            owner = server.Session("owner", "operator@example.com", "csrf", 0, int(time.time()) + 60, 0)
            handler.handle_operation_cancel(operation["operation_id"], owner)
            self.assertEqual(responses[-1][0], 200)
            self.assertEqual(responses[-1][1]["state"], "denied")


if __name__ == "__main__":
    unittest.main()
