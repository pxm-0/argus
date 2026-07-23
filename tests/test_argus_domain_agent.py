from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_domain_agent import AgentService  # noqa: E402


class DomainAgentServiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
