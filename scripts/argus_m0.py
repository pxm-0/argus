#!/usr/bin/env python3
"""Typed private planning, evidence, and isolation helpers for Argus M0."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from argus_legacy import CommandRunner, canonical_digest, now, opaque_ref, root, write_inventory


ACTION_BY_CATEGORY = {
    "wildcard-listener": "rebind-loopback",
    "runtime-control": "remove-runtime-control-mount",
    "operator-identity": "remove-operator-identity-mount",
    "host-capability": "remove-host-capability",
    "privileged-container": "remove-privileged-mode",
    "host-network": "remove-host-network",
    "host-pid": "remove-host-pid",
    "added-capabilities": "remove-added-capabilities",
    "host-device": "remove-host-device",
    "untracked-runtime-resource": "classify-or-contain-resource",
    "health-unhealthy": "restore-or-contain-workload",
    "funnel-enabled": "disable-funnel",
}
PROBE_PROGRAM = (
    "import socket,sys; s=socket.socket(); s.settimeout(2); "
    "s.connect((sys.argv[1], int(sys.argv[2]))); sys.exit(0)"
)


def private_path(*parts: str) -> Path:
    return root() / "runtime" / "argus" / Path(*parts)


def load_private_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"missing private evidence: {path}") from None
    except json.JSONDecodeError:
        raise SystemExit(f"invalid private evidence: {path}") from None
    if not isinstance(value, dict):
        raise SystemExit(f"private evidence must be an object: {path}")
    return value


def remediation_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    digest = str(inventory.get("evidenceDigest", ""))
    if not digest:
        raise ValueError("inventory has no evidence digest")
    docker_forwarded = docker_forwarded_wildcard_findings(inventory)
    actions = []
    for finding in inventory.get("findings", []):
        if not isinstance(finding, dict):
            continue
        category = str(finding.get("category", ""))
        finding_id = str(finding.get("id", ""))
        if category == "wildcard-listener" and finding_id in docker_forwarded:
            action = "contain-docker-forwarded-ingress"
            requires = ["pre-health", "dual-stack-firewall-enforcement", "post-health", "rollback"]
        elif category == "wildcard-listener":
            action = "review-host-listener"
            requires = ["pre-health", "reviewed-containment-or-removal", "post-health", "rollback"]
        else:
            action = ACTION_BY_CATEGORY.get(category, "investigate-and-contain")
            requires = ["pre-health", "rollback", "post-health", "isolation-check"]
        actions.append(
            {
                "id": opaque_ref(f"{digest}|{finding_id}|{action}"),
                "findingId": finding_id,
                "action": action,
                "approval": "pending",
                "state": "planned",
                "requires": requires,
            }
        )
    payload = {
        "schemaVersion": 1,
        "createdAt": now(),
        "sourceRevision": inventory.get("sourceRevision", "unknown"),
        "inventoryDigest": digest,
        "actions": actions,
    }
    payload["planDigest"] = canonical_digest(payload)
    return payload


def docker_forwarded_wildcard_findings(inventory: dict[str, Any]) -> set[str]:
    """Return listener findings backed by a wildcard-published Docker port."""
    resources = {
        opaque_ref(f"{port.get('protocol')}:{port.get('publicPort')}")
        for container in inventory.get("containers", [])
        if isinstance(container, dict)
        for port in container.get("publishedPorts", [])
        if isinstance(port, dict)
        and port.get("addressScope") == "wildcard"
        and port.get("protocol") in {"tcp", "udp"}
        and isinstance(port.get("publicPort"), int)
        and port["publicPort"] > 0
    }
    container_refs = {
        str(container.get("containerRef", ""))
        for container in inventory.get("containers", [])
        if isinstance(container, dict)
        and any(
            isinstance(port, dict)
            and port.get("addressScope") == "wildcard"
            and port.get("protocol") in {"tcp", "udp"}
            and isinstance(port.get("publicPort"), int)
            and port["publicPort"] > 0
            for port in container.get("publishedPorts", [])
        )
    }
    return {
        str(finding.get("id", ""))
        for finding in inventory.get("findings", [])
        if isinstance(finding, dict)
        and finding.get("category") == "wildcard-listener"
        and finding.get("resourceRef") in resources | container_refs
    }


def record_docker_lockdown_containment(
    plan: dict[str, Any], inventory: dict[str, Any], verification: dict[str, bool],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Approve and record only Docker wildcard findings covered by the reviewed guard."""
    if plan.get("inventoryDigest") != inventory.get("evidenceDigest"):
        raise ValueError("stale remediation plan: inventory digest changed")
    required = {"unitEnabled", "unitActive", "ipv4Guard", "ipv6Guard", "healthPassing"}
    if set(verification) != required or not all(verification.values()):
        raise ValueError("dual-stack lockdown verification is incomplete")
    affected = [
        action for action in plan.get("actions", [])
        if isinstance(action, dict) and action.get("action") == "contain-docker-forwarded-ingress"
    ]
    if not affected:
        raise ValueError("no Docker wildcard findings are eligible for lockdown containment")
    approval = canonical_digest(
        {"inventoryDigest": inventory.get("evidenceDigest"), "verification": verification, "findingIds": sorted(str(item["findingId"]) for item in affected)}
    )
    for action in affected:
        action["approval"] = "approved"
        action["approvalDigest"] = approval
        action["approvedAt"] = now()
        action["state"] = "contained"
    plan["planDigest"] = canonical_digest({key: value for key, value in plan.items() if key != "planDigest"})
    record = {
        "schemaVersion": 1,
        "recordedAt": now(),
        "scope": "docker-forwarded-ingress",
        "inventoryDigest": inventory.get("evidenceDigest"),
        "planDigest": plan["planDigest"],
        "sourceRevision": inventory.get("sourceRevision"),
        "verification": verification,
        "affectedFindingIds": sorted(str(item["findingId"]) for item in affected),
        "remainingHostListenerFindingCount": sum(
            1 for action in plan.get("actions", [])
            if isinstance(action, dict) and action.get("action") == "review-host-listener"
        ),
    }
    record["evidenceDigest"] = canonical_digest(record)
    return plan, record


