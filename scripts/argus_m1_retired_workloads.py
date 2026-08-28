"""Fail-closed reconciliation of formally retired workloads from M1 state."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argus_sqlite import ClosingConnection
from argus_state import AuditLedger, legacy_workload_snapshot


SCHEMA_VERSION = 1
OPERATION = "retired-workloads.reconcile"
TABLES = {
    "privacy": ("privacy_projection", "workload_id"),
    "access": ("access_projection", "workload_id"),
}


class RetirementReconcileError(ValueError):
    """Raised when retired M1 records cannot be removed safely."""


@dataclass(frozen=True)
class RetirementPlan:
    """A fully validated set of stale M1 records eligible for deletion."""

    config_digest: str
    entities: tuple[str, ...]
    privacy: tuple[str, ...]
    access: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.entities or self.privacy or self.access)

    def summary(self) -> dict[str, int]:
        return {
            "entityRemovals": len(self.entities),
            "privacyProjectionRemovals": len(self.privacy),
            "accessProjectionRemovals": len(self.access),
        }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetirementReconcileError(f"{label} is unavailable or malformed") from exc
    if not isinstance(value, dict):
        raise RetirementReconcileError(f"{label} must contain an object")
    return value


def _ids(value: Any, label: str) -> set[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise RetirementReconcileError(f"{label} must contain non-empty workload IDs")
    result = set(value)
    if len(result) != len(value):
        raise RetirementReconcileError(f"{label} contains duplicate workload IDs")
    return result


def _active_workload_ids(value: Any) -> set[str]:
    if not isinstance(value, list) or not value:
        raise RetirementReconcileError("active workload registry is malformed")
    ids: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise RetirementReconcileError("active workload registry contains an invalid ID")
        ids.append(item["id"])
    result = set(ids)
    if len(result) != len(ids):
        raise RetirementReconcileError("active workload registry contains duplicate IDs")
    return result


def _workload_map(value: Any, label: str, active_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != active_ids:
        raise RetirementReconcileError(f"{label} does not exactly match the active workload registry")
    return value


def _expected(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], set[str], str]:
    config = root / "config"
    workload_data = _load_object(config / "workloads.json", "workload registry")
    active_workloads = workload_data.get("workloads")
    active_ids = _active_workload_ids(active_workloads)
    legacy = _load_object(config / "argus" / "legacy-classification.json", "legacy classification registry")
    classified = _load_object(config / "argus" / "workload-classification.json", "workload classification registry")
    privacy = _load_object(config / "privacy.json", "privacy registry")
    access = _load_object(config / "access.json", "access registry")
    retired_data = _load_object(config / "argus" / "retired-workloads.json", "retired workload registry")
    if retired_data.get("schemaVersion") != SCHEMA_VERSION:
        raise RetirementReconcileError("retired workload registry has an unsupported schema")
    retired_ids = _ids(retired_data.get("workloads"), "retired workload registry")
    if active_ids & retired_ids:
        raise RetirementReconcileError("retired workload registry overlaps the active workload registry")
    legacy_records = _workload_map(legacy.get("workloads"), "legacy classification registry", active_ids)
    _workload_map(classified.get("workloads"), "workload classification registry", active_ids)
    privacy_records = _workload_map(privacy.get("workloads"), "privacy registry", active_ids)
    access_records = _workload_map(access.get("workloads"), "access registry", active_ids)
    try:
        snapshot = legacy_workload_snapshot(active_workloads, legacy_records)
    except (TypeError, ValueError) as exc:
        raise RetirementReconcileError("active workload classification snapshot is invalid") from exc
    entities = {
        str(entry["id"]): {
            "id": str(entry["id"]),
            "kind": str(entry["kind"]),
            "state": entry["state"],
        }
        for entry in snapshot
    }
    config_digest = _digest(
        {
            "entities": entities,
            "privacy": privacy_records,
            "access": access_records,
            "retired": sorted(retired_ids),
        }
    )
    return entities, privacy_records, access_records, retired_ids, config_digest


def _read_entities(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise RetirementReconcileError("M1 entity store is unavailable")
    try:
        with sqlite3.connect(path, factory=ClosingConnection) as connection:
            rows = connection.execute("SELECT entity_id, entity_kind, state_json FROM entities ORDER BY entity_id").fetchall()
    except sqlite3.Error as exc:
        raise RetirementReconcileError("M1 entity store is malformed") from exc
    result: dict[str, dict[str, Any]] = {}
    for entity_id, entity_kind, state_json in rows:
        if not isinstance(entity_id, str) or not entity_id or not isinstance(entity_kind, str) or not entity_kind:
            raise RetirementReconcileError("M1 entity store contains an invalid record")
        try:
            state = json.loads(str(state_json))
        except json.JSONDecodeError as exc:
            raise RetirementReconcileError("M1 entity store contains malformed state") from exc
        if not isinstance(state, dict) or entity_id in result:
            raise RetirementReconcileError("M1 entity store contains an invalid record")
        result[entity_id] = {"id": entity_id, "kind": entity_kind, "state": state}
    return result


def _read_projection(path: Path, table: str) -> dict[str, Any]:
    if not path.is_file():
        raise RetirementReconcileError("M1 projection store is unavailable")
    if table not in {item[0] for item in TABLES.values()}:
        raise RetirementReconcileError("unknown M1 projection")
    try:
        with sqlite3.connect(path, factory=ClosingConnection) as connection:
            rows = connection.execute(f"SELECT workload_id, entry_json FROM {table} ORDER BY workload_id").fetchall()
    except sqlite3.Error as exc:
        raise RetirementReconcileError("M1 projection store is malformed") from exc
    result: dict[str, Any] = {}
    for workload_id, entry_json in rows:
        if not isinstance(workload_id, str) or not workload_id:
            raise RetirementReconcileError("M1 projection store contains an invalid workload ID")
        try:
            entry = json.loads(str(entry_json))
        except json.JSONDecodeError as exc:
            raise RetirementReconcileError("M1 projection store contains malformed state") from exc
        if not isinstance(entry, dict) or workload_id in result:
            raise RetirementReconcileError("M1 projection store contains an invalid record")
        result[workload_id] = entry
    return result


def _stale_ids(actual: dict[str, Any], expected: dict[str, Any], retired_ids: set[str], store: str) -> tuple[str, ...]:
    missing = set(expected) - set(actual)
    changed = {workload_id for workload_id in expected if actual.get(workload_id) != expected[workload_id]}
    if missing or changed:
        raise RetirementReconcileError(f"M1 {store} differs for an active workload")
    stale = set(actual) - set(expected)
    if stale - retired_ids:
        raise RetirementReconcileError(f"M1 {store} contains an unapproved stale workload")
    return tuple(sorted(stale))


def _plan(root: Path) -> RetirementPlan:
    entities, privacy, access, retired_ids, config_digest = _expected(root)
    runtime = root / "runtime" / "argus"
    entity_rows = _read_entities(runtime / "entity-store.sqlite3")
    state_path = runtime / "m1" / "state.sqlite3"
    privacy_rows = _read_projection(state_path, TABLES["privacy"][0])
    access_rows = _read_projection(state_path, TABLES["access"][0])
    return RetirementPlan(
        config_digest=config_digest,
        entities=_stale_ids(entity_rows, entities, retired_ids, "entity store"),
        privacy=_stale_ids(privacy_rows, privacy, retired_ids, "privacy projection"),
        access=_stale_ids(access_rows, access, retired_ids, "access projection"),
    )


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_journal(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(_canonical(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_journal(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = _load_object(path, "retired workload reconciliation journal")
    if (
        value.get("schemaVersion") != SCHEMA_VERSION
        or value.get("operation") != OPERATION
        or not isinstance(value.get("configDigest"), str)
        or not value["configDigest"].startswith("sha256:")
        or not isinstance(value.get("correlationId"), str)
        or not value["correlationId"]
        or not isinstance(value.get("backups"), dict)
    ):
        raise RetirementReconcileError("retired workload reconciliation journal is malformed")
    return value


def _backup_database(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    except sqlite3.Error as exc:
        raise RetirementReconcileError("could not checkpoint M1 rollback evidence") from exc
    finally:
        destination_connection.close()
        source_connection.close()
    os.chmod(destination, 0o600)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())


def _create_backups(root: Path, correlation_id: str) -> dict[str, str]:
    runtime = root / "runtime" / "argus"
    backup_dir = runtime / "m1" / "retirement-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = correlation_id.replace("-", "")[:12]
    sources = {
        "entities": runtime / "entity-store.sqlite3",
        "projections": runtime / "m1" / "state.sqlite3",
    }
    backups: dict[str, str] = {}
    for label, source in sources.items():
        if not source.is_file():
            raise RetirementReconcileError("M1 rollback evidence source is unavailable")
        destination = backup_dir / f"{label}-{timestamp}-{suffix}.sqlite3"
        _backup_database(source, destination)
        backups[label] = str(destination)
    _sync_directory(backup_dir)
    return backups


def _delete_rows(path: Path, table: str, column: str, workload_ids: tuple[str, ...]) -> None:
    if not workload_ids:
        return
    if (table, column) not in {("entities", "entity_id"), *TABLES.values()}:
        raise RetirementReconcileError("unknown M1 retirement deletion target")
    placeholders = ", ".join("?" for _ in workload_ids)
    try:
        with sqlite3.connect(path, factory=ClosingConnection) as connection:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute(
                f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
                workload_ids,
            ).rowcount
            if deleted != len(workload_ids):
                raise RetirementReconcileError("M1 state changed during retired workload reconciliation")
    except sqlite3.Error as exc:
        raise RetirementReconcileError("M1 retirement deletion failed") from exc


def _intent_present(ledger: AuditLedger, correlation_id: str) -> bool:
    return any(
        event.get("correlationId") == correlation_id
        and event.get("operation") == OPERATION
        and event.get("outcome") == "intent"
        for event in ledger._events()
    )


def reconcile_retired_workloads(root: Path, *, apply: bool) -> dict[str, Any]:
    """Delete only declared retired records after exact active-state parity checks."""
    root = root.resolve()
    plan = _plan(root)
    result = {"schemaVersion": SCHEMA_VERSION, "ready": True, **plan.summary()}
    if not apply:
        return {**result, "reconciled": False, "alreadyApplied": not plan.has_changes}

    runtime = root / "runtime" / "argus"
    ledger = AuditLedger(runtime / "audit.sqlite3")
    if not ledger.verify():
        raise RetirementReconcileError("M1 audit ledger is not tamper-evident")
    journal_path = runtime / "m1" / "retired-workload-reconcile.json"
    journal = _load_journal(journal_path)
    if journal is not None and journal["configDigest"] != plan.config_digest:
        raise RetirementReconcileError("retired workload reconciliation input changed; refusing recovery")
    if not plan.has_changes and journal is None:
        return {**result, "reconciled": True, "alreadyApplied": True}

    if journal is None:
        correlation_id = str(uuid.uuid4())
        journal = {
            "schemaVersion": SCHEMA_VERSION,
            "operation": OPERATION,
            "configDigest": plan.config_digest,
            "correlationId": correlation_id,
            "backups": _create_backups(root, correlation_id),
        }
        _write_journal(journal_path, journal)
    correlation_id = str(journal["correlationId"])
    if not _intent_present(ledger, correlation_id):
        ledger.append(
            {
                "actor": "argus-retired-workload-reconciler",
                "operation": OPERATION,
                "outcome": "intent",
                "target": "m1-retired-workload-state",
                "trustDomain": "management",
                "correlationId": correlation_id,
            }
        )

    _delete_rows(runtime / "entity-store.sqlite3", "entities", "entity_id", plan.entities)
    _delete_rows(runtime / "m1" / "state.sqlite3", *TABLES["privacy"], plan.privacy)
    _delete_rows(runtime / "m1" / "state.sqlite3", *TABLES["access"], plan.access)

    final_plan = _plan(root)
    if final_plan.config_digest != plan.config_digest or final_plan.has_changes:
        raise RetirementReconcileError("M1 retired workload reconciliation did not restore exact parity")
    if not ledger.has_correlation_outcome(correlation_id):
        ledger.append(
            {
                "actor": "argus-retired-workload-reconciler",
                "operation": OPERATION,
                "outcome": "accepted",
                "target": "m1-retired-workload-state",
                "trustDomain": "management",
                "correlationId": correlation_id,
                **plan.summary(),
            }
        )
    journal_path.unlink()
    _sync_directory(journal_path.parent)
    return {**result, "reconciled": True, "alreadyApplied": False}
