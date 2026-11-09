"""Fail-closed, insert-only registration of onboarded workloads into private M1 state."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus_m1_retired_workloads import (
    SCHEMA_VERSION,
    TABLES,
    RetirementReconcileError,
    _canonical,
    _create_backups,
    _expected,
    _intent_present,
    _load_journal,
    _read_entities,
    _read_projection,
    _sync_directory,
    _write_journal,
)
from argus_sqlite import ClosingConnection
from argus_state import AuditLedger


OPERATION = "inventory.register"
ACTOR = "argus-onboarded-workload-reconciler"
JOURNAL_LABEL = "onboarded workload registration journal"


class OnboardedReconcileError(RetirementReconcileError):
    """Raised when onboarded workloads cannot be registered in M1 safely."""


@dataclass(frozen=True)
class RegistrationPlan:
    """Workloads active in reviewed config and absent from each M1 store."""

    config_digest: str
    entities: tuple[str, ...]
    privacy: tuple[str, ...]
    access: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.entities or self.privacy or self.access)

    def summary(self) -> dict[str, int]:
        return {
            "entityInsertions": len(self.entities),
            "privacyProjectionInsertions": len(self.privacy),
            "accessProjectionInsertions": len(self.access),
        }


def _insertions(actual: dict[str, Any], expected: dict[str, Any], retired_ids: set[str], store: str) -> tuple[str, ...]:
    if any(actual[workload_id] != expected[workload_id] for workload_id in set(actual) & set(expected)):
        raise OnboardedReconcileError(f"M1 {store} differs from the reviewed configuration for an active workload")
    if set(actual) - set(expected) - retired_ids:
        raise OnboardedReconcileError(f"M1 {store} contains an unapproved stale workload")
    # _expected() rejects active/retired overlap, so every missing ID is active and not retired.
    return tuple(sorted(set(expected) - set(actual)))


def _plan(root: Path) -> RegistrationPlan:
    entities, privacy, access, retired_ids, config_digest = _expected(root)
    runtime = root / "runtime" / "argus"
    state_path = runtime / "m1" / "state.sqlite3"
    return RegistrationPlan(
        config_digest=config_digest,
        entities=_insertions(_read_entities(runtime / "entity-store.sqlite3"), entities, retired_ids, "entity store"),
        privacy=_insertions(_read_projection(state_path, TABLES["privacy"][0]), privacy, retired_ids, "privacy projection"),
        access=_insertions(_read_projection(state_path, TABLES["access"][0]), access, retired_ids, "access projection"),
    )


def _insert(path: Path, rows: dict[str, list[tuple[Any, ...]]]) -> None:
    """Insert rows per table in one transaction; a plain INSERT refuses to overwrite."""
    statements = {
        "entities": "INSERT INTO entities(entity_id, entity_kind, revision, state_json) VALUES (?, ?, 1, ?)",
        **{table: f"INSERT INTO {table}({column}, entry_json) VALUES (?, ?)" for table, column in TABLES.values()},
    }
    if not any(rows.values()):
        return
    try:
        with sqlite3.connect(path, factory=ClosingConnection) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for table, values in rows.items():
                connection.executemany(statements[table], values)
    except sqlite3.IntegrityError as exc:
        raise OnboardedReconcileError("M1 state changed during onboarded workload registration") from exc
    except sqlite3.Error as exc:
        raise OnboardedReconcileError("M1 onboarded workload registration failed") from exc


def reconcile_onboarded_workloads(root: Path, *, apply: bool) -> dict[str, Any]:
    """Insert reviewed active workloads missing from M1; never update or delete a row."""
    root = root.resolve()
    plan = _plan(root)
    result = {"schemaVersion": SCHEMA_VERSION, "ready": True, **plan.summary()}
    if not apply:
        return {**result, "registered": False, "alreadyApplied": not plan.has_changes}

    runtime = root / "runtime" / "argus"
    ledger = AuditLedger(runtime / "audit.sqlite3")
    if not ledger.verify():
        raise OnboardedReconcileError("M1 audit ledger is not tamper-evident")
    journal_path = runtime / "m1" / "onboarded-workload-register.json"
    journal = _load_journal(journal_path, operation=OPERATION, label=JOURNAL_LABEL)
    if journal is not None and journal["configDigest"] != plan.config_digest:
        raise OnboardedReconcileError("onboarded workload registration input changed; refusing recovery")
    if not plan.has_changes and journal is None:
        return {**result, "registered": True, "alreadyApplied": True}

    if journal is None:
        correlation_id = str(uuid.uuid4())
        journal = {
            "schemaVersion": SCHEMA_VERSION,
            "operation": OPERATION,
            "configDigest": plan.config_digest,
            "correlationId": correlation_id,
            "backups": _create_backups(root, correlation_id, "onboarding-backups"),
        }
        _write_journal(journal_path, journal)
    correlation_id = str(journal["correlationId"])
    event = {
        "actor": ACTOR,
        "operation": OPERATION,
        "target": "m1-deployed-inventory-state",
        "trustDomain": "management",
        "correlationId": correlation_id,
    }
    if not _intent_present(ledger, correlation_id, OPERATION):
        ledger.append({**event, "outcome": "intent"})

    entities, privacy, access, _, config_digest = _expected(root)
    if config_digest != plan.config_digest:
        raise OnboardedReconcileError("reviewed inventory changed during M1 registration")
    _insert(
        runtime / "entity-store.sqlite3",
        {"entities": [(workload_id, entities[workload_id]["kind"], _canonical(entities[workload_id]["state"])) for workload_id in plan.entities]},
    )
    _insert(
        runtime / "m1" / "state.sqlite3",
        {
            TABLES["privacy"][0]: [(workload_id, _canonical(privacy[workload_id])) for workload_id in plan.privacy],
            TABLES["access"][0]: [(workload_id, _canonical(access[workload_id])) for workload_id in plan.access],
        },
    )

    final_plan = _plan(root)
    if final_plan.config_digest != plan.config_digest or final_plan.has_changes:
        raise OnboardedReconcileError("M1 onboarded workload registration did not reach parity")
    if not ledger.has_correlation_outcome(correlation_id):
        ledger.append({**event, "outcome": "accepted", **plan.summary()})
    journal_path.unlink()
    _sync_directory(journal_path.parent)
    return {**result, "registered": True, "alreadyApplied": False}
