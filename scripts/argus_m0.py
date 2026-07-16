#!/usr/bin/env python3
"""Typed private planning, evidence, and isolation helpers for Argus M0."""

from __future__ import annotations

import json
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
    actions = []
    for finding in inventory.get("findings", []):
        if not isinstance(finding, dict):
            continue
        category = str(finding.get("category", ""))
        action = ACTION_BY_CATEGORY.get(category, "investigate-and-contain")
        finding_id = str(finding.get("id", ""))
        actions.append(
            {
                "id": opaque_ref(f"{digest}|{finding_id}|{action}"),
                "findingId": finding_id,
                "action": action,
                "approval": "pending",
                "state": "planned",
                "requires": ["pre-health", "rollback", "post-health", "isolation-check"],
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
