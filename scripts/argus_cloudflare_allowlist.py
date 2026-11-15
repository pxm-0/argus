"""Cloudflare public-route allowlist (D027): pure checks shared by policy, doctor, reconcile, smoke and activation.

Every helper fails closed: a malformed allowlist, ingress or evidence file allows nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CATCH_ALL_SERVICE = "http_status:404"
STATE_MODES = {"cloudflare-protected": "protected", "cloudflare-public": "public"}
ROLLED_BACK = "rolledBack"
HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


class AllowlistError(ValueError):
    """The exposure config does not hold a well-formed publicAllowlist."""


def cloudflare_provider(exposure: dict[str, Any]) -> dict[str, Any]:
    provider = exposure.get("providers", {}).get("cloudflare", {})
    return provider if isinstance(provider, dict) else {}


def public_allowlist(exposure: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Return {workloadId: hostnames}; raise AllowlistError on any malformed entry."""
    raw = cloudflare_provider(exposure).get("publicAllowlist", [])
    if not isinstance(raw, list):
        raise AllowlistError("publicAllowlist must be a list")
    result: dict[str, tuple[str, ...]] = {}
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {"workloadId", "hostnames"}:
            raise AllowlistError("each publicAllowlist entry must hold exactly workloadId and hostnames")
        workload_id = entry["workloadId"]
        hostnames = entry["hostnames"]
        if not isinstance(workload_id, str) or not workload_id or workload_id in result:
            raise AllowlistError("publicAllowlist workloadId must be a unique non-empty string")
        if not isinstance(hostnames, list) or not hostnames:
            raise AllowlistError(f"publicAllowlist hostnames for {workload_id} must be a non-empty list")
        if len(set(map(str, hostnames))) != len(hostnames):
            raise AllowlistError(f"publicAllowlist hostnames for {workload_id} must be unique")
        for hostname in hostnames:
            if not isinstance(hostname, str) or not HOSTNAME_PATTERN.match(hostname) or hostname.endswith(".invalid"):
                raise AllowlistError(f"publicAllowlist hostname for {workload_id} is not an exact lowercase DNS name")
        result[workload_id] = tuple(hostnames)
    return result


def safe_allowlist(exposure: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    try:
        return public_allowlist(exposure)
    except AllowlistError:
        return {}


def allowlisted_hostnames(exposure: dict[str, Any]) -> frozenset[str]:
    return frozenset(host for hosts in safe_allowlist(exposure).values() for host in hosts)


def is_allowlisted(exposure: dict[str, Any], workload_id: str, hostname: str) -> bool:
    return bool(hostname) and hostname in safe_allowlist(exposure).get(workload_id, ())


def provider_ready(exposure: dict[str, Any]) -> bool:
    provider = cloudflare_provider(exposure)
    return (
        provider.get("enabled") is True
        and provider.get("provisioned") is True
        and provider.get("allowNamedTunnels") is True
        and provider.get("allowQuickTunnels") is False
    )


class IngressError(ValueError):
    """The cloudflared ingress is not the flat shape Argus can verify."""


RULE_KEYS = frozenset({"hostname", "service", "path"})


def parse_ingress(text: str) -> list[dict[str, str]]:
    """Parse the flat `ingress:` list that Argus writes and cloudflared reads.

    Fails closed (IngressError) on nested blocks, unknown or repeated keys: a nested
    `hostname:` under e.g. originRequest must never be mistaken for the rule's hostname.
    shortcut: only flat `- key: value` rules are readable; use a YAML parser if hand-written
    configs with originRequest blocks must be supported.
    """
    rules: list[dict[str, str]] = []
    in_ingress = False
    key_indent = -1
    for raw_line in text.splitlines():
        line = raw_line.split(" #", 1)[0].rstrip() if not raw_line.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "-")):
            in_ingress = line.strip() == "ingress:"
            continue
        if not in_ingress:
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith("- "):
            rules.append({})
            key_indent = indent + 2
            stripped = stripped[2:].strip()
        elif not rules or indent != key_indent:
            raise IngressError(f"ingress line is not a flat rule key: {stripped}")
        key, sep, value = stripped.partition(":")
        key = key.strip()
        if not sep or key not in RULE_KEYS or key in rules[-1]:
            raise IngressError(f"ingress rule key is unknown, repeated or nested: {key}")
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            try:
                value = str(json.loads(value))
            except json.JSONDecodeError:
                pass
        rules[-1] = {**rules[-1], key: value}
    return rules


