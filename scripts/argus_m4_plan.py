"""Fail-closed, read-only Argus M4 migration planning."""
from __future__ import annotations
from typing import Any

REQUIRED = {"pilotIsolationVerified", "backupVerified", "restoreVerified", "sourceFenced", "targetFencedBeforeRollback", "uidGidVerified", "checksumVerified", "healthVerified", "accessVerified", "driftVerified", "rollbackVerified"}

def migration_plan(workload_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    if not workload_id or not isinstance(evidence, dict):
        raise ValueError("workload ID and evidence are required")
    missing = sorted(key for key in REQUIRED if evidence.get(key) is not True)
    mappings = evidence.get("physicalMappings")
    if not isinstance(mappings, dict) or set(mappings) != {"sourceRuntimeRef", "targetRuntimeRef", "sourceVolumeRef", "targetVolumeRef"} or not all(isinstance(value, str) and value.startswith("sha256:") for value in mappings.values()):
        missing.append("physicalMappings")
    if missing:
        return {"schemaVersion": 1, "workloadId": workload_id, "approved": False, "missing": sorted(missing), "steps": []}
    return {
        "schemaVersion": 1, "workloadId": workload_id, "approved": True,
        "physicalMappings": mappings,
        "steps": [
            "quiesce-and-fence-source", "snapshot-and-verify-backup", "translate-uid-gid",
            "copy-to-new-target-volume", "verify-checksum-and-permissions", "start-and-observe-target",
            "record-health-access-isolation-and-drift", "release-source-only-after-acceptance",
        ],
        "rollback": ["stop-and-fence-target", "verify-target-is-not-writing", "reopen-source", "record-rollback-evidence"],
    }
