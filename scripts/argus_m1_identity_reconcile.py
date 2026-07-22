"""Audited one-time reconciliation for the Argus identity rename."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argus_state import AuditLedger


class IdentityReconcileError(ValueError):
    """Raised when the private projection is not the exact pre-rename state."""


def _rename(value: Any) -> Any:
    if isinstance(value, str):
        return (
            value.replace("Oreo Cloud", "Argus")
            .replace("OREO_CLOUD", "ARGUS")
            .replace("oreo-cloud", "argus")
            .replace("oreo_", "argus_")
            .replace("oreo-", "argus-")
        )
    if isinstance(value, list):
        return [_rename(item) for item in value]
    if isinstance(value, dict):
        return {_rename(key): _rename(item) for key, item in value.items()}
    return value


def _load_workloads(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityReconcileError("identity compatibility input is unavailable") from exc
    workloads = value.get("workloads") if isinstance(value, dict) else None
    if not isinstance(workloads, dict):
        raise IdentityReconcileError("identity compatibility input is malformed")
    return workloads


def _projection(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    try:
        rows = connection.execute(f"SELECT workload_id, entry_json FROM {table}").fetchall()
        return {str(workload_id): json.loads(str(entry_json)) for workload_id, entry_json in rows}
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        raise IdentityReconcileError("M1 identity projection is malformed") from exc


def reconcile_identity(root: Path, *, apply: bool) -> dict[str, Any]:
    runtime = root / "runtime" / "argus"
    state_path = runtime / "m1" / "state.sqlite3"
    ledger = AuditLedger(runtime / "audit.sqlite3")
    journal = runtime / "m1" / "identity-reconcile.json"
    if not state_path.is_file() or not ledger.verify():
        raise IdentityReconcileError("M1 private state is unavailable or not tamper-evident")
    expected = {
        "privacy_projection": _load_workloads(root / "config" / "privacy.json"),
        "access_projection": _load_workloads(root / "config" / "access.json"),
    }
    with sqlite3.connect(state_path) as connection:
        actual = {table: _projection(connection, table) for table in expected}
    if actual == expected:
        if journal.is_file():
            record = json.loads(journal.read_text(encoding="utf-8"))
            correlation_id = str(record.get("correlationId", ""))
            if not correlation_id:
                raise IdentityReconcileError("identity reconciliation journal is malformed")
            if not ledger.has_correlation_outcome(correlation_id):
                ledger.append({"actor": "argus-identity-cutover", "operation": "identity.reconcile", "outcome": "accepted", "target": "m1-compatibility-projections", "trustDomain": "management", "correlationId": correlation_id})
            journal.unlink()
        return {"schemaVersion": 1, "reconciled": True, "alreadyApplied": True}
    transformed = {table: _rename(entries) for table, entries in actual.items()}
    if transformed != expected:
        raise IdentityReconcileError("M1 projection differs beyond the reviewed identity rename")
    if not apply:
        return {"schemaVersion": 1, "reconciled": False, "alreadyApplied": False, "ready": True}
    backup_dir = runtime / "identity-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"m1-state-{timestamp}.sqlite3"
    shutil.copy2(state_path, backup)
    correlation_id = str(uuid.uuid4())
    journal.write_text(json.dumps({"schemaVersion": 1, "correlationId": correlation_id, "backup": str(backup)}, sort_keys=True) + "\n", encoding="utf-8")
    ledger.append({"actor": "argus-identity-cutover", "operation": "identity.reconcile", "outcome": "intent", "target": "m1-compatibility-projections", "trustDomain": "management", "correlationId": correlation_id})
    try:
        with sqlite3.connect(state_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for table, entries in expected.items():
                connection.execute(f"DELETE FROM {table}")
                connection.executemany(
                    f"INSERT INTO {table}(workload_id, entry_json) VALUES (?, ?)",
                    [(key, json.dumps(value, sort_keys=True, separators=(",", ":"))) for key, value in entries.items()],
                )
    except sqlite3.Error as exc:
        ledger.append({"actor": "argus-identity-cutover", "operation": "identity.reconcile", "outcome": "error", "target": "m1-compatibility-projections", "trustDomain": "management", "correlationId": correlation_id})
        raise IdentityReconcileError("M1 identity projection update failed") from exc
    ledger.append({"actor": "argus-identity-cutover", "operation": "identity.reconcile", "outcome": "accepted", "target": "m1-compatibility-projections", "trustDomain": "management", "correlationId": correlation_id})
    journal.unlink()
    return {"schemaVersion": 1, "reconciled": True, "alreadyApplied": False, "backup": str(backup)}
