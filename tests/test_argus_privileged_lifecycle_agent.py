from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_domain_agent import IndeterminateOperation
from argus_privileged_lifecycle_agent import LifecycleAgent


class PrivilegedLifecycleAgentTests(unittest.TestCase):
    def service(self) -> LifecycleAgent:
        service = object.__new__(LifecycleAgent)
        service.root = ROOT
        service.domain = "managed-production"
        service.ledger = Mock()
        return service

    def test_broker_allowlist_rejects_non_privileged_operations(self) -> None:
        service = self.service()
        self.assertFalse(service.policy_check("demo", "health.refresh", {})[0])
        self.assertTrue(service.policy_check("demo", "migration.cutover", {})[0])

    def test_root_unit_is_local_private_and_has_no_public_provider_authority(self) -> None:
        unit = (ROOT / "systemd" / "argus-privileged-lifecycle-agent.service").read_text()
        self.assertIn("User=root", unit)
        self.assertIn("UMask=0007", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertNotIn("Cloudflare", unit)
        self.assertNotIn("Funnel", unit)
        self.assertNotIn("AF_INET", unit)
        self.assertNotIn("/var/run/docker.sock", unit)

    def test_promotion_fences_source_before_starting_private_target(self) -> None:
        service = self.service()
        service.ledger.get.return_value = {"trust_domain": "personal-sandbox"}
        completed = Mock(returncode=0)
        with (
            patch.object(service, "require_private_target") as private,
            patch.object(service, "compose", return_value=completed) as compose,
            patch.object(service, "running", side_effect=[False, True]),
        ):
            result = service.execute_typed(
                "production.promote", "demo",
                {"sourceOperationId": "source", "targetTrustDomain": "managed-production"},
            )
        private.assert_called_once_with("managed-production", "demo")
        self.assertEqual(
            [call("personal-sandbox", "demo", "stop"), call("managed-production", "demo", "up", "-d")],
            compose.call_args_list,
        )
        self.assertFalse(result["publicExposure"])

    def test_failed_promotion_with_unproven_recovery_is_indeterminate(self) -> None:
        service = self.service()
        service.ledger.get.return_value = {"trust_domain": "personal-sandbox"}
        with (
            patch.object(service, "require_private_target"),
            patch.object(service, "compose", side_effect=[Mock(returncode=0), Mock(returncode=1), Mock(returncode=1)]),
            patch.object(service, "running", side_effect=[False, False]),
        ):
            with self.assertRaises(IndeterminateOperation):
                service.execute_typed(
                    "production.promote", "demo",
                    {"sourceOperationId": "source", "targetTrustDomain": "managed-production"},
                )

    def test_private_gate_rejects_ports_host_network_privilege_and_docker_socket(self) -> None:
        service = self.service()
        unsafe = '{"services":{"app":{"ports":["8080:80"],"volumes":["/var/run/docker.sock:/x"]}}}'
        with patch.object(service, "compose", return_value=Mock(returncode=0, stdout=unsafe)):
            with self.assertRaises(PermissionError):
                service.require_private_target("managed-production", "demo")


if __name__ == "__main__":
    unittest.main()
