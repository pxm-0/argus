from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_access_runtime import apply_tailscale_access, route_contract  # noqa: E402


class FakeTailscale:
    def __init__(self, mapping: str = "") -> None:
        self.mapping = mapping
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[-2:] == ["status", "--json"]:
            web = {}
            if self.mapping:
                web["server.example.ts.net:8444"] = {"Handlers": {"/": {"Proxy": self.mapping}}}
            return subprocess.CompletedProcess(command, 0, json.dumps({"Web": web}), "")
        if command[-1] == "off":
            self.mapping = ""
            return subprocess.CompletedProcess(command, 0, "", "")
        self.mapping = command[-1]
        return subprocess.CompletedProcess(command, 0, "", "")


class AccessRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "routes.json").write_text(json.dumps({
            "workloadRoutes": {
                "demo": {
                    "tailnet": {
                        "enabled": True,
                        "mode": "tailscale-serve",
                        "url": "https://server.example.ts.net:8444",
                    }
                }
            }
        }))
        self.workload = {"network": {"localUrl": "http://127.0.0.1:8080"}}

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_contract_rejects_non_loopback_target(self) -> None:
        workload = {"network": {"localUrl": "http://0.0.0.0:8080"}}
        contract, reason = route_contract(self.root, workload, "demo")
        self.assertIsNone(contract)
        self.assertIn("loopback", reason)

    def test_tailnet_apply_and_remove_are_exact_and_verified(self) -> None:
        tailscale = FakeTailscale()
        applied = apply_tailscale_access(self.root, self.workload, "demo", "tailnet", run=tailscale)
        self.assertTrue(applied["changed"])
        self.assertEqual(tailscale.mapping, "http://127.0.0.1:8080")
        removed = apply_tailscale_access(self.root, self.workload, "demo", "local", run=tailscale)
        self.assertTrue(removed["changed"])
        self.assertEqual(tailscale.mapping, "")
        self.assertIn(["tailscale", "serve", "--yes", "--https=8444", "off"], tailscale.commands)

    def test_different_existing_mapping_fails_closed(self) -> None:
        tailscale = FakeTailscale("http://127.0.0.1:9999")
        with self.assertRaisesRegex(PermissionError, "different target"):
            apply_tailscale_access(self.root, self.workload, "demo", "tailnet", run=tailscale)
        self.assertEqual(len(tailscale.commands), 1)


if __name__ == "__main__":
    unittest.main()