def approve_host_ingress_exceptions(
    plan: dict[str, Any], inventory: dict[str, Any], review: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record the explicit M0 exception for remote SSH and tailnet transport only."""
    if plan.get("inventoryDigest") != inventory.get("evidenceDigest") or review.get("inventoryDigest") != inventory.get("evidenceDigest"):
        raise ValueError("stale remediation plan or host listener review")
    if inventory.get("routes", {}).get("tailscaleFunnel", {}).get("enabled"):
        raise ValueError("refusing host ingress approval while Tailscale Funnel is enabled")
    if review.get("processClassCounts") != {"sshd": 1, "tailscaled": 1} or len(review.get("cards", [])) != 2:
        raise ValueError("host ingress approval requires exactly one sshd and one tailscaled listener review card")
    review_ids = {str(card.get("findingId", "")) for card in review["cards"] if isinstance(card, dict)}
    actions = [
        action for action in plan.get("actions", [])
        if isinstance(action, dict) and action.get("findingId") in review_ids and action.get("action") == "review-host-listener"
    ]
    if len(actions) != 2 or {str(action.get("findingId", "")) for action in actions} != review_ids:
        raise ValueError("host listener review and remediation plan do not match")
    if not all(bool(item.get("ok")) for item in inventory.get("health", [])):
        raise ValueError("host ingress approval requires passing workload health")
    approval = canonical_digest(
        {"inventoryDigest": inventory.get("evidenceDigest"), "reviewDigest": review.get("reviewDigest"), "exception": "remote-ssh-and-tailnet-transport"}
    )
    for action in actions:
        action["approval"] = "approved"
        action["approvalDigest"] = approval
        action["approvedAt"] = now()
        action["state"] = "explicitly-approved-host-ingress"
    plan["planDigest"] = canonical_digest({key: value for key, value in plan.items() if key != "planDigest"})
    record = {
        "schemaVersion": 1,
        "recordedAt": now(),
        "scope": "host-ingress-exceptions",
        "inventoryDigest": inventory.get("evidenceDigest"),
        "planDigest": plan["planDigest"],
        "reviewDigest": review.get("reviewDigest"),
        "sourceRevision": inventory.get("sourceRevision"),
        "approvedFindingIds": sorted(review_ids),
        "approvedServices": ["remote-ssh", "tailnet-transport"],
        "tailscaleFunnelEnabled": False,
        "healthPassing": True,
    }
    record["evidenceDigest"] = canonical_digest(record)
    return plan, record


def host_listener_review(
    inventory: dict[str, Any], ss_output: str, *, ownership_output: str | None = None, inode_processes: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Resolve non-Docker wildcard findings to safe process-class labels privately."""
    docker_findings = docker_forwarded_wildcard_findings(inventory)
    targets = {
        str(finding.get("id", "")): str(finding.get("resourceRef", ""))
        for finding in inventory.get("findings", [])
        if isinstance(finding, dict)
        and finding.get("category") == "wildcard-listener"
        and str(finding.get("id", "")) not in docker_findings
    }
    listener_rows = _wildcard_listener_rows(ss_output)
    ownership_rows = _wildcard_listener_rows(ownership_output if ownership_output is not None else ss_output)
    if ownership_output is not None and [reference for reference, _ in listener_rows] != [reference for reference, _ in ownership_rows]:
        raise ValueError("listener and ownership snapshots differ; rerun the private review")
    discovered: dict[str, set[str]] = {reference: set() for reference in targets.values()}
    diagnostics = {"wildcardRows": 0, "matchedFindingRows": 0, "attributedFindingRows": 0}
    for reference, line in ownership_rows:
        diagnostics["wildcardRows"] += 1
        if reference not in discovered:
            continue
        diagnostics["matchedFindingRows"] += 1
        match = re.search(r'users:\(\("([^"\\]+)"', line)
        names = {match.group(1)} if match else set()
        inode_match = re.search(r"\bino:(\d+)\b", line)
        if not names and inode_match and inode_processes is not None:
            names = inode_processes.get(inode_match.group(1), set())
        if names:
            diagnostics["attributedFindingRows"] += 1
        discovered[reference].update(
            name if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name) else "unknown"
            for name in names
        )
    cards = [
        {"findingId": finding_id, "resourceRef": reference, "processClasses": sorted(discovered[reference]) or ["unknown"]}
        for finding_id, reference in sorted(targets.items())
    ]
    classes = Counter(
        process_class
        for card in cards
        for process_class in card["processClasses"]
    )
    payload = {
        "schemaVersion": 1,
        "inventoryDigest": inventory.get("evidenceDigest"),
        "cards": cards,
        "processClassCounts": dict(sorted(classes.items())),
        "diagnostics": diagnostics,
    }
    payload["reviewDigest"] = canonical_digest(payload)
    return payload


