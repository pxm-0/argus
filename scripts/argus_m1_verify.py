"""Secret-safe, fail-closed verification for the deployed M1 state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from argus_state import AuditLedger, SQLiteRepository, legacy_workload_snapshot


class VerificationError(ValueError):
    """Raised when required M1 evidence is absent, malformed, or divergent."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError("required private M1 input is unavailable") from exc
    if not isinstance(value, dict):
        raise VerificationError("required private M1 input is malformed")
    return value


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _projection_parity(path: Path, table: str, workloads: dict[str, Any]) -> bool:
    if not path.is_file():
        raise VerificationError("M1 projection store is missing")
    if table not in {"privacy_projection", "access_projection"}:
        raise VerificationError("unknown M1 projection")
    expected = sorted((str(key), json.dumps(value, sort_keys=True, separators=(",", ":"))) for key, value in workloads.items())
    try:
        with sqlite3.connect(path) as connection:
            rows = connection.execute(f"SELECT workload_id, entry_json FROM {table} ORDER BY workload_id").fetchall()
    except sqlite3.Error as exc:
        raise VerificationError("M1 projection store is malformed") from exc
    actual = [(str(workload_id), str(entry_json)) for workload_id, entry_json in rows]
    return actual == expected


def verify_m1_state(root: Path) -> dict[str, Any]:
    """Verify all local M1 stores without returning workload or host details."""
    config = root / "config"
    runtime = root / "runtime" / "argus"
    workloads = _load(config / "workloads.json").get("workloads")
    classifications = _load(config / "argus" / "legacy-classification.json").get("workloads")
    privacy = _load(config / "privacy.json").get("workloads")
    access = _load(config / "access.json").get("workloads")
    if not isinstance(workloads, list) or not all(isinstance(value, dict) for value in workloads):
        raise VerificationError("workload registry is malformed")
    if not isinstance(classifications, dict) or not isinstance(privacy, dict) or not isinstance(access, dict):
        raise VerificationError("M1 compatibility registries are malformed")
    snapshot = legacy_workload_snapshot(workloads, classifications)
    entities = SQLiteRepository(runtime / "entity-store.sqlite3")
    if not entities.semantic_parity(snapshot):
        raise VerificationError("canonical entity store has no semantic parity")
    state_path = runtime / "m1" / "state.sqlite3"
    privacy_ok = _projection_parity(state_path, "privacy_projection", privacy)
    access_ok = _projection_parity(state_path, "access_projection", access)
    if not privacy_ok or not access_ok:
        raise VerificationError("M1 compatibility projection has no semantic parity")
    ledger_path = runtime / "audit.sqlite3"
    if not ledger_path.is_file():
        raise VerificationError("M1 audit ledger is missing")
    ledger = AuditLedger(ledger_path)
    if not ledger.verify():
        raise VerificationError("M1 audit ledger is not tamper-evident")
    checkpoint = ledger.checkpoint()
    if checkpoint["sequence"] < 1:
        raise VerificationError("M1 audit ledger is empty")
    return {
        "schemaVersion": 1,
        "verified": True,
        "entityCount": len(snapshot),
        "auditSequence": checkpoint["sequence"],
        "entitySnapshotDigest": _digest(snapshot),
        "auditCheckpointHash": checkpoint["checkpointHash"],
    }
