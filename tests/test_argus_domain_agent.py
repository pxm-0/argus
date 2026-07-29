from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_domain_agent import AgentService  # noqa: E402
from argus_capabilities import Ed25519Signer, build_envelope  # noqa: E402
from argus_canonical import canonical_policy_version, canonical_revision  # noqa: E402
from argus_operations import digest  # noqa: E402


class DomainAgentServiceTests(unittest.TestCase):
    def service(self, directory: Path) -> tuple[AgentService, Ed25519Signer]:
        private_key = directory / "issuer.key"
        public_key = directory / "issuer.pub"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "ED25519",
                "-out",
                str(private_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        service = AgentService(
            ROOT,
            directory / "runtime",
            "personal-sandbox",
            [public_key],
            issuer_socket=directory / "issuer.sock",
            replay_db=directory / "capabilities.sqlite3",
        )
        return service, Ed25519Signer(private_key)

    def run_health_result(self, result: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            service, signer = self.service(root)
            revision = canonical_revision(ROOT, "hello-nginx")
            policy = canonical_policy_version(ROOT, "hello-nginx")
            preview = {
                "workloadId": "hello-nginx",
                "trustDomain": "personal-sandbox",
                "operationType": "health.refresh",
                "parameters": {},
                "expectedRevision": revision,
                "policyVersion": policy,
            }
            operation, _ = service.ledger.create(
                workload_id="hello-nginx",
                trust_domain="personal-sandbox",
                operation_type="health.refresh",
                requested_by="operator@example.com",
                parameters={},
                preview_digest=digest(preview),
                expected_revision=revision,
                policy_version=policy,
                idempotency_key="health-result",
            )
            claimed = service.ledger.claim(str(operation["operation_id"]))
            self.assertIsNotNone(claimed)
            signed = signer.sign(build_envelope(claimed))
            with (
                patch(
                    "argus_domain_agent.ipc_request",
                    return_value={
                        "ok": True,
                        "signedCapability": signed,
                    },
                ),
                patch.object(service, "execute_typed", return_value=result),
            ):
                return service.run_operation(str(operation["operation_id"]))

    def test_personal_sandbox_uses_rootless_socket_and_manifest_policy(self) -> None:
        previous = os.environ.get("DOCKER_HOST")
        try:
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                service, _signer = self.service(Path(directory))
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
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
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
