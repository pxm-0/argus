#!/usr/bin/env python3
"""Firewall-only sandbox discovery, planning, verification, and recovery."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from argus_firewall import (
    FirewallPolicyError,
    canonical_digest,
    render_firewall,
    validate_connectivity,
    validate_endpoints,
    validate_networks,
)


DOMAINS = {"personal-sandbox", "work-sandbox"}
BUILTIN_NETWORKS = {"bridge", "host", "none"}
MAX_CONFIG_BYTES = 65536
MAX_RUNTIME_OUTPUT_BYTES = 1048576
MAX_PROJECTS = 64


class FirewallOperationError(RuntimeError):
    """Stable fail-closed orchestration error."""


class DuplicateJsonKey(ValueError):
    pass


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    content = path.read_bytes()
    if len(content) > MAX_CONFIG_BYTES:
        raise FirewallOperationError("configuration exceeds the bounded input limit")
    try:
        return json.loads(content, object_pairs_hook=_duplicates)
    except (DuplicateJsonKey, json.JSONDecodeError, RecursionError, UnicodeError, ValueError) as error:
        raise FirewallOperationError("configuration is not valid bounded JSON") from error


class Runner:
    def run(self, command: list[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=check,
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            raise FirewallOperationError("required runtime command timed out") from error
        except subprocess.CalledProcessError as error:
            raise FirewallOperationError("required runtime command failed") from error

    def text(self, command: list[str]) -> str:
        value = self.run(command).stdout
        if len(value.encode()) > MAX_RUNTIME_OUTPUT_BYTES:
            raise FirewallOperationError("required runtime output exceeds the bounded limit")
        return value.strip()


def _runtime_json(value: str, label: str) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_duplicates)
    except (DuplicateJsonKey, json.JSONDecodeError, RecursionError, UnicodeError, ValueError) as error:
        raise FirewallOperationError(f"{label} is not valid bounded JSON") from error


def _sandbox_specs(root: Path) -> tuple[dict[str, dict[str, Any]], Any]:
    script = root / "scripts" / "argus-m5-workload-cutover"
    loader = importlib.machinery.SourceFileLoader("argus_workload_cutover_policy", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise FirewallOperationError("workload policy module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.SPECS, module.domain_egress


def configured_projects(root: Path, domain: str) -> dict[str, str]:
    payload = load_json(root / "config" / "workloads.json")
    workloads = payload.get("workloads") if isinstance(payload, dict) else None
    if not isinstance(workloads, list):
        raise FirewallOperationError("workload inventory is invalid")
    projects: dict[str, str] = {}
    seen_projects: set[str] = set()
    for workload in workloads:
        if not isinstance(workload, dict):
            raise FirewallOperationError("workload inventory entry is invalid")
        migration = workload.get("migration")
        runtime = workload.get("runtime")
        if (
            workload.get("lifecycle") != "active"
            or not isinstance(migration, dict)
            or migration.get("targetTrustDomain") != domain
        ):
            continue
        if not isinstance(runtime, dict):
            raise FirewallOperationError("sandbox workload runtime identity is missing")
        workload_id = workload.get("id")
        project = runtime.get("composeProject")
        if not isinstance(workload_id, str) or not workload_id or not isinstance(project, str) or not project:
            raise FirewallOperationError("sandbox workload project identity is invalid")
        if workload_id in projects or project in seen_projects:
            raise FirewallOperationError("sandbox workload project identity is duplicated")
        projects[workload_id] = project
        seen_projects.add(project)
    if not projects:
        raise FirewallOperationError("sandbox domain has no configured projects")
    if len(projects) > MAX_PROJECTS:
        raise FirewallOperationError("sandbox domain exceeds the bounded project limit")
    return dict(sorted(projects.items()))


def rootless_child_pid(domain: str, runner: Runner) -> int:
    user = f"argus-{domain}"
    try:
        pwd.getpwnam(user)
    except KeyError as error:
        raise FirewallOperationError("sandbox runtime user is missing") from error
    pids = runner.text(["pgrep", "-u", user, "-x", "dockerd"]).splitlines()
    if len(pids) != 1 or not pids[0].isdigit():
        raise FirewallOperationError("sandbox Docker daemon identity is ambiguous")
    parent = runner.text(["ps", "-o", "ppid=", "-p", pids[0]]).strip()
    if not parent.isdigit():
        raise FirewallOperationError("sandbox RootlessKit namespace is unavailable")
    command_line = Path(f"/proc/{parent}/cmdline").read_bytes().replace(b"\0", b" ")
    expected = f"--state-dir=/var/lib/argus/{domain}/rootlesskit".encode()
    if expected not in command_line:
        raise FirewallOperationError("sandbox RootlessKit namespace identity does not match")
    try:
        child_namespace = os.readlink(f"/proc/{parent}/ns/net")
        host_namespace = os.readlink("/proc/1/ns/net")
    except OSError as error:
        raise FirewallOperationError("sandbox RootlessKit network namespace is unavailable") from error
    if child_namespace == host_namespace:
        raise FirewallOperationError("sandbox RootlessKit child is in the host network namespace")
    return int(parent)


def _docker(domain: str, *arguments: str) -> list[str]:
    return ["docker", "--host", f"unix:///var/lib/argus/{domain}/docker.sock", *arguments]


def discover_runtime(root: Path, domain: str, runner: Runner) -> dict[str, Any]:
    if domain not in DOMAINS:
        raise FirewallOperationError("unsupported sandbox domain")
    expected_projects = configured_projects(root, domain)
    child = rootless_child_pid(domain, runner)
    network_ids = runner.text(_docker(domain, "network", "ls", "-q")).splitlines()
    if not network_ids:
        raise FirewallOperationError("sandbox Docker network inventory is empty")
    raw_networks = _runtime_json(
        runner.text(_docker(domain, "network", "inspect", *network_ids)),
        "Docker network inventory",
    )
    if not isinstance(raw_networks, list):
        raise FirewallOperationError("Docker network inventory must be a list")
    mappings: list[dict[str, str]] = []
    for network in raw_networks:
        if not isinstance(network, dict):
            raise FirewallOperationError("Docker network inventory entry must be an object")
        name = network.get("Name")
        if name in BUILTIN_NETWORKS:
            continue
        if network.get("Driver") != "bridge":
            raise FirewallOperationError("sandbox contains an unsupported custom network")
        labels = network.get("Labels") or {}
        if not isinstance(labels, dict):
            raise FirewallOperationError("custom bridge labels are invalid")
        project = labels.get("com.docker.compose.project")
        logical_network = labels.get("com.docker.compose.network")
        network_id = network.get("Id")
        if not isinstance(project, str) or not isinstance(logical_network, str):
            raise FirewallOperationError("custom bridge lacks canonical Compose identity")
        options = network.get("Options") or {}
        if not isinstance(options, dict):
            raise FirewallOperationError("custom bridge options are invalid")
        interface = options.get("com.docker.network.bridge.name") or f"br-{str(network_id)[:12]}"
        mappings.append(
            {
                "project": project,
                "network": logical_network,
                "networkId": str(network_id),
                "interface": str(interface),
            }
        )
    mappings = validate_networks(mappings)
    configured = set(expected_projects.values())
    observed = {item["project"] for item in mappings}
    if observed != configured:
        raise FirewallOperationError("configured and observed sandbox projects differ")
    raw_links = _runtime_json(
        runner.text(["nsenter", "-t", str(child), "-n", "ip", "-json", "link", "show"]),
        "sandbox interface inventory",
    )
    if not isinstance(raw_links, list):
        raise FirewallOperationError("sandbox interface inventory must be a list")
    link_names = {item.get("ifname") for item in raw_links if isinstance(item, dict)}
    mapped_interfaces = {item["interface"] for item in mappings}
    if not mapped_interfaces <= link_names:
        raise FirewallOperationError("a resolved sandbox bridge is absent from the live namespace")
    managed_links = {
        name
        for name in link_names
        if isinstance(name, str) and (name.startswith("br-") or name.startswith("argus-"))
    }
    if managed_links != mapped_interfaces:
        raise FirewallOperationError("live sandbox contains an unknown managed bridge")

    container_ids = runner.text(_docker(domain, "ps", "-q")).splitlines()
    if not container_ids:
        raise FirewallOperationError("sandbox running container inventory is empty")
    raw_containers = _runtime_json(
        runner.text(_docker(domain, "inspect", *container_ids)),
        "Docker container inventory",
    )
    if not isinstance(raw_containers, list):
        raise FirewallOperationError("Docker container inventory must be a list")
    endpoint_map: dict[tuple[str, str, str], set[str]] = {}
    containers: list[dict[str, Any]] = []
    for container in raw_containers:
        if not isinstance(container, dict):
            raise FirewallOperationError("Docker container inventory entry must be an object")
        config = container.get("Config") or {}
        state = container.get("State") or {}
        network_settings_root = container.get("NetworkSettings") or {}
        if not isinstance(config, dict) or not isinstance(state, dict) or not isinstance(network_settings_root, dict):
            raise FirewallOperationError("running container metadata is invalid")
        labels = config.get("Labels") or {}
        if not isinstance(labels, dict):
            raise FirewallOperationError("running container labels are invalid")
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        if project not in configured or not isinstance(service, str) or not service:
            raise FirewallOperationError("running container lacks configured Compose identity")
        pid = state.get("Pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise FirewallOperationError("running container PID is invalid")
        network_settings = network_settings_root.get("Networks") or {}
        if not isinstance(network_settings, dict) or not network_settings:
            raise FirewallOperationError("running container network identity is missing")
        container_networks: list[str] = []
        for _network_name, attachment in network_settings.items():
            attachment_network_id = attachment.get("NetworkID") if isinstance(attachment, dict) else None
            matching = [
                item
                for item in mappings
                if item["project"] == project and item["networkId"] == attachment_network_id
            ]
            if len(matching) != 1:
                raise FirewallOperationError("container network does not resolve canonically")
            logical_network = matching[0]["network"]
            address = attachment.get("IPAddress") if isinstance(attachment, dict) else None
            if not isinstance(address, str) or not address:
                raise FirewallOperationError("container endpoint address is missing")
            endpoint_map.setdefault((project, logical_network, service), set()).add(address)
            container_networks.append(logical_network)
        containers.append(
            {
                "project": project,
                "service": service,
                "pid": pid,
                "networks": sorted(container_networks),
            }
        )
    endpoints = validate_endpoints(
        [
            {"project": key[0], "network": key[1], "service": key[2], "addresses": sorted(addresses)}
            for key, addresses in endpoint_map.items()
        ]
    )
    return {
        "childPid": child,
        "configuredProjects": expected_projects,
        "networks": mappings,
        "endpoints": endpoints,
        "containers": sorted(containers, key=lambda item: (item["project"], item["service"])),
    }


def declared_egress(root: Path, domain: str) -> dict[str, dict[str, Any]]:
    specs, domain_egress = _sandbox_specs(root)
    result: dict[str, dict[str, Any]] = {}
    for workload, policy in domain_egress(domain).items():
        result[workload] = {
            "project": str(specs[workload]["project"]),
            "resolver": str(policy["resolver"]),
            "allow": tuple((str(protocol), int(port)) for protocol, port in policy["allow"]),
            "reason": str(policy["reason"]),
        }
    return result


def active_connectivity(root: Path, projects: set[str], now: datetime) -> list[dict[str, Any]]:
    policies = validate_connectivity(load_json(root / "config" / "sandbox-connectivity.json"), now=now)
    active: list[dict[str, Any]] = []
    for policy in policies:
        source_in_domain = policy["sourceProject"] in projects
        target_in_domain = policy["targetProject"] in projects
        if source_in_domain != target_in_domain:
            raise FirewallOperationError("cross-domain connectivity policy is forbidden")
        if source_in_domain:
            active.append(policy)
    return active


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def build_plan(root: Path, domain: str, runner: Runner, *, now: datetime | None = None) -> dict[str, Any]:
    observed = discover_runtime(root, domain, runner)
    projects = set(observed["configuredProjects"].values())
    connectivity = active_connectivity(root, projects, now or datetime.now(timezone.utc))
    egress = declared_egress(root, domain)
    rendered = render_firewall(
        domain,
        observed["networks"],
        egress=egress,
        connectivity=connectivity,
        endpoints=observed["endpoints"],
    )
    canonical = {
        "schemaVersion": 1,
        "domain": domain,
        "configuredProjects": observed["configuredProjects"],
        "networks": observed["networks"],
        "endpoints": observed["endpoints"],
        "connectivity": connectivity,
        "egress": egress,
        "renderedDigest": _sha256_text(rendered),
    }
    return {
        **canonical,
        "mappingDigest": canonical_digest(
            {"networks": observed["networks"], "endpoints": observed["endpoints"]}
        ),
        "policyDigest": canonical_digest({"connectivity": connectivity, "egress": egress}),
        "planDigest": canonical_digest(canonical),
        "rendered": rendered,
        "childPid": observed["childPid"],
        "containers": observed["containers"],
    }


def probe_connectivity(root: Path, plan: dict[str, Any], runner: Runner) -> dict[str, Any]:
    """Probe every directed project pair concurrently from existing namespaces."""
    specs, _domain_egress = _sandbox_specs(root)
    domain = str(plan["domain"])
    project_specs = {
        str(spec["project"]): spec
        for spec in specs.values()
        if str(spec["domain"]) == domain
    }
    configured_projects = set(plan["configuredProjects"].values())
    if set(project_specs) != configured_projects:
        raise FirewallOperationError("probe project identities differ from configured inventory")
    containers = plan["containers"]
    endpoints = plan["endpoints"]
    source_pids: dict[str, int] = {}
    source_networks: dict[str, set[str]] = {}
    targets: dict[str, tuple[str, int, str, str]] = {}
    for project in sorted(configured_projects):
        source_matches = [
            item for item in containers if item["project"] == project and item["service"] == "argus-ingress"
        ]
        if len(source_matches) != 1:
            raise FirewallOperationError("project probe source is missing or ambiguous")
        spec = project_specs[project]
        target_service = str(spec["endpoint_service"])
        endpoint_matches = [
            item for item in endpoints if item["project"] == project and item["service"] == target_service
        ]
        if len(endpoint_matches) != 1 or len(endpoint_matches[0]["addresses"]) != 1:
            raise FirewallOperationError("project probe target is missing or ambiguous")
        endpoint = endpoint_matches[0]
        addresses = endpoint["addresses"]
        source_pids[project] = int(source_matches[0]["pid"])
        source_networks[project] = set(source_matches[0]["networks"])
        targets[project] = (
            addresses[0],
            int(spec["endpoint_port"]),
            str(endpoint["network"]),
            target_service,
        )

    def probe(source: str, target: str) -> dict[str, Any]:
        address, port, target_network, target_service = targets[target]
        program = (
            "import socket,sys; "
            f"s=socket.socket(); s.settimeout(1.5); "
            f"rc=s.connect_ex(({address!r},{port})); s.close(); sys.exit(0 if rc == 0 else 1)"
        )
        result = runner.run(
            ["nsenter", "-t", str(source_pids[source]), "-n", "python3", "-c", program],
            check=False,
        )
        reachable = result.returncode == 0
        expected = source == target or any(
            policy["sourceProject"] == source
            and policy["sourceNetwork"] in source_networks[source]
            and policy["targetProject"] == target
            and policy["targetNetwork"] == target_network
            and policy["targetService"] == target_service
            and policy["protocol"] == "tcp"
            and policy["destinationPort"] == port
            for policy in plan["connectivity"]
        )
        return {
            "sourceProject": source,
            "targetProject": target,
            "expectedReachable": expected,
            "reachable": reachable,
            "passed": reachable == expected,
        }

    pairs = [(source, target) for source in sorted(configured_projects) for target in sorted(configured_projects)]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(16, len(pairs))) as executor:
        futures = {executor.submit(probe, source, target): (source, target) for source, target in pairs}
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: (item["sourceProject"], item["targetProject"]))
    failures = [item for item in results if not item["passed"]]
    return {
        "schemaVersion": 1,
        "domain": domain,
        "result": "pass" if not failures else "fail",
        "ownProjectChecks": len(configured_projects),
        "crossProjectChecks": len(pairs) - len(configured_projects),
        "passedChecks": len(results) - len(failures),
        "totalChecks": len(results),
        "unexpectedReachability": sum(
            1 for item in failures if item["reachable"] and not item["expectedReachable"]
        ),
        "unexpectedDenial": sum(
            1 for item in failures if not item["reachable"] and item["expectedReachable"]
        ),
        "checks": results,
    }


def _table_names(domain: str) -> tuple[str, str]:
    suffix = domain.replace("-", "_")
    return f"argus_{suffix}", f"argus_{suffix}_nat"


def normalized_rules(runner: Runner, child: int, domain: str) -> str:
    main, nat = _table_names(domain)
    main_rules = runner.text(["nsenter", "-t", str(child), "-n", "nft", "list", "table", "inet", main])
    nat_result = runner.run(
        ["nsenter", "-t", str(child), "-n", "nft", "list", "table", "inet", nat],
        check=False,
    )
    nat_rules = nat_result.stdout.strip() if nat_result.returncode == 0 else ""
    return main_rules + ("\n" + nat_rules if nat_rules else "")


def rendered_rules(runner: Runner, config: Path, domain: str) -> str:
    main, nat = _table_names(domain)
    command = (
        'nft -f "$1"; nft list table inet "$2"; '
        'nft list table inet "$3" 2>/dev/null || true'
    )
    return runner.text(["unshare", "--net", "sh", "-ceu", command, "sh", str(config), main, nat])


def verify_plan(root: Path, domain: str, runner: Runner) -> dict[str, Any]:
    plan = build_plan(root, domain, runner)
    destination = Path(f"/etc/argus/argus-{domain}.nft")
    persisted = destination.read_text()
    if persisted != plan["rendered"]:
        raise FirewallOperationError("persisted firewall differs from the deterministic plan")
    with tempfile.TemporaryDirectory(prefix="argus-firewall-verify-") as directory:
        candidate = Path(directory) / "candidate.nft"
        candidate.write_text(plan["rendered"])
        expected = rendered_rules(runner, candidate, domain)
    live = normalized_rules(runner, int(plan["childPid"]), domain)
    if live != expected:
        raise FirewallOperationError("live firewall differs from persisted deterministic policy")
    if 'iifname "br-*"' in live or 'oifname "br-*"' in live:
        raise FirewallOperationError("wildcard bridge forwarding remains installed")
    probes = probe_connectivity(root, plan, runner)
    if probes["result"] != "pass":
        raise FirewallOperationError("sandbox connectivity probe matrix failed")
    return {
        "schemaVersion": 1,
        "domain": domain,
        "verified": True,
        "planDigest": plan["planDigest"],
        "mappingDigest": plan["mappingDigest"],
        "policyDigest": plan["policyDigest"],
        "persistedDigest": _sha256_text(persisted),
        "liveRulesDigest": _sha256_text(live),
        "wildcardBridgeRule": False,
        "connectivityProbes": {
            key: value for key, value in probes.items() if key != "checks"
        },
    }


def _safe_backup(path: Path) -> None:
    metadata = os.lstat(path)
    if metadata.st_uid != 0 or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise FirewallOperationError("firewall backup ownership or mode is unsafe")


def apply_plan(root: Path, domain: str, expected_digest: str, runner: Runner) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise FirewallOperationError("firewall apply requires root")
    plan = build_plan(root, domain, runner)
    if expected_digest != plan["planDigest"]:
        raise FirewallOperationError("firewall plan digest is stale or mismatched")
    destination = Path(f"/etc/argus/argus-{domain}.nft")
    metadata = os.lstat(destination)
    if metadata.st_uid != 0 or not stat.S_ISREG(metadata.st_mode) or destination.is_symlink():
        raise FirewallOperationError("persisted firewall ownership is unsafe")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = Path("/var/lib/argus/firewall-remediation") / domain / stamp
    backup_dir.mkdir(parents=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    backup = backup_dir / destination.name
    shutil.copy2(destination, backup)
    os.chown(backup, 0, 0)
    os.chmod(backup, 0o600)
    _safe_backup(backup)
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=f".{destination.name}.",
        dir=destination.parent,
        delete=False,
    ) as handle:
        handle.write(plan["rendered"])
        handle.flush()
        os.fsync(handle.fileno())
        candidate: Path | None = Path(handle.name)
    try:
        assert candidate is not None
        os.chown(candidate, 0, 0)
        os.chmod(candidate, 0o644)
        runner.run(["nsenter", "-t", str(plan["childPid"]), "-n", "nft", "-c", "-f", str(candidate)])
        rules_before = normalized_rules(runner, int(plan["childPid"]), domain)
        runner.run(["nsenter", "-t", str(plan["childPid"]), "-n", "nft", "-f", str(candidate)])
        try:
            os.replace(candidate, destination)
            candidate = None
            verification = verify_plan(root, domain, runner)
        except BaseException:
            shutil.copyfile(backup, destination)
            os.chown(destination, 0, 0)
            os.chmod(destination, 0o644)
            runner.run(["nsenter", "-t", str(plan["childPid"]), "-n", "nft", "-f", str(backup)])
            if normalized_rules(runner, int(plan["childPid"]), domain) != rules_before:
                raise FirewallOperationError("automatic firewall restore did not match pre-apply rules")
            raise
    finally:
        if candidate is not None and candidate.exists():
            candidate.unlink()
    return {**verification, "applied": True, "backup": str(backup)}


def rollback(root: Path, domain: str, backup: Path, runner: Runner) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise FirewallOperationError("firewall rollback requires root")
    resolved_backup = backup.resolve(strict=True)
    approved_root = (Path("/var/lib/argus/firewall-remediation") / domain).resolve()
    if approved_root not in resolved_backup.parents:
        raise FirewallOperationError("firewall backup path is outside the approved root")
    _safe_backup(resolved_backup)
    child = rootless_child_pid(domain, runner)
    runner.run(["nsenter", "-t", str(child), "-n", "nft", "-c", "-f", str(resolved_backup)])
    destination = Path(f"/etc/argus/argus-{domain}.nft")
    destination_metadata = os.lstat(destination)
    if (
        destination_metadata.st_uid != 0
        or not stat.S_ISREG(destination_metadata.st_mode)
        or destination.is_symlink()
    ):
        raise FirewallOperationError("persisted firewall ownership is unsafe")
    current = destination.read_bytes()
    with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", dir=destination.parent, delete=False) as handle:
        candidate: Path | None = Path(handle.name)
    try:
        assert candidate is not None
        shutil.copyfile(resolved_backup, candidate)
        os.chown(candidate, 0, 0)
        os.chmod(candidate, 0o644)
        runner.run(["nsenter", "-t", str(child), "-n", "nft", "-f", str(candidate)])
        try:
            os.replace(candidate, destination)
            candidate = None
        except BaseException:
            with tempfile.NamedTemporaryFile(prefix="argus-firewall-current-", delete=False) as restore_handle:
                restore_handle.write(current)
                restore_path = Path(restore_handle.name)
            try:
                runner.run(["nsenter", "-t", str(child), "-n", "nft", "-f", str(restore_path)])
            finally:
                restore_path.unlink(missing_ok=True)
            raise
    finally:
        if candidate is not None and candidate.exists():
            candidate.unlink()
    if destination.read_bytes() != resolved_backup.read_bytes():
        raise FirewallOperationError("firewall rollback persisted digest does not match")
    expected = rendered_rules(runner, resolved_backup, domain)
    live = normalized_rules(runner, child, domain)
    if live != expected:
        raise FirewallOperationError("firewall rollback live rules do not match the backup")
    return {
        "schemaVersion": 1,
        "domain": domain,
        "rolledBack": True,
        "backup": str(resolved_backup),
        "persistedDigest": "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest(),
        "liveRulesDigest": _sha256_text(live),
    }
