from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
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


# (project, compose network, network id char, interface, service, address, pid)
SANDBOX = [
    ("hastur", "default", "a", "argus-hastur", "argus-ingress", "172.18.0.2", 101),
    ("kadath-live", "default", "b", "argus-kadath", "argus-ingress", "172.19.0.2", 102),
    ("nodens", "default", "c", "argus-nodens", "argus-ingress", "172.20.0.2", 103),
]
STAGING = ("nodens-staging", "internal", "d", "argus-ndns-stg", "nodens", "172.21.0.2", 104)
# /etc/argus/argus-personal-sandbox.nft as installed on oreochiserver before #354.
INSTALLED_POLICY = """destroy table inet argus_personal_sandbox
table inet argus_personal_sandbox {
  chain input { type filter hook input priority filter; policy drop; iifname "lo" accept; }
  chain forward {
    type filter hook forward priority filter; policy drop;
    iifname "argus-hastur" oifname "argus-hastur" accept;
    iifname "argus-kadath" oifname "argus-kadath" accept;
    iifname "argus-nodens" oifname "argus-nodens" accept;
    iifname "argus-hastur" oifname "tap0" ip daddr 10.0.2.3 udp dport 53 ct state new,established accept;
    iifname "argus-hastur" oifname "tap0" ip daddr 10.0.2.3 tcp dport 53 ct state new,established accept;
    iifname "argus-hastur" oifname "tap0" tcp dport 443 ct state new,established accept;
    iifname "tap0" oifname "argus-hastur" ct state established,related accept;
  }
  chain output { type filter hook output priority filter; policy drop; oifname "lo" accept; }
}
destroy table inet argus_personal_sandbox_nat
table inet argus_personal_sandbox_nat {
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    iifname "argus-hastur" oifname "tap0" masquerade;
  }
}
"""
STAGING_RULE = '    iifname "argus-ndns-stg" oifname "argus-ndns-stg" accept;\n'


class RuntimeRunner(module.Runner):
    """Docker and namespace inventory for the listed running projects."""

    def __init__(self, projects: list[tuple]) -> None:
        self.projects = projects

    def text(self, command: list[str]) -> str:
        joined = " ".join(command)
        if "network ls -q" in joined:
            return "\n".join(item[2] * 64 for item in self.projects)
        if "network inspect" in joined:
            return json.dumps(
                [
                    {
                        "Name": f"{project}_{network}",
                        "Driver": "bridge",
                        "Id": char * 64,
                        "Labels": {
                            "com.docker.compose.project": project,
                            "com.docker.compose.network": network,
                        },
                        "Options": {"com.docker.network.bridge.name": interface},
                    }
                    for project, network, char, interface, *_rest in self.projects
                ]
            )
        if "link" in command:
            return json.dumps([{"ifname": "tap0"}] + [{"ifname": item[3]} for item in self.projects])
        if " ps -q" in joined:
            return "\n".join(f"c{item[6]}" for item in self.projects)
        if " inspect c" in joined:
            return json.dumps(
                [
                    {
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": project,
                                "com.docker.compose.service": service,
                            }
                        },
                        "State": {"Pid": pid},
                        "NetworkSettings": {
                            "Networks": {network: {"IPAddress": address, "NetworkID": char * 64}}
                        },
                    }
                    for project, network, char, _interface, service, address, pid in self.projects
                ]
            )
        raise AssertionError(command)


def load_cutover() -> object:
    loader = importlib.machinery.SourceFileLoader(
        "argus_m5_workload_cutover_typed", str(ROOT / "scripts" / "argus-m5-workload-cutover")
    )
    cutover_spec = importlib.util.spec_from_loader(loader.name, loader)
    cutover = importlib.util.module_from_spec(cutover_spec)
    loader.exec_module(cutover)
    return cutover


