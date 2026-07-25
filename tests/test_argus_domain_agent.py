from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_domain_agent import AgentService  # noqa: E402


class DomainAgentServiceTests(unittest.TestCase):
    def run_health_result(self, result: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            service = AgentService(ROOT, Path(directory), "personal-sandbox", b"x" * 32)
            operation, _ = service.ledger.create(
                workload_id="hello-nginx",
                trust_domain="personal-sandbox",
                operation_type="health.refresh",
                requested_by="operator@example.com",
                parameters={},
                preview_digest="preview",
                expected_revision="revision",
                policy_version="1",
                idempotency_key="health-result",
            )
            with patch.object(service.agent, "execute", return_value=result):
                return service.run_operation(str(operation["operation_id"]))

    def test_personal_sandbox_uses_rootless_socket_and_manifest_policy(self) -> None:
        previous = os.environ.get("DOCKER_HOST")
        try:
            with tempfile.TemporaryDirectory() as directory:
                service = AgentService(ROOT, Path(directory), "personal-sandbox", b"x" * 32)
                self.assertEqual(os.environ["DOCKER_HOST"], "unix:///var/lib/argus/personal-sandbox/docker.sock")
                self.assertEqual(service.policy_check("hello-nginx", "logs.preview", {}), (True, "logs disabled by manifest"))
                self.assertEqual(service.policy_check("hello-nginx", "workload.restart", {}), (True, "restart disabled by manifest"))
                command = service.compose_command("hello-nginx", "restart", "web")
                self.assertEqual(command[-2:], ["restart", "web"])
                self.assertNotIn("/var/run/docker.sock", " ".join(command))
        finally:
            if previous is None:
                os.environ.pop("DOCKER_HOST", None)
            else:
                os.environ["DOCKER_HOST"] = previous

    def test_agent_denies_cross_domain_and_unapproved_tailnet_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = AgentService(ROOT, Path(directory), "personal-sandbox", b"x" * 32)
            allowed, reason = service.policy_check("hello-nginx", "access.apply", {"desired": "tailnet"})
            self.assertFalse(allowed)
            self.assertIn("approved Tailscale Serve route", reason)
            with self.assertRaisesRegex(ValueError, "requires docker-compose"):
                # Standalone Docker workloads cannot smuggle an arbitrary runtime request.
                service.compose_command("dozzle", "restart")

    def test_unavailable_health_evidence_fails_operation_and_is_preserved(self) -> None:
        result = {
            "summary": "Domain-local runtime health evidence refreshed.",
            "health": {"ok": False, "status": "unavailable", "detail": "typed runtime health command failed"},
        }
        operation = self.run_health_result(result)
        self.assertEqual(operation["state"], "failed")
        self.assertEqual(operation["error_class"], "health-evidence-unavailable")
        self.assertEqual(operation["redactedResult"], result)

    def test_observed_unhealthy_workload_remains_completed_evidence(self) -> None:
        result = {
            "summary": "Domain-local runtime health evidence refreshed.",
            "health": {"ok": False, "status": "unhealthy", "detail": "1 approved service(s) observed"},
        }
        operation = self.run_health_result(result)
        self.assertEqual(operation["state"], "succeeded")
        self.assertIsNone(operation["error_class"])
        self.assertEqual(operation["redactedResult"], result)


if __name__ == "__main__":
    unittest.main()
