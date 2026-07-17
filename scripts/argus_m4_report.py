"""Fail-closed M4 registry/classification reconciliation report."""
from __future__ import annotations
from typing import Any

QUARANTINE = {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful", "status": "legacy-unclassified", "admission": "denied"}

def classification_report(workloads: list[dict[str, Any]], classifications: dict[str, Any]) -> dict[str, Any]:
    declared = {str(item.get("id")) for item in workloads if isinstance(item, dict) and item.get("id")}
    mapped = classifications.get("workloads", {}) if isinstance(classifications, dict) else {}
    if not isinstance(mapped, dict):
        raise ValueError("classification workloads must be an object")
    missing = sorted(declared - set(mapped))
    unknown = sorted(set(mapped) - declared)
    invalid = sorted(workload_id for workload_id, state in mapped.items() if state != QUARANTINE)
    return {
        "schemaVersion": 1,
        "complete": not missing and not unknown and not invalid,
        "declaredCount": len(declared),
        "classifiedCount": len(mapped),
        "missingClassification": missing,
        "unknownClassification": unknown,
        "nonQuarantineClassification": invalid,
    }
