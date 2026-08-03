from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_sandbox_firewall as module  # noqa: E402


class FakeRunner(module.Runner):
    def __init__(self, *, unknown_link: bool = False) -> None:
        self.unknown_link = unknown_link

    def text(self, command: list[str]) -> str:
        joined = " ".join(command)
        if "network ls -q" in joined:
            return "a" * 64
        if "network inspect" in joined:
            return json.dumps(
                [
                    {
                        "Name": "alpha_default",
                        "Driver": "bridge",
                        "Id": "a" * 64,
                        "Labels": {
                            "com.docker.compose.project": "alpha",
                            "com.docker.compose.network": "default",
                        },
                        "Options": {},
                    }
                ]
            )
        if command[:4] == ["nsenter", "-t", "123", "-n"] and "link" in command:
            links = [{"ifname": "br-aaaaaaaaaaaa"}]
            if self.unknown_link:
                links.append({"ifname": "br-bbbbbbbbbbbb"})
            return json.dumps(links)
        if " ps -q" in joined:
            return "container-id"
        if " inspect container-id" in joined:
            return json.dumps(
                [
                    {
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": "alpha",
                                "com.docker.compose.service": "web",
                            }
                        },
                        "State": {"Pid": 456},
                        "NetworkSettings": {
                            "Networks": {
                                "preserved-name": {
                                    "IPAddress": "172.18.0.2",
                                    "NetworkID": "a" * 64,
                                }
                            }
                        },
                    }
                ]
            )
        raise AssertionError(command)


