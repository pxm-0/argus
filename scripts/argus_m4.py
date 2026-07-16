"""Fail-closed validation of private M4 stateful migration evidence."""
from __future__ import annotations
from typing import Any


class MigrationError(ValueError):
    pass


def validate_stateful_migration(record: dict[str, Any]) -> dict[str, Any]:
    required = {
        "workloadId", "logicalVolume", "sourceRuntimeRef", "targetRuntimeRef",
        "sourceVolumeRef", "targetVolumeRef", "sourceUidGid", "targetUidGid",
        "sourceChecksum", "targetChecksum", "backupVerified", "restoreVerified",
        "sourceFenced", "targetFencedBeforeRollback", "healthVerified",
        "accessVerified", "isolationVerified", "rollbackVerified",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise MigrationError("migration evidence must contain exactly the required fields")
    for key in ("workloadId", "logicalVolume", "sourceRuntimeRef", "targetRuntimeRef", "sourceVolumeRef", "targetVolumeRef", "sourceUidGid", "targetUidGid"):
        if not isinstance(record[key], str) or not record[key]:
            raise MigrationError(f"{key} is required")
    for key in ("sourceChecksum", "targetChecksum"):
        if not isinstance(record[key], str) or not record[key].startswith("sha256:"):
            raise MigrationError(f"{key} must be a sha256 digest")
    if record["sourceRuntimeRef"] == record["targetRuntimeRef"] or record["sourceVolumeRef"] == record["targetVolumeRef"]:
        raise MigrationError("source and target physical identities must differ")
    if record["sourceChecksum"] != record["targetChecksum"]:
        raise MigrationError("source and target checksums differ")
    if not all(record[key] is True for key in required if key.endswith("Verified") or key in {"sourceFenced", "targetFencedBeforeRollback"}):
        raise MigrationError("backup, fencing, validation, and rollback evidence are all required")
    return {
        "schemaVersion": 1,
        "workloadId": record["workloadId"],
        "logicalVolume": record["logicalVolume"],
        "sourceRuntimeRef": record["sourceRuntimeRef"],
        "targetRuntimeRef": record["targetRuntimeRef"],
        "sourceVolumeRef": record["sourceVolumeRef"],
        "targetVolumeRef": record["targetVolumeRef"],
        "accepted": True,
    }
