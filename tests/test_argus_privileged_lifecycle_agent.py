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
            patch.object(service, "running", side_effect=[False, True, False]),
            patch.object(service, "healthy", return_value=True),
            patch(
                "argus_privileged_lifecycle_agent.apply_tailscale_access",
                return_value={"summary": "Tailnet access applied and verified."},
            ),
            patch(
                "argus_privileged_lifecycle_agent.by_id",
                return_value={"demo": {}},
            ),
            patch(
                "argus_privileged_lifecycle_agent.load_manifest",
                return_value={"runtime": {"composeProject": "demo"}},
            ),
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
            patch.object(
                service, "compose",
                side_effect=[
                    Mock(returncode=0), Mock(returncode=1),
                    Mock(returncode=0), Mock(returncode=1),
                ],
            ),
            patch.object(service, "running", return_value=False),
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

    def test_private_gate_allows_only_explicit_loopback_ports(self) -> None:
        service = self.service()
        safe = '{"services":{"app":{"ports":[{"host_ip":"127.0.0.1","published":"18080","target":80}]}}}'
        with patch.object(service, "compose", return_value=Mock(returncode=0, stdout=safe)):
            service.require_private_target("managed-production", "demo")

    def test_private_gate_rejects_host_path_mounts(self) -> None:
        service = self.service()
        unsafe = '{"services":{"app":{"volumes":[{"type":"bind","source":"/srv/private","target":"/data"}]}}}'
        with patch.object(service, "compose", return_value=Mock(returncode=0, stdout=unsafe)):
            with self.assertRaises(PermissionError):
                service.require_private_target("managed-production", "demo")

    def test_migration_source_fence_revalidates_bound_evidence_before_stopping(self) -> None:
        service = self.service()
        parent = {
            "migration_id": "00000000-0000-4000-8000-000000000001",
            "source_trust_domain": "personal-sandbox",
            "target_trust_domain": "personal-managed",
        }
        service.ledger.migration_child_authorized.return_value = parent
        with (
            patch(
                "argus_privileged_lifecycle_agent.fresh_preview_matches",
                return_value=(False, {"eligible": False}),
            ),
            patch.object(service, "compose") as compose,
        ):
            with self.assertRaisesRegex(PermissionError, "evidence changed"):
                service.execute_typed(
                    "migration.source-fence",
                    "demo",
                    {
                        "_operation_id": "00000000-0000-4000-8000-000000000002",
                        "migrationId": parent["migration_id"],
                        "authorityEpoch": "00000000-0000-4000-8000-000000000003",
                        "sourceTrustDomain": "personal-sandbox",
                        "targetTrustDomain": "personal-managed",
                    },
        )
        compose.assert_not_called()

    def test_migration_source_fence_stops_only_the_bound_source_after_revalidation(self) -> None:
        service = self.service()
        parent = {
            "migration_id": "00000000-0000-4000-8000-000000000001",
            "source_trust_domain": "personal-sandbox",
            "target_trust_domain": "personal-managed",
        }
        service.ledger.migration_child_authorized.return_value = parent
        with (
            patch(
                "argus_privileged_lifecycle_agent.fresh_preview_matches",
                return_value=(True, {"eligible": True}),
            ),
            patch.object(service, "compose", return_value=Mock(returncode=0)) as compose,
            patch.object(service, "proven_running", return_value=False),
        ):
            result = service.execute_typed(
                "migration.source-fence",
                "demo",
                {
                    "_operation_id": "00000000-0000-4000-8000-000000000002",
                    "migrationId": parent["migration_id"],
                    "authorityEpoch": "00000000-0000-4000-8000-000000000003",
                    "sourceTrustDomain": "personal-sandbox",
                    "targetTrustDomain": "personal-managed",
                },
            )
        compose.assert_called_once_with("personal-sandbox", "demo", "stop")
        self.assertEqual("personal-sandbox", result["sourceTrustDomain"])
        self.assertFalse(result["publicExposure"])


if __name__ == "__main__":
    unittest.main()
