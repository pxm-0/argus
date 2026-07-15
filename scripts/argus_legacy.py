#!/usr/bin/env python3
"""Secret-safe, read-only inventory helpers for the Argus M0 quarantine."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from oreo_common import load_json, now, root


LEGACY_CLASSIFICATION = {
    "realm": "unclassified",
    "zone": "legacy",
    "stage": "none",
    "trustDomain": "legacy-rootful",
    "status": "legacy-unclassified",
}
PROHIBITED_MOUNT_DESTINATIONS = {
    "/root/.ssh": "operator-identity",
    "/home/oreo/.ssh": "operator-identity",
    "/var/run/docker.sock": "runtime-control",
    "/run/docker.sock": "runtime-control",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


class CommandRunner:
    """Runs fixed, read-only commands without invoking a shell."""

    def run(self, command: Sequence[str]) -> CommandResult:
        if not command or not shutil.which(command[0]):
            return CommandResult(127, "", "command-not-found")
        result = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)


def opaque_ref(value: str) -> str:
    """Return a stable correlation token without exposing a host path."""

    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return f"sha256:{digest[:16]}"


def address_scope(address: str) -> str:
    candidate = address.strip().strip("[]")
    if candidate in {"*", "0.0.0.0", "::"}:
        return "wildcard"
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return "named"
    if parsed.is_loopback:
        return "loopback"
    if parsed.is_link_local:
        return "link-local"
    if parsed.is_private:
        return "private"
    return "public"


def split_endpoint(value: str) -> tuple[str, str]:
    endpoint = value.strip()
    if endpoint.startswith("[") and "]:" in endpoint:
        address, port = endpoint[1:].rsplit("]:", 1)
        return address, port
    if ":" not in endpoint:
        return endpoint, ""
    return endpoint.rsplit(":", 1)


def parse_ss_listeners(output: str) -> list[dict[str, Any]]:
    listeners: list[dict[str, Any]] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        protocol = fields[0].lower()
        local = fields[4]
        address, port = split_endpoint(local)
        listeners.append(
            {
                "protocol": protocol,
                "port": port,
                "addressScope": address_scope(address),
            }
        )
    return sorted(listeners, key=lambda item: (item["protocol"], str(item["port"]), item["addressScope"]))


def mount_finding(source: str, destination: str) -> str | None:
    if source.endswith("/docker.sock") or destination.endswith("/docker.sock"):
        return "runtime-control"
    if source.endswith("/.ssh") or destination.endswith("/.ssh"):
        return "operator-identity"
    if destination in {"/", "/proc", "/sys"}:
        return "host-capability"
    return PROHIBITED_MOUNT_DESTINATIONS.get(destination)


def normalize_mount(mount: dict[str, Any]) -> dict[str, Any]:
    mount_type = str(mount.get("Type", "unknown"))
    destination = str(mount.get("Destination", ""))
    source = str(mount.get("Source", ""))
    finding = mount_finding(source, destination)
    return {
        "type": mount_type,
        "sourceRef": opaque_ref(source) if source else "",
        "destination": destination,
        "readOnly": not bool(mount.get("RW", False)),
        "propagation": str(mount.get("Propagation", "")),
        "blockingFinding": finding,
    }


def normalize_port(binding: dict[str, Any]) -> dict[str, Any]:
    host_ip = str(binding.get("HostIp", binding.get("IP", "")))
    return {
        "privatePort": int(binding.get("PrivatePort", 0) or 0),
        "publicPort": int(binding.get("HostPort", binding.get("PublicPort", 0)) or 0),
        "protocol": str(binding.get("Type", "")),
        "addressScope": address_scope(host_ip),
        "blockingFinding": "wildcard-listener" if address_scope(host_ip) == "wildcard" else None,
    }


def _json_command(runner: CommandRunner, command: Sequence[str]) -> Any:
    result = runner.run(command)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def docker_containers(runner: CommandRunner) -> tuple[list[dict[str, Any]], list[str]]:
    result = runner.run(["docker", "ps", "--no-trunc", "--format", "{{.ID}}"])
    if result.returncode != 0:
        return [], ["docker-container-inventory-unavailable"]
    identifiers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not identifiers:
        return [], []
    payload = _json_command(runner, ["docker", "inspect", *identifiers])
    if not isinstance(payload, list):
        return [], ["docker-container-inspect-unavailable"]

    containers: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        config = item.get("Config", {}) if isinstance(item.get("Config"), dict) else {}
        labels = config.get("Labels", {}) if isinstance(config.get("Labels"), dict) else {}
        network_settings = item.get("NetworkSettings", {}) if isinstance(item.get("NetworkSettings"), dict) else {}
        host_config = item.get("HostConfig", {}) if isinstance(item.get("HostConfig"), dict) else {}
        networks = network_settings.get("Networks", {}) if isinstance(network_settings.get("Networks"), dict) else {}
        ports: list[dict[str, Any]] = []
        for container_port, bindings in (network_settings.get("Ports", {}) or {}).items():
            private_port, _, protocol = str(container_port).partition("/")
            for binding in bindings or []:
                if isinstance(binding, dict):
                    ports.append(
                        normalize_port(
                            {
                                **binding,
                                "PrivatePort": int(private_port or 0),
                                "Type": protocol,
                            }
                        )
                    )
        mounts = [normalize_mount(mount) for mount in item.get("Mounts", []) if isinstance(mount, dict)]
        host_capabilities = {
            "privileged": bool(host_config.get("Privileged", False)),
            "hostNetwork": host_config.get("NetworkMode") == "host",
            "hostPid": host_config.get("PidMode") == "host",
            "addedCapabilities": bool(host_config.get("CapAdd")),
            "hostDevices": bool(host_config.get("Devices")),
        }
        capability_findings = {
            name
            for name, present in {
                "privileged-container": host_capabilities["privileged"],
                "host-network": host_capabilities["hostNetwork"],
                "host-pid": host_capabilities["hostPid"],
                "added-capabilities": host_capabilities["addedCapabilities"],
                "host-device": host_capabilities["hostDevices"],
            }.items()
            if present
        }
        findings = sorted(
            {
                str(entry["blockingFinding"])
                for entry in [*mounts, *ports]
                if entry.get("blockingFinding")
            }
            | capability_findings
        )
        containers.append(
            {
                "containerRef": opaque_ref(str(item.get("Id", ""))),
                "name": str(item.get("Name", "")).lstrip("/"),
                "image": str(config.get("Image", "")),
                "composeProject": str(labels.get("com.docker.compose.project", "")),
                "composeService": str(labels.get("com.docker.compose.service", "")),
                "networks": sorted(str(name) for name in networks),
                "mounts": mounts,
                "publishedPorts": sorted(ports, key=lambda entry: (entry["publicPort"], entry["privatePort"])),
                "hostCapabilities": host_capabilities,
                "blockingFindings": findings,
                "classification": dict(LEGACY_CLASSIFICATION),
            }
        )
    return sorted(containers, key=lambda entry: entry["name"]), []


def docker_named_resources(runner: CommandRunner, kind: str) -> tuple[list[dict[str, str]], list[str]]:
    if kind not in {"network", "volume"}:
        raise ValueError(f"unsupported Docker resource kind: {kind}")
    result = runner.run(["docker", kind, "ls", "--format", "{{.Name}}"])
    if result.returncode != 0:
        return [], [f"docker-{kind}-inventory-unavailable"]
    resources = [
        {"name": name, "trustDomain": "legacy-rootful", "status": "legacy-unclassified"}
        for name in sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
    ]
    return resources, []


def listener_inventory(runner: CommandRunner) -> tuple[list[dict[str, Any]], list[str]]:
    result = runner.run(["ss", "-H", "-lntu"])
    if result.returncode != 0:
        return [], ["listener-inventory-unavailable"]
    return parse_ss_listeners(result.stdout), []


def firewall_inventory(runner: CommandRunner) -> tuple[dict[str, Any], list[str]]:
    nft = runner.run(["nft", "--json", "list", "ruleset"])
    if nft.returncode == 0:
        try:
            payload = json.loads(nft.stdout)
        except json.JSONDecodeError:
            return {"backend": "nftables", "verified": False}, ["nftables-output-invalid"]
        entries = payload.get("nftables", []) if isinstance(payload, dict) else []
        chains = [entry.get("chain", {}) for entry in entries if isinstance(entry, dict) and "chain" in entry]
        policies = sorted(
            {
                str(chain.get("policy"))
                for chain in chains
                if isinstance(chain, dict) and chain.get("policy") is not None
            }
        )
        hooks = sorted(
            {
                str(chain.get("hook"))
                for chain in chains
                if isinstance(chain, dict) and chain.get("hook") is not None
            }
        )
        evidence = {
            "backend": "nftables",
            "verified": True,
            "privileged": os.geteuid() == 0,
            "chainCount": len(chains),
            "hooks": hooks,
            "policies": policies,
        }
        gaps = [] if evidence["privileged"] else ["firewall-inventory-not-privileged"]
        return evidence, gaps

    iptables = runner.run(["iptables-save"])
    if iptables.returncode == 0:
        chains = [line for line in iptables.stdout.splitlines() if line.startswith(":")]
        policies = sorted({line.split()[1] for line in chains if len(line.split()) > 1})
        evidence = {
            "backend": "iptables",
            "verified": True,
            "privileged": os.geteuid() == 0,
            "chainCount": len(chains),
            "policies": policies,
        }
        gaps = [] if evidence["privileged"] else ["firewall-inventory-not-privileged"]
        return evidence, gaps

    return {"backend": "unknown", "verified": False, "privileged": os.geteuid() == 0}, [
        "firewall-inventory-unavailable"
    ]


def configured_routes() -> list[dict[str, Any]]:
    routes = load_json("routes.json")
    items: list[dict[str, Any]] = []
    for workload_id, route in routes.get("workloadRoutes", {}).items():
        if not isinstance(route, dict):
            continue
        items.append(
            {
                "workloadId": str(workload_id),
                "localConfigured": bool(route.get("local")),
                "tailnetMode": str((route.get("tailnet") or {}).get("mode", "")),
                "tailnetConfigured": bool((route.get("tailnet") or {}).get("url")),
                "cloudflareConfigured": bool((route.get("cloudflare") or {}).get("hostname")),
                "classification": dict(LEGACY_CLASSIFICATION),
            }
        )
    return sorted(items, key=lambda entry: entry["workloadId"])


def tracked_legacy_workloads() -> list[dict[str, Any]]:
    baseline = load_json("argus/legacy-classification.json")
    workloads = baseline.get("workloads", {})
    return [
        {"workloadId": workload_id, **classification}
        for workload_id, classification in sorted(workloads.items())
        if isinstance(classification, dict)
    ]


def collect_inventory(runner: CommandRunner | None = None) -> dict[str, Any]:
    command_runner = runner or CommandRunner()
    containers, container_gaps = docker_containers(command_runner)
    networks, network_gaps = docker_named_resources(command_runner, "network")
    volumes, volume_gaps = docker_named_resources(command_runner, "volume")
    listeners, listener_gaps = listener_inventory(command_runner)
    firewall, firewall_gaps = firewall_inventory(command_runner)
    evidence_gaps = sorted({*container_gaps, *network_gaps, *volume_gaps, *listener_gaps, *firewall_gaps})
    blocking_findings = sorted(
        {
            finding
            for container in containers
            for finding in container.get("blockingFindings", [])
        }
    )
    return {
        "schemaVersion": 1,
        "capturedAt": now(),
        "hostRef": opaque_ref(socket.gethostname()),
        "readOnly": True,
        "complete": not evidence_gaps,
        "classification": dict(LEGACY_CLASSIFICATION),
        "trackedWorkloads": tracked_legacy_workloads(),
        "containers": containers,
        "networks": networks,
        "volumes": volumes,
        "listeners": listeners,
        "routes": configured_routes(),
        "firewall": firewall,
        "blockingFindings": blocking_findings,
        "evidenceGaps": evidence_gaps,
    }


def write_inventory(payload: dict[str, Any], destination: Path | None = None) -> Path:
    path = destination or root() / "runtime" / "argus" / "legacy-inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