def _wildcard_listener_rows(output: str) -> list[tuple[str, str]]:
    rows = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        protocol = fields[0].lower()
        address, port = _split_listener_endpoint(fields[4])
        if port and address in {"*", "0.0.0.0", "::"}:
            rows.append((opaque_ref(f"{protocol}:{port}"), line))
    return rows


def _split_listener_endpoint(value: str) -> tuple[str, str]:
    if value.startswith("[") and "]:" in value:
        return value[1:].rsplit("]:", 1)
    return value.rsplit(":", 1) if ":" in value else (value, "")


def record_evidence(plan: dict[str, Any], inventory: dict[str, Any], finding_id: str, phase: str) -> dict[str, Any]:
    if phase not in {"pre", "post", "rollback"}:
        raise ValueError("phase must be pre, post, or rollback")
    if plan.get("inventoryDigest") != inventory.get("evidenceDigest"):
        raise ValueError("stale remediation plan: inventory digest changed")
    action = next((item for item in plan.get("actions", []) if item.get("findingId") == finding_id), None)
    if not isinstance(action, dict):
        raise ValueError("finding is not in the remediation plan")
    if phase == "post" and action.get("approval") != "approved":
        raise ValueError("post-change evidence requires an approved remediation action")
    record = {
        "schemaVersion": 1,
        "recordedAt": now(),
        "phase": phase,
        "findingId": finding_id,
        "actionId": action.get("id"),
        "action": action.get("action"),
        "inventoryDigest": inventory.get("evidenceDigest"),
        "planDigest": plan.get("planDigest"),
        "sourceRevision": inventory.get("sourceRevision"),
    }
    record["evidenceDigest"] = canonical_digest(record)
    return record


