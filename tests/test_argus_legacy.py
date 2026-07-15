from __future__ import annotations

import importlib.util
import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from argus_legacy import (  # noqa: E402
    CommandResult,
    LEGACY_CLASSIFICATION,
    address_scope,
    collect_inventory,
    docker_containers,
    firewall_inventory,
    mount_finding,
    normalize_mount,
    parse_ss_listeners,
    write_inventory,
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]):
        self.responses = responses

    def run(self, command: list[str]) -> CommandResult:
        return self.responses.get(tuple(command), CommandResult(127, "", "missing fake"))


class ArgusLegacyInventoryTest(unittest.TestCase):
    def test_address_scope_classifies_wildcard_loopback_private_and_public(self) -> None:
        self.assertEqual("wildcard", address_scope("0.0.0.0"))
        self.assertEqual("wildcard", address_scope("::"))
        self.assertEqual("loopback", address_scope("127.0.0.1"))
        self.assertEqual("private", address_scope("10.0.0.8"))
        self.assertEqual("public", address_scope("8.8.8.8"))

    def test_listener_parser_omits_addresses_but_keeps_scope_and_port(self) -> None:
        output = "tcp LISTEN 0 4096 0.0.0.0:443 0.0.0.0:*\n" "udp UNCONN 0 0 [::1]:53 [::]:*\n"
        self.assertEqual(
            [
                {"protocol": "tcp", "port": "443", "addressScope": "wildcard"},
                {"protocol": "udp", "port": "53", "addressScope": "loopback"},
            ],
            parse_ss_listeners(output),
        )

    def test_mount_source_is_replaced_and_prohibited_destination_blocks(self) -> None:
        mount = normalize_mount(
            {
                "Type": "bind",
                "Source": "/home/operator/.ssh",
                "Destination": "/root/.ssh",
                "RW": True,
                "Propagation": "rprivate",
            }
        )
        self.assertNotIn("/home/operator", json.dumps(mount))
        self.assertTrue(mount["sourceRef"].startswith("sha256:"))
        self.assertEqual("operator-identity", mount["blockingFinding"])
        self.assertFalse(mount["readOnly"])
        self.assertEqual("runtime-control", mount_finding("/var/run/docker.sock", "/run/service.sock"))
        self.assertEqual("host-capability", mount_finding("/host/sys", "/sys"))

    def test_complete_inventory_normalizes_docker_data_without_host_paths(self) -> None:
        inspect_payload = [
            {
                "Id": "container-id",
                "Name": "/example",
                "Config": {
                    "Image": "example:latest",
                    "Labels": {
                        "com.docker.compose.project": "example-project",
                        "com.docker.compose.service": "web",
                    },
                },
                "HostConfig": {
                    "Privileged": False,
                    "NetworkMode": "bridge",
                    "PidMode": "",
                    "CapAdd": None,
                    "Devices": [],
                },
                "NetworkSettings": {
                    "Networks": {"example_default": {}},
                    "Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18080"}]},
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": "/private/source",
                        "Destination": "/app/data",
                        "RW": True,
                        "Propagation": "rprivate",
                    }
                ],
            }
        ]
        nft_payload = {
            "nftables": [
                {"chain": {"family": "inet", "table": "filter", "name": "input", "hook": "input", "policy": "drop"}}
            ]
        }
        runner = FakeRunner(
            {
                ("docker", "ps", "--no-trunc", "--format", "{{.ID}}"): CommandResult(0, "container-id\n"),
                ("docker", "inspect", "container-id"): CommandResult(0, json.dumps(inspect_payload)),
                ("docker", "network", "ls", "--format", "{{.Name}}"): CommandResult(0, "example_default\n"),
                ("docker", "volume", "ls", "--format", "{{.Name}}"): CommandResult(0, "example_data\n"),
                ("ss", "-H", "-lntu"): CommandResult(0, "tcp LISTEN 0 4096 127.0.0.1:22 0.0.0.0:*\n"),
                ("nft", "--json", "list", "ruleset"): CommandResult(0, json.dumps(nft_payload)),
            }
        )
        payload = collect_inventory(runner)
        if os.geteuid() == 0:
            self.assertTrue(payload["complete"])
        container = payload["containers"][0]
        self.assertEqual("wildcard-listener", container["publishedPorts"][0]["blockingFinding"])
        self.assertEqual(18080, container["publishedPorts"][0]["publicPort"])
        self.assertNotIn("/private/source", json.dumps(payload))
        self.assertEqual(["wildcard-listener"], payload["blockingFindings"])

    def test_container_host_capabilities_are_blocking_findings(self) -> None:
        inspect_payload = [
            {
                "Id": "dangerous-container",
                "Name": "/dangerous",
                "Config": {"Image": "example:latest", "Labels": {}},
                "HostConfig": {
                    "Privileged": True,
                    "NetworkMode": "host",
                    "PidMode": "host",
                    "CapAdd": ["SYS_ADMIN"],
                    "Devices": [{"PathOnHost": "/dev/example"}],
                },
                "NetworkSettings": {"Networks": {}, "Ports": {}},
                "Mounts": [],
            }
        ]
        runner = FakeRunner(
            {
                ("docker", "ps", "--no-trunc", "--format", "{{.ID}}"): CommandResult(0, "dangerous-container\n"),
                ("docker", "inspect", "dangerous-container"): CommandResult(0, json.dumps(inspect_payload)),
            }
        )
        containers, gaps = docker_containers(runner)
        self.assertEqual([], gaps)
        self.assertEqual(
            ["added-capabilities", "host-device", "host-network", "host-pid", "privileged-container"],
            containers[0]["blockingFindings"],
        )
        self.assertNotIn("PathOnHost", json.dumps(containers))

    def test_firewall_inventory_falls_back_to_iptables_and_rejects_bad_nft_json(self) -> None:
        malformed = FakeRunner({("nft", "--json", "list", "ruleset"): CommandResult(0, "not-json")})
        evidence, gaps = firewall_inventory(malformed)
        self.assertFalse(evidence["verified"])
        self.assertEqual(["nftables-output-invalid"], gaps)

        fallback = FakeRunner(
            {
                ("nft", "--json", "list", "ruleset"): CommandResult(1, ""),
                ("iptables-save",): CommandResult(0, ":INPUT DROP [0:0]\n:FORWARD DROP [0:0]\n"),
            }
        )
        evidence, gaps = firewall_inventory(fallback)
        self.assertEqual("iptables", evidence["backend"])
        self.assertEqual(2, evidence["chainCount"])
        self.assertEqual(["DROP"], evidence["policies"])
        self.assertEqual([] if os.geteuid() == 0 else ["firewall-inventory-not-privileged"], gaps)

    def test_collect_inventory_is_incomplete_when_server_tools_are_unavailable(self) -> None:
        payload = collect_inventory(FakeRunner({}))
        self.assertFalse(payload["complete"])
        self.assertTrue(payload["readOnly"])
        self.assertEqual(LEGACY_CLASSIFICATION, payload["classification"])
        self.assertIn("firewall-inventory-unavailable", payload["evidenceGaps"])
        self.assertEqual(8, len(payload["trackedWorkloads"]))

    def test_write_inventory_is_private_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            destination = Path(directory) / "legacy-inventory.json"
            write_inventory({"ok": True}, destination)
            mode = stat.S_IMODE(os.stat(destination).st_mode)
            self.assertEqual(0o600, mode)
            self.assertEqual({"ok": True}, json.loads(destination.read_text()))
            self.assertFalse(destination.with_suffix(".json.tmp").exists())

    def test_every_tracked_workload_is_quarantined_and_new_admission_is_denied(self) -> None:
        tracked = json.loads((ROOT / "config" / "workloads.json").read_text())["workloads"]
        baseline = json.loads((ROOT / "config" / "argus" / "legacy-classification.json").read_text())
        policy = json.loads((ROOT / "config" / "policy.json").read_text())
        self.assertEqual({item["id"] for item in tracked}, set(baseline["workloads"]))
        for classification in baseline["workloads"].values():
            self.assertEqual("legacy-unclassified", classification["status"])
            self.assertEqual("denied", classification["admission"])
        self.assertFalse(policy["rules"]["allowNewLegacyRootfulAdmission"])
        self.assertTrue(policy["rules"]["requireLegacyUnclassifiedQuarantine"])

    def test_workload_add_fails_closed_during_m0(self) -> None:
        guarded_paths = [
            ROOT / "config" / "workloads.json",
            ROOT / "config" / "privacy.json",
            ROOT / "config" / "access.json",
        ]
        before = {path: path.read_bytes() for path in guarded_paths}
        result = subprocess.run(
            [str(ROOT / "scripts" / "oreo-workload-add"), "new-legacy-app", "New Legacy App"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("new legacy-rootful workload admission is denied", result.stderr)
        self.assertEqual(before, {path: path.read_bytes() for path in guarded_paths})

    def test_doctor_quarantine_checks_fail_for_missing_and_invalid_records(self) -> None:
        namespace = runpy.run_path(str(ROOT / "scripts" / "oreo-doctor"))
        quarantine_checks = namespace["argus_quarantine_checks"]
        original_load_json = namespace["load_json"]

        fixtures = {
            "workloads.json": {"workloads": [{"id": "one"}, {"id": "two"}]},
            "argus/legacy-classification.json": {
                "workloads": {
                    "one": {
                        "realm": "personal",
                        "zone": "legacy",
                        "stage": "none",
                        "trustDomain": "legacy-rootful",
                        "status": "legacy-unclassified",
                        "admission": "denied",
                    }
                }
            },
            "policy.json": {
                "rules": {
                    "allowNewLegacyRootfulAdmission": True,
                    "requireLegacyUnclassifiedQuarantine": False,
                }
            },
        }
        quarantine_checks.__globals__["load_json"] = lambda name: fixtures[name]
        try:
            checks: list[dict[str, object]] = []
            quarantine_checks(checks)
        finally:
            quarantine_checks.__globals__["load_json"] = original_load_json
        self.assertEqual(4, len(checks))
        self.assertTrue(all(check["ok"] is False for check in checks))


if __name__ == "__main__":
    unittest.main()