@mock.patch.object(module, "rootless_child_pid", return_value=123)
class TypedDeployProjectTests(unittest.TestCase):
    NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def plan(self, projects: list[tuple]) -> dict:
        return module.build_plan(ROOT, "personal-sandbox", RuntimeRunner(projects), now=self.NOW)

    def test_reviewed_config_declares_nodens_staging_as_typed(self, _child: mock.Mock) -> None:
        self.assertEqual(
            {"nodens-staging": {"project": "nodens-staging", "bridge": "argus-ndns-stg"}},
            module.typed_projects(ROOT, "personal-sandbox"),
        )
        self.assertEqual(
            {"hastur": "hastur", "kadath": "kadath-live", "nodens": "nodens"},
            module.configured_projects(ROOT, "personal-sandbox"),
        )

    def test_nodens_compose_files_pin_their_manifest_bridge(self, _child: mock.Mock) -> None:
        for workload in ("nodens-staging", "nodens-production"):
            manifest = json.loads((ROOT / "workloads" / workload / "manifest.json").read_text())
            bridge = manifest["runtime"]["compose"]["bridge"]
            self.assertLessEqual(len(bridge), 15)
            compose = (ROOT / "workloads" / workload / "source" / "compose.yml").read_text()
            self.assertIn(f"com.docker.network.bridge.name: {bridge}\n", compose, workload)

    def test_cutover_policy_is_byte_identical_to_the_installed_policy(self, _child: mock.Mock) -> None:
        with mock.patch.object(module, "typed_projects", return_value={}):
            self.assertEqual(INSTALLED_POLICY, self.plan(SANDBOX)["rendered"])

    def test_typed_project_adds_only_its_bridge_rule_running_or_not(self, _child: mock.Mock) -> None:
        expected = INSTALLED_POLICY.replace(
            '"argus-nodens" accept;\n', '"argus-nodens" accept;\n' + STAGING_RULE
        )
        absent = self.plan(SANDBOX)
        running = self.plan([*SANDBOX, STAGING])
        self.assertEqual(expected, absent["rendered"])
        self.assertEqual(expected, running["rendered"])
        # The typed project never reaches cutover-only inventories or egress.
        self.assertEqual(absent["planDigest"], running["planDigest"])
        self.assertNotIn("nodens-staging", {item["project"] for item in running["containers"]})
        self.assertNotIn('"argus-ndns-stg" oifname "tap0"', running["rendered"])
        self.assertEqual({"nodens-staging": "argus-ndns-stg"}, module.discover_runtime(
            ROOT, "personal-sandbox", RuntimeRunner([*SANDBOX, STAGING])
        )["typedBridges"])

    def test_unknown_project_is_still_refused(self, _child: mock.Mock) -> None:
        unknown = ("rogue", "default", "e", "argus-rogue", "web", "172.22.0.2", 105)
        with self.assertRaisesRegex(module.FirewallOperationError, "projects differ"):
            self.plan([*SANDBOX, unknown])

    def test_missing_cutover_project_is_still_refused(self, _child: mock.Mock) -> None:
        with self.assertRaisesRegex(module.FirewallOperationError, "projects differ"):
            self.plan([SANDBOX[0], SANDBOX[1], STAGING])

    def test_typed_project_on_an_undeclared_bridge_is_refused(self, _child: mock.Mock) -> None:
        unnamed = (*STAGING[:3], "br-dddddddddddd", *STAGING[4:])
        with self.assertRaisesRegex(module.FirewallOperationError, "bridge does not match"):
            self.plan([*SANDBOX, unnamed])

    def test_typed_project_without_a_bridge_declaration_fails_closed(self, _child: mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "config", root / "config")
            shutil.copytree(ROOT / "workloads" / "nodens-staging", root / "workloads" / "nodens-staging")
            manifest_path = root / "workloads" / "nodens-staging" / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            del manifest["runtime"]["compose"]["bridge"]
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(module.FirewallOperationError, "stable bridge"):
                module.typed_projects(root, "personal-sandbox")

    def test_typed_project_cannot_receive_egress(self, _child: mock.Mock) -> None:
        egress = {"nodens-staging": {"project": "nodens-staging", "resolver": "10.0.2.3", "allow": (("tcp", 443),), "reason": "x"}}
        with self.assertRaises(module.FirewallPolicyError):
            module.render_firewall(
                "personal-sandbox", [], typed_bridges={"nodens-staging": "argus-ndns-stg"}, egress=egress
            )

    def test_cutover_reports_no_drift_while_staging_runs(self, _child: mock.Mock) -> None:
        cutover = load_cutover()
        expected = INSTALLED_POLICY.replace(
            '"argus-nodens" accept;\n', '"argus-nodens" accept;\n' + STAGING_RULE
        )
        with (
            mock.patch.object(cutover, "ROOT", ROOT),
            mock.patch.object(cutover, "FirewallRunner", return_value=RuntimeRunner([*SANDBOX, STAGING])),
            mock.patch.object(cutover.Path, "read_text", return_value=expected),
        ):
            rendered, _child_pid, networks = cutover.resolved_firewall_policy("personal-sandbox")
            self.assertEqual(expected, rendered)
            self.assertEqual(["hastur", "kadath-live", "nodens"], [item["project"] for item in networks])
            self.assertFalse(cutover.egress_policy_drift(cutover.SPECS["hastur"]))
        with (
            mock.patch.object(cutover, "ROOT", ROOT),
            mock.patch.object(cutover, "FirewallRunner", return_value=RuntimeRunner([*SANDBOX, STAGING])),
            mock.patch.object(cutover.Path, "read_text", return_value=INSTALLED_POLICY),
        ):
            self.assertTrue(cutover.egress_policy_drift(cutover.SPECS["hastur"]))


class SandboxFirewallTests(unittest.TestCase):
    def test_rootless_child_rejects_host_network_namespace(self) -> None:
        runner = mock.Mock(spec=module.Runner)
        runner.text.side_effect = ["123\n", "456\n"]
        with (
            mock.patch.object(module.pwd, "getpwnam", return_value=mock.Mock()),
            mock.patch.object(module.Path, "read_bytes", return_value=b"--state-dir=/var/lib/argus/personal-sandbox/rootlesskit"),
            mock.patch.object(module.os, "readlink", return_value="net:[1]"),
        ):
            with self.assertRaisesRegex(module.FirewallOperationError, "host network namespace"):
                module.rootless_child_pid("personal-sandbox", runner)

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
            "typedBridges": {},
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