class ProbeRunner(module.Runner):
    def __init__(self, *, allow_cross_project: bool = False) -> None:
        self.allow_cross_project = allow_cross_project

    def run(self, command: list[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        pid = command[2]
        program = command[-1]
        own_address = {"101": "172.18.0.2", "202": "172.19.0.2"}[pid]
        reachable = own_address in program or self.allow_cross_project
        return subprocess.CompletedProcess(command, 0 if reachable else 1, "", "")


class EgressRunner(module.Runner):
    def __init__(self, answer: str = "203.0.113.10") -> None:
        self.answer = answer

    def run(self, command: list[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        if "dig" in command:
            return subprocess.CompletedProcess(command, 0, self.answer + "\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    def text(self, command: list[str]) -> str:
        return self.run(command).stdout.strip()


class SandboxFirewallTests(unittest.TestCase):
    def test_configured_projects_uses_active_canonical_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "workloads.json").write_text(
                json.dumps(
                    {
                        "workloads": [
                            {
                                "id": "alpha",
                                "lifecycle": "active",
                                "runtime": {"composeProject": "alpha-live"},
                                "migration": {"targetTrustDomain": "personal-sandbox"},
                            },
                            {
                                "id": "retired",
                                "lifecycle": "retired",
                                "runtime": {"composeProject": "retired"},
                                "migration": {"targetTrustDomain": "personal-sandbox"},
                            },
                        ]
                    }
                )
            )
            self.assertEqual(
                {"alpha": "alpha-live"},
                module.configured_projects(root, "personal-sandbox"),
            )

    @mock.patch.object(module, "rootless_child_pid", return_value=123)
    @mock.patch.object(module, "configured_projects", return_value={"alpha": "alpha"})
    def test_discovery_resolves_compose_identity_to_exact_live_interface(
        self, _projects: mock.Mock, _child: mock.Mock
    ) -> None:
        observed = module.discover_runtime(ROOT, "personal-sandbox", FakeRunner())
        self.assertEqual("br-aaaaaaaaaaaa", observed["networks"][0]["interface"])
        self.assertEqual("alpha", observed["endpoints"][0]["project"])
        self.assertEqual(456, observed["containers"][0]["pid"])

    @mock.patch.object(module, "rootless_child_pid", return_value=123)
    @mock.patch.object(module, "configured_projects", return_value={"alpha": "alpha"})
    def test_discovery_rejects_unknown_managed_bridge(
        self, _projects: mock.Mock, _child: mock.Mock
    ) -> None:
        with self.assertRaisesRegex(module.FirewallOperationError, "unknown managed bridge"):
            module.discover_runtime(ROOT, "personal-sandbox", FakeRunner(unknown_link=True))

    def test_plan_digest_binds_policy_and_runtime_mapping(self) -> None:
        observed = {
            "childPid": 123,
            "configuredProjects": {"alpha": "alpha"},
            "networks": [
                {"project": "alpha", "network": "default", "networkId": "a" * 64, "interface": "br-aaaaaaaaaaaa"}
            ],
            "endpoints": [
                {"project": "alpha", "network": "default", "service": "web", "addresses": ["172.18.0.2"]}
            ],
            "containers": [],
        }
        with (
            mock.patch.object(module, "discover_runtime", return_value=observed),
            mock.patch.object(module, "active_connectivity", return_value=[]),
            mock.patch.object(module, "declared_egress", return_value={}),
        ):
            first = module.build_plan(ROOT, "personal-sandbox", FakeRunner(), now=datetime(2026, 8, 3, tzinfo=timezone.utc))
            changed = json.loads(json.dumps(observed))
            changed["networks"][0]["networkId"] = "b" * 64
            with mock.patch.object(module, "discover_runtime", return_value=changed):
                second = module.build_plan(ROOT, "personal-sandbox", FakeRunner(), now=datetime(2026, 8, 3, tzinfo=timezone.utc))
        self.assertNotEqual(first["mappingDigest"], second["mappingDigest"])
        self.assertNotEqual(first["planDigest"], second["planDigest"])
        self.assertNotIn("br-*", first["rendered"])

    def test_probe_matrix_checks_own_project_and_every_directed_cross_pair(self) -> None:
        plan = {
            "domain": "personal-sandbox",
            "connectivity": [],
            "configuredProjects": {"alpha": "alpha", "beta": "beta"},
            "containers": [
                {"project": "alpha", "service": "argus-ingress", "pid": 101, "networks": ["default"]},
                {"project": "beta", "service": "argus-ingress", "pid": 202, "networks": ["default"]},
            ],
            "endpoints": [
                {"project": "alpha", "network": "default", "service": "web", "addresses": ["172.18.0.2"]},
                {"project": "beta", "network": "default", "service": "api", "addresses": ["172.19.0.2"]},
            ],
        }
        specs = {
            "alpha": {"project": "alpha", "domain": "personal-sandbox", "endpoint_service": "web", "endpoint_port": 80},
            "beta": {"project": "beta", "domain": "personal-sandbox", "endpoint_service": "api", "endpoint_port": 8080},
        }
        with mock.patch.object(module, "_sandbox_specs", return_value=(specs, mock.Mock())):
            result = module.probe_connectivity(ROOT, plan, ProbeRunner())
            failed = module.probe_connectivity(ROOT, plan, ProbeRunner(allow_cross_project=True))
        self.assertEqual("pass", result["result"])
        self.assertEqual(2, result["ownProjectChecks"])
        self.assertEqual(2, result["crossProjectChecks"])
        self.assertEqual(4, result["passedChecks"])
        self.assertEqual("fail", failed["result"])
        self.assertEqual(2, failed["unexpectedReachability"])

    def test_egress_probe_checks_udp_tcp_dns_and_declared_tcp_port(self) -> None:
        plan = {
            "containers": [
                {"project": "alpha", "service": "web", "pid": 101, "networks": ["default"]}
            ],
            "egress": {
                "alpha": {
                    "project": "alpha",
                    "resolver": "10.0.2.3",
                    "allow": (("tcp", 443),),
                    "reason": "reviewed",
                    "probeHost": "example.com",
                }
            },
        }
        result = module.probe_egress(plan, EgressRunner("93.184.216.34"))
        self.assertEqual("pass", result["result"])
        self.assertEqual(3, result["passedChecks"])
        with self.assertRaises(module.FirewallOperationError):
            module.probe_egress(plan, EgressRunner("10.0.0.2"))

    def test_public_command_help_and_apply_acknowledgement(self) -> None:
        executable = ROOT / "scripts" / "argus-sandbox-firewall"
        help_result = subprocess.run([sys.executable, str(executable), "--help"], text=True, capture_output=True, check=False)
        self.assertEqual(0, help_result.returncode)
        for contract in ("Privilege:", "Prerequisites:", "Source:", "Safety:", "Example:", "Recovery:"):
            self.assertIn(contract, help_result.stdout)
        refused = subprocess.run(
            [sys.executable, str(executable), "--domain", "personal-sandbox", "--apply"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(3, refused.returncode)
        self.assertIn("--plan-digest", refused.stderr)

        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "argus-sandbox-firewall"
            link.symlink_to(executable)
            linked_help = subprocess.run([str(link), "--help"], text=True, capture_output=True, check=False)
            self.assertEqual(0, linked_help.returncode, linked_help.stderr)


if __name__ == "__main__":
    unittest.main()
