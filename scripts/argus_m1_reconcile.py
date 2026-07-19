"""Fail-closed reconciliation of explicit legacy quarantine records."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED = {
    "realm": "unclassified",
    "zone": "legacy",
    "stage": "none",
    "trustDomain": "legacy-rootful",
    "status": "legacy-unclassified",
    "admission": "denied",
}


class ReconcileError(ValueError):
    """Raised when quarantine reconciliation cannot safely continue."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError("required classification input is unavailable") from exc
    if not isinstance(value, dict):
        raise ReconcileError("required classification input is malformed")
    return value


def _atomic_replace(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".argus-tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def reconcile(root: Path, *, apply: bool) -> dict[str, Any]:
    """Add only missing explicit quarantine records, never classify or remove."""
    workload_data = _load(root / "config" / "workloads.json")
    baseline_path = root / "config" / "argus" / "legacy-classification.json"
    baseline = _load(baseline_path)
    workloads = workload_data.get("workloads")
    records = baseline.get("workloads")
    default = baseline.get("default")
    if not isinstance(workloads, list) or not isinstance(records, dict) or default != EXPECTED:
        raise ReconcileError("legacy classification baseline is not fail-closed")
    tracked = {str(item.get("id", "")) for item in workloads if isinstance(item, dict)}
    if "" in tracked:
        raise ReconcileError("workload registry contains an invalid ID")
    invalid = [value for value in records.values() if not isinstance(value, dict) or any(value.get(key) != expected for key, expected in EXPECTED.items())]
    if invalid:
        raise ReconcileError("existing legacy classification is not fail-closed")
    missing = sorted(tracked - set(records))
    result: dict[str, Any] = {"schemaVersion": 1, "applied": False, "missingCount": len(missing), "quarantine": "legacy-unclassified"}
    if not apply or not missing:
        return result
    backup_dir = root / "runtime" / "argus" / "classification-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"legacy-classification-{timestamp}.json"
    shutil.copy2(baseline_path, backup)
    replacement = json.loads(json.dumps(baseline))
    replacement["workloads"].update({workload_id: dict(EXPECTED) for workload_id in missing})
    _atomic_replace(baseline_path, replacement)
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    return {**result, "applied": True, "backupDigest": f"sha256:{digest}"}