def ingress_problems(
    text: str,
    exposure: dict[str, Any],
    host_to_workload: dict[str, str] | None = None,
) -> list[str]:
    """List reasons an ingress config would publish more than the allowlist.

    With host_to_workload, each hostname must be allowlisted for the workload whose route
    names it; without it, each hostname must be allowlisted for some workload.
    """
    try:
        rules = parse_ingress(text)
    except IngressError as exc:
        return [str(exc)]
    problems: list[str] = []
    last = rules[-1] if rules else {}
    if "hostname" in last or last.get("service") != CATCH_ALL_SERVICE:
        problems.append(f"ingress does not end in an {CATCH_ALL_SERVICE} catch-all")
    allowlist = safe_allowlist(exposure)
    every_host = allowlisted_hostnames(exposure)
    for rule in rules[:-1]:
        hostname = rule.get("hostname", "")
        if not hostname:
            problems.append("ingress has a rule without a hostname before the catch-all")
            continue
        if host_to_workload is None:
            if hostname not in every_host:
                problems.append(f"ingress hostname is not allowlisted: {hostname}")
            continue
        workload_id = host_to_workload.get(hostname, "")
        if hostname not in allowlist.get(workload_id, ()):
            problems.append(f"ingress hostname is not allowlisted for its workload: {hostname}")
    return problems


def load_evidence(evidence_dir: Path) -> list[dict[str, Any]]:
    if not evidence_dir.is_dir():
        return []
    payloads: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue  # unreadable evidence is not evidence; callers then fail closed
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def probe_passes(mode: str, probe: Any) -> bool:
    """protected: Cloudflare Access itself refused the request; public: the origin answered 200."""
    if not isinstance(probe, dict):
        return False
    if mode == "protected":
        return probe.get("accessBlocked") is True
    return mode == "public" and probe.get("status") == 200


def _rollback_cutoff(evidence: list[dict[str, Any]], workload_id: str) -> str:
    stamps = [
        str(payload.get("recordedAt", ""))
        for payload in evidence
        if payload.get("workloadId") == workload_id and payload.get("mode") == ROLLED_BACK
    ]
    return max(stamps, default="")


def has_stage_evidence(evidence: list[dict[str, Any]], workload_id: str, mode: str, hostname: str = "") -> bool:
    """True when a successful `mode` activation was recorded for the workload (and hostname) after its last rollback."""
    cutoff = _rollback_cutoff(evidence, workload_id)
    for payload in evidence:
        probes = payload.get("unauthenticatedProbes")
        validation = payload.get("validation")
        hostnames = payload.get("hostnames")
        recorded = payload.get("recordedAt")
        if not isinstance(probes, dict) or not isinstance(validation, dict) or not isinstance(hostnames, list):
            continue
        if (
            payload.get("ok") is not True
            or payload.get("workloadId") != workload_id
            or payload.get("mode") != mode
            or validation.get("ok") is not True
            or not isinstance(recorded, str)
            or recorded <= cutoff
            or not hostnames
            or (hostname and hostname not in hostnames)
            or set(probes) != set(hostnames)
            or not all(probe_passes(mode, probe) for probe in probes.values())
        ):
            continue
        if mode == "protected" and payload.get("authenticatedConfirmed") is not True:
            continue
        return True
    return False


def effective_blockers(
    exposure: dict[str, Any],
    workload_id: str,
    hostname: str,
    state: str,
    evidence: list[dict[str, Any]],
) -> list[str]:
    """Reasons a Cloudflare access state may not be effective; empty means it may."""
    mode = STATE_MODES.get(state)
    if mode is None:
        return [f"not a Cloudflare access state: {state}"]
    blockers: list[str] = []
    if not is_allowlisted(exposure, workload_id, hostname):
        blockers.append("workload and hostname are not in cloudflare.publicAllowlist")
    if not provider_ready(exposure):
        blockers.append("Cloudflare provider is not enabled, provisioned and limited to named tunnels")
    if not has_stage_evidence(evidence, workload_id, "protected", hostname):
        blockers.append("no recorded protected-stage activation evidence")
    if mode == "public" and not has_stage_evidence(evidence, workload_id, "public", hostname):
        blockers.append("no recorded public-stage activation evidence")
    return blockers