def approve_action(plan: dict[str, Any], inventory: dict[str, Any], finding_id: str, approval_digest: str) -> dict[str, Any]:
    if plan.get("inventoryDigest") != inventory.get("evidenceDigest"):
        raise ValueError("stale remediation plan: inventory digest changed")
    if not approval_digest.startswith("sha256:"):
        raise ValueError("approval must be a reviewed sha256 digest")
    action = next((item for item in plan.get("actions", []) if item.get("findingId") == finding_id), None)
    if not isinstance(action, dict):
        raise ValueError("finding is not in the remediation plan")
    action["approval"] = "approved"
    action["approvalDigest"] = approval_digest
    action["approvedAt"] = now()
    plan["planDigest"] = canonical_digest({key: value for key, value in plan.items() if key != "planDigest"})
    return plan


def owner_review_cards(inventory: dict[str, Any]) -> dict[str, Any]:
    """Resolve opaque finding references to private workload ownership only."""
    digest = str(inventory.get("evidenceDigest", ""))
    if not digest:
        raise ValueError("inventory has no evidence digest")
    ownership = inventory.get("ownership", [])
    if not isinstance(ownership, list):
        raise ValueError("inventory ownership is malformed")
    owners = {
        str(item.get("containerRef")): str(item.get("workloadId"))
        for item in ownership
        if isinstance(item, dict) and item.get("containerRef") and item.get("workloadId")
    }
    cards = []
    for finding in inventory.get("findings", []):
        if not isinstance(finding, dict):
            continue
        resource_ref = str(finding.get("resourceRef", ""))
        owner = owners.get(resource_ref, "")
        cards.append(
            {
                "findingId": str(finding.get("id", "")),
                "category": str(finding.get("category", "")),
                "resourceRef": resource_ref,
                "owner": owner or "unresolved-non-container",
                "ownershipState": "registered" if owner and owner != "legacy-unclassified" else "quarantined",
                "requiredReview": [
                    "review owning configuration privately",
                    "review containment and rollback commands",
                    "capture pre/post health and isolation evidence",
                ],
            }
        )
    payload = {"schemaVersion": 1, "inventoryDigest": digest, "cards": cards}
    payload["reviewDigest"] = canonical_digest(payload)
    return payload


def _containers_with_pids(runner: CommandRunner) -> list[tuple[str, int]]:
    identifiers = runner.run(["docker", "ps", "--no-trunc", "--format", "{{.ID}}"])
    if identifiers.returncode != 0:
        raise RuntimeError("Docker container inspection unavailable")
    values = [line.strip() for line in identifiers.stdout.splitlines() if line.strip()]
    if not values:
        return []
    inspected = runner.run(["docker", "inspect", *values])
    if inspected.returncode != 0:
        raise RuntimeError("Docker container inspect unavailable")
    payload = json.loads(inspected.stdout)
    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid = int((item.get("State") or {}).get("Pid", 0) or 0)
        if pid:
            result.append((opaque_ref(str(item.get("Id", ""))), pid))
    return result


def isolation_report(targets: dict[str, Any], runner: CommandRunner | None = None) -> dict[str, Any]:
    target_items = targets.get("targets", [])
    if not isinstance(target_items, list) or not target_items:
        raise ValueError("private probe targets must contain at least one target")
    for target in target_items:
        if not isinstance(target, dict) or not all(target.get(key) for key in ("id", "host", "port")):
            raise ValueError("each private probe target requires id, host, and port")
    command_runner = runner or CommandRunner()
    checks = []
    gaps = []
    for container_ref, pid in _containers_with_pids(command_runner):
        for target in target_items:
            result = command_runner.run(
                [
                    "timeout",
                    "3",
                    "nsenter",
                    "-t",
                    str(pid),
                    "-n",
                    "python3",
                    "-c",
                    PROBE_PROGRAM,
                    str(target["host"]),
                    str(target["port"]),
                ]
            )
            if result.returncode in {127, 126}:
                gaps.append("namespace-probe-unavailable")
                state = "unavailable"
            elif result.returncode == 0:
                state = "reachable"
            else:
                state = "blocked"
            checks.append(
                {
                    "containerRef": container_ref,
                    "targetRef": opaque_ref(str(target["id"])),
                    "state": state,
                }
            )
    payload = {
        "schemaVersion": 1,
        "capturedAt": now(),
        "complete": not gaps,
        "checks": checks,
        "evidenceGaps": sorted(set(gaps)),
    }
    payload["evidenceDigest"] = canonical_digest(payload)
    return payload


def write_private(payload: dict[str, Any], path: Path) -> Path:
    return write_inventory(payload, path)
