from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m4_bootstrap import BootstrapError, personal_sandbox_contract  # noqa: E402


class M4BootstrapTest(unittest.TestCase):
    def test_contract_is_dedicated_and_sealed(self) -> None:
        contract = personal_sandbox_contract(user="argus-personal-sandbox")
        self.assertEqual("personal-sandbox", contract["domain"])
        self.assertIn("no-published-ports", contract["prohibitions"])
        self.assertTrue(contract["contractDigest"].startswith("sha256:"))
        with self.assertRaises(BootstrapError):
            personal_sandbox_contract(user="argus-pilot")

    def test_bootstrap_never_deploys_a_workload_or_opens_a_route(self) -> None:
        script = (ROOT / "scripts" / "argus-m4-personal-sandbox-bootstrap").read_text(encoding="utf-8")
        self.assertIn("--acknowledge-personal-sandbox-cell", script)
        self.assertIn("policy drop", script)
        self.assertIn("DOCKERD_ROOTLESS_ROOTLESSKIT_NET=none", script)
        self.assertIn("DOCKERD_ROOTLESS_ROOTLESSKIT_PORT_DRIVER=none", script)
        self.assertIn("--iptables=false", script)
        self.assertIn("Delegate=yes", script)
        self.assertIn("TasksMax=infinity", script)
        self.assertIn("systemctl --user", script)
        self.assertIn("--exec-opt native.cgroupdriver=systemd", script)
        self.assertIn("workloadsDeployed", script)
        self.assertNotIn("docker compose", script)
