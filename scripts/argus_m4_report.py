"""Fail-closed M4 registry/classification reconciliation report."""
from __future__ import annotations
from typing import Any

QUARANTINE = {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful", "status": "legacy-unclassified", "admission": "denied"}
TARGET_KEYS = {"realm", "zone", "stage", "trustDomain", "status", "admission"}


def _valid_target(state: Any) -> bool:
    if not isinstance(state, dict) or set(state) != TARGET_KEYS:
        return False
    realm, zone, stage = state.get("realm"), state.get("zone"), state.get("stage")
    expected_domain = f"{realm}-{zone}"
    return (
        realm in {"personal", "work"}
        and zone in {"sandbox", "managed"}
        and stage in ({"none"} if zone == "sandbox" else {"dev", "staging", "production"})
        and state.get("trustDomain") == expected_domain
        and state.get("status") == "classified"
        and state.get("admission") == "allowed"
    )

def classification_report(workloads: list[dict[str, Any]], classifications: dict[str, Any], placements: dict[str, Any] | None = None) -> dict[str, Any]:
    declared = {str(item.get("id")) for item in workloads if isinstance(item, dict) and item.get("id")}
    mapped = classifications.get("workloads", {}) if isinstance(classifications, dict) else {}
    placed = placements.get("workloads", {}) if isinstance(placements, dict) else {}
    if not isinstance(mapped, dict):
        raise ValueError("classification workloads must be an object")
    if not isinstance(placed, dict):
        raise ValueError("placement workloads must be an object")
    missing = sorted(declared - (set(mapped) | set(placed)))
    unknown = sorted((set(mapped) | set(placed)) - declared)
    superseded = sorted(set(mapped) & set(placed))
    invalid = sorted(workload_id for workload_id, state in mapped.items() if state != QUARANTINE)
    invalid_target = sorted(workload_id for workload_id, state in placed.items() if not _valid_target(state))
    return {
        "schemaVersion": 1,
        "complete": not missing and not unknown and not invalid and not invalid_target,
        "declaredCount": len(declared),
        "classifiedCount": len(set(mapped) | set(placed)),
        "targetCount": len(placed),
        "missingClassification": missing,
        "unknownClassification": unknown,
        "supersededLegacyClassification": superseded,
        "nonQuarantineClassification": invalid,
        "invalidTargetClassification": invalid_target,
    }
