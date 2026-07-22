import importlib.util
import os
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


if __name__ == "__main__":
    unittest.main()
