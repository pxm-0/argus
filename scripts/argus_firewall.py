#!/usr/bin/env python3
"""Pure deterministic sandbox firewall policy validation and rendering."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from typing import Any


SLUG = re.compile(r"^[a-z0-9]+(?:[a-z0-9_.-]*[a-z0-9])?$")
POLICY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INTERFACE = re.compile(r"^[a-zA-Z0-9_.-]{1,15}$")
NETWORK_ID = re.compile(r"^[0-9a-f]{12,64}$")
PROTOCOLS = {"tcp", "udp"}
POLICY_KEYS = {
    "id",
    "sourceProject",
    "sourceNetwork",
    "targetProject",
    "targetNetwork",
    "targetService",
    "direction",
    "protocol",
    "destinationPort",
    "owner",
    "reason",
    "expiresAt",
}
NETWORK_KEYS = {"project", "network", "networkId", "interface"}
ENDPOINT_KEYS = {"project", "network", "service", "addresses"}


class FirewallPolicyError(ValueError):
    """Stable fail-closed policy validation error."""


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise FirewallPolicyError(f"{label} fields do not match the reviewed contract")


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise FirewallPolicyError(f"{label} is invalid")
    return value


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise FirewallPolicyError("connectivity policy expiry is invalid") from error
    if parsed.tzinfo is None:
        raise FirewallPolicyError("connectivity policy expiry must include a timezone")
    return parsed.astimezone(timezone.utc)


def _private_ipv4(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise FirewallPolicyError(f"{label} must be private IPv4")
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as error:
        raise FirewallPolicyError(f"{label} must be private IPv4") from error
    if parsed.version != 4 or not parsed.is_private:
        raise FirewallPolicyError(f"{label} must be private IPv4")
    return str(parsed)


def validate_networks(networks: Any) -> list[dict[str, str]]:
    if not isinstance(networks, list):
        raise FirewallPolicyError("runtime network mapping must be a list")
    result: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    ids: set[str] = set()
    interfaces: set[str] = set()
    for raw in networks:
        if not isinstance(raw, dict):
            raise FirewallPolicyError("runtime network mapping entry must be an object")
        _exact_keys(raw, NETWORK_KEYS, "runtime network mapping")
        project = _name(raw["project"], "runtime project")
        network = _name(raw["network"], "runtime network")
        network_id = raw["networkId"]
        interface = raw["interface"]
        if not isinstance(network_id, str) or not NETWORK_ID.fullmatch(network_id):
            raise FirewallPolicyError("runtime network id is invalid")
        if not isinstance(interface, str) or not INTERFACE.fullmatch(interface):
            raise FirewallPolicyError("runtime network interface is invalid")
        identity = (project, network)
        if identity in identities or network_id in ids or interface in interfaces:
            raise FirewallPolicyError("runtime network mapping is duplicated")
        identities.add(identity)
        ids.add(network_id)
        interfaces.add(interface)
        result.append(
            {
                "project": project,
                "network": network,
                "networkId": network_id,
                "interface": interface,
            }
        )
    return sorted(result, key=lambda item: (item["project"], item["network"]))


def validate_endpoints(endpoints: Any) -> list[dict[str, Any]]:
    if not isinstance(endpoints, list):
        raise FirewallPolicyError("runtime endpoint mapping must be a list")
    result: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for raw in endpoints:
        if not isinstance(raw, dict):
            raise FirewallPolicyError("runtime endpoint mapping entry must be an object")
        _exact_keys(raw, ENDPOINT_KEYS, "runtime endpoint mapping")
        project = _name(raw["project"], "endpoint project")
        network = _name(raw["network"], "endpoint network")
        service = _name(raw["service"], "endpoint service")
        identity = (project, network, service)
        if identity in identities:
            raise FirewallPolicyError("runtime endpoint mapping is duplicated")
        identities.add(identity)
        if not isinstance(raw["addresses"], list) or not raw["addresses"]:
            raise FirewallPolicyError("runtime endpoint needs at least one address")
        addresses: list[str] = []
        for address in raw["addresses"]:
            addresses.append(_private_ipv4(address, "runtime endpoint address"))
        if len(addresses) != len(set(addresses)):
            raise FirewallPolicyError("runtime endpoint address is duplicated")
        result.append(
            {
                "project": project,
                "network": network,
                "service": service,
                "addresses": sorted(addresses),
            }
        )
    return sorted(result, key=lambda item: (item["project"], item["network"], item["service"]))


def validate_connectivity(payload: Any, *, now: datetime) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "policies"}:
        raise FirewallPolicyError("connectivity document fields do not match the reviewed contract")
    if isinstance(payload["schemaVersion"], bool) or payload["schemaVersion"] != 1:
        raise FirewallPolicyError("connectivity schema version is unsupported")
    policies = payload["policies"]
    if not isinstance(policies, list):
        raise FirewallPolicyError("connectivity policies must be a list")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    normalized_now = now.astimezone(timezone.utc)
    for raw in policies:
        if not isinstance(raw, dict):
            raise FirewallPolicyError("connectivity policy must be an object")
        _exact_keys(raw, POLICY_KEYS, "connectivity policy")
        policy_id = raw["id"]
        if not isinstance(policy_id, str) or not POLICY_ID.fullmatch(policy_id):
            raise FirewallPolicyError("connectivity policy id is invalid")
        if policy_id in ids:
            raise FirewallPolicyError("connectivity policy id is duplicated")
        ids.add(policy_id)
        source_project = _name(raw["sourceProject"], "source project")
        source_network = _name(raw["sourceNetwork"], "source network")
        target_project = _name(raw["targetProject"], "target project")
        target_network = _name(raw["targetNetwork"], "target network")
        target_service = _name(raw["targetService"], "target service")
        if source_project == target_project:
            raise FirewallPolicyError("connectivity policies are only for cross-project traffic")
        if raw["direction"] != "source-to-target":
            raise FirewallPolicyError("connectivity policy direction is invalid")
        protocol = raw["protocol"]
        raw_port = raw["destinationPort"]
        if not isinstance(protocol, str) or protocol not in PROTOCOLS:
            raise FirewallPolicyError("connectivity policy protocol is invalid")
        if (
            isinstance(raw_port, bool)
            or not isinstance(raw_port, (int, float))
            or (isinstance(raw_port, float) and not raw_port.is_integer())
            or not 1 <= int(raw_port) <= 65535
        ):
            raise FirewallPolicyError("connectivity policy destination port is invalid")
        port = int(raw_port)
        owner = raw["owner"]
        reason = raw["reason"]
        if not isinstance(owner, str) or not owner.strip() or not isinstance(reason, str) or not reason.strip():
            raise FirewallPolicyError("connectivity policy owner and reason are required")
        expires_at = raw["expiresAt"]
        if expires_at is not None:
            if not isinstance(expires_at, str) or _timestamp(expires_at) <= normalized_now:
                raise FirewallPolicyError("connectivity policy is expired")
        result.append(
            {
                "id": policy_id,
                "sourceProject": source_project,
                "sourceNetwork": source_network,
                "targetProject": target_project,
                "targetNetwork": target_network,
                "targetService": target_service,
                "direction": "source-to-target",
                "protocol": protocol,
                "destinationPort": port,
                "owner": owner.strip(),
                "reason": reason.strip(),
                "expiresAt": expires_at,
            }
        )
    return sorted(result, key=lambda item: item["id"])


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def render_firewall(
    domain: str,
    networks: Any,
    *,
    egress: dict[str, dict[str, Any]] | None = None,
    connectivity: list[dict[str, Any]] | None = None,
    endpoints: Any | None = None,
    uplink: str = "tap0",
) -> str:
    """Render one complete nftables policy from validated canonical inputs."""
    domain_name = _name(domain, "sandbox domain")
    if not INTERFACE.fullmatch(uplink):
        raise FirewallPolicyError("uplink interface is invalid")
    resolved_networks = validate_networks(networks)
    resolved_endpoints = validate_endpoints(endpoints or [])
    policies = connectivity or []
    if not isinstance(policies, list):
        raise FirewallPolicyError("connectivity policies must be a list")
    table = domain_name.replace("-", "_")
    by_project: dict[str, list[dict[str, str]]] = {}
    by_identity: dict[tuple[str, str], dict[str, str]] = {}
    for network in resolved_networks:
        by_project.setdefault(network["project"], []).append(network)
        by_identity[(network["project"], network["network"])] = network
    endpoint_index = {
        (item["project"], item["network"], item["service"]): item["addresses"]
        for item in resolved_endpoints
    }
    forward: list[str] = []
    for project in sorted(by_project):
        project_networks = by_project[project]
        for source in project_networks:
            for target in project_networks:
                forward.append(
                    f'    iifname "{source["interface"]}" oifname "{target["interface"]}" accept;\n'
                )
    for policy in sorted(policies, key=lambda item: item["id"]):
        source = by_identity.get((policy["sourceProject"], policy["sourceNetwork"]))
        target = by_identity.get((policy["targetProject"], policy["targetNetwork"]))
        addresses = endpoint_index.get(
            (policy["targetProject"], policy["targetNetwork"], policy["targetService"])
        )
        if source is None or target is None or not addresses:
            raise FirewallPolicyError("connectivity policy references an unresolved identity")
        for address in addresses:
            forward.append(
                f'    iifname "{source["interface"]}" oifname "{target["interface"]}" '
                f'ip daddr {address} {policy["protocol"]} dport {policy["destinationPort"]} '
                "ct state new,established accept;\n"
            )
            forward.append(
                f'    iifname "{target["interface"]}" oifname "{source["interface"]}" '
                f'ip saddr {address} {policy["protocol"]} sport {policy["destinationPort"]} '
                "ct state established,related accept;\n"
            )
    egress_policies = egress or {}
    if not isinstance(egress_policies, dict):
        raise FirewallPolicyError("egress policies must be an object")
    egress_projects: set[str] = set()
    for workload in sorted(egress_policies):
        policy = egress_policies[workload]
        if not isinstance(workload, str) or not isinstance(policy, dict):
            raise FirewallPolicyError("egress policy identity is invalid")
        if set(policy) != {"project", "resolver", "allow", "reason"}:
            raise FirewallPolicyError("egress policy fields do not match the reviewed contract")
        project = _name(policy.get("project"), "egress project")
        if project in egress_projects:
            raise FirewallPolicyError("egress project is duplicated")
        egress_projects.add(project)
        project_networks = by_project.get(project, [])
        if len(project_networks) != 1:
            raise FirewallPolicyError("egress project must resolve to exactly one network")
        interface = project_networks[0]["interface"]
        resolver = _private_ipv4(policy["resolver"], "egress resolver")
        if not isinstance(policy["reason"], str) or not policy["reason"].strip():
            raise FirewallPolicyError("egress reason is required")
        allowances = policy["allow"]
        if not isinstance(allowances, (list, tuple)) or not allowances:
            raise FirewallPolicyError("egress allowance is required")
        forward.extend(
            [
                f'    iifname "{interface}" oifname "{uplink}" ip daddr {resolver} udp dport 53 ct state new,established accept;\n',
                f'    iifname "{interface}" oifname "{uplink}" ip daddr {resolver} tcp dport 53 ct state new,established accept;\n',
            ]
        )
        for allowance in allowances:
            if not isinstance(allowance, (list, tuple)) or len(allowance) != 2:
                raise FirewallPolicyError("egress allowance is invalid")
            protocol, port = allowance
            if (
                not isinstance(protocol, str)
                or protocol not in PROTOCOLS
                or isinstance(port, bool)
                or not isinstance(port, int)
                or not 1 <= port <= 65535
            ):
                raise FirewallPolicyError("egress allowance is invalid")
            forward.append(
                f'    iifname "{interface}" oifname "{uplink}" {protocol} dport {int(port)} ct state new,established accept;\n'
            )
        forward.append(
            f'    iifname "{uplink}" oifname "{interface}" ct state established,related accept;\n'
        )
    nat = f"destroy table inet argus_{table}_nat\n"
    if egress_policies:
        masquerade = "".join(
            f'    iifname "{by_project[_name(egress_policies[name]["project"], "egress project")][0]["interface"]}" '
            f'oifname "{uplink}" masquerade;\n'
            for name in sorted(egress_policies)
        )
        nat += (
            f"table inet argus_{table}_nat {{\n"
            "  chain postrouting {\n"
            "    type nat hook postrouting priority srcnat; policy accept;\n"
            f"{masquerade}"
            "  }\n"
            "}\n"
        )
    return (
        f"destroy table inet argus_{table}\n"
        f"table inet argus_{table} {{\n"
        "  chain input { type filter hook input priority filter; policy drop; iifname \"lo\" accept; }\n"
        "  chain forward {\n"
        "    type filter hook forward priority filter; policy drop;\n"
        f"{''.join(forward)}"
        "  }\n"
        "  chain output { type filter hook output priority filter; policy drop; oifname \"lo\" accept; }\n"
        "}\n"
    ) + nat
