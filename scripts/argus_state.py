"""Fail-closed Argus V1 entity classification and SQLite repository primitives."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REALMS = {"unclassified", "personal", "work"}
ZONES = {"legacy", "sandbox", "managed"}
STAGES = {"none", "dev", "staging", "production"}
DOMAIN_KINDS = {"management", "legacy", "workload"}


class StateError(ValueError):
    """Raised when an entity cannot be safely represented or persisted."""


def _canonical_digest(value: Any) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class AtomicJsonStore:
    """Single-writer compatibility store with a durable write-ahead journal."""

    def __init__(self, path: Path, journal_path: Path):
        self.path = path
        self.journal_path = journal_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"revision": 0, "payload": {}, "transactionId": ""}
        try:
            value = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise StateError("legacy JSON store is malformed") from exc
        if not isinstance(value, dict) or not isinstance(value.get("revision"), int) or not isinstance(value.get("payload"), dict):
            raise StateError("legacy JSON store has an invalid schema")
        return {
            "revision": value["revision"],
            "payload": value["payload"],
            "transactionId": str(value.get("transactionId", "")),
        }

    def _append(self, record: dict[str, Any]) -> None:
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(self.journal_path.parent)

    def replace(self, payload: dict[str, Any], *, expected_revision: int, operation: str) -> int:
        if not isinstance(payload, dict) or not operation:
            raise StateError("payload and typed operation are required")
        current = self.read()
        if current["revision"] != expected_revision:
            raise StateError(f"revision mismatch: expected {expected_revision}, got {current['revision']}")
        transaction_id = str(uuid.uuid4())
        replacement = {"revision": expected_revision + 1, "payload": payload, "transactionId": transaction_id}
        prepared = {
            "phase": "PREPARED",
            "transactionId": transaction_id,
            "expectedRevision": expected_revision,
            "operation": operation,
            "payloadChecksum": _canonical_digest(replacement),
        }
        self._append(prepared)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(replacement, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            _sync_directory(self.path.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._append({"phase": "COMMITTED", "transactionId": transaction_id})
        return replacement["revision"]

    def recover(self) -> dict[str, str]:
        """Close interrupted writes without replaying an uncommitted mutation."""
        if not self.journal_path.exists():
            return {}
        records: dict[str, set[str]] = {}
        for line in self.journal_path.read_text().splitlines():
            try:
                record = json.loads(line)
                transaction_id = str(record["transactionId"])
                phase = str(record["phase"])
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise StateError("legacy journal is malformed") from exc
            records.setdefault(transaction_id, set()).add(phase)
        current = self.read()
        outcomes: dict[str, str] = {}
        for transaction_id, phases in records.items():
            if "PREPARED" not in phases or "COMMITTED" in phases or "ABORTED" in phases:
                continue
            if current["transactionId"] == transaction_id:
                self._append({"phase": "COMMITTED", "transactionId": transaction_id})
                outcomes[transaction_id] = "committed"
            else:
                self._append({"phase": "ABORTED", "transactionId": transaction_id})
                outcomes[transaction_id] = "aborted"
        return outcomes


@dataclass(frozen=True)
class Classification:
    realm: str | None
    zone: str | None
    stage: str | None
    trust_domain: str
    domain_kind: str

    def validate(self) -> None:
        if self.domain_kind not in DOMAIN_KINDS:
            raise StateError("unknown trust-domain kind")
        if not self.trust_domain:
            raise StateError("trust domain is required")
        if self.domain_kind == "management":
            if any(value is not None for value in (self.realm, self.zone, self.stage)):
                raise StateError("management domains cannot carry workload classification")
            return
        if self.realm not in REALMS or self.zone not in ZONES or self.stage not in STAGES:
            raise StateError("workload classification has an invalid realm, zone, or stage")
        if self.domain_kind == "legacy":
            if (self.realm, self.zone, self.stage) != ("unclassified", "legacy", "none"):
                raise StateError("legacy domains must be unclassified, legacy, and stage none")
        elif self.realm == "unclassified" or self.zone == "legacy":
            raise StateError("workload domains require personal/work and sandbox/managed classification")

    def as_dict(self) -> dict[str, str | None]:
        self.validate()
        return {
            "realm": self.realm,
            "zone": self.zone,
            "stage": self.stage,
            "trustDomain": self.trust_domain,
            "domainKind": self.domain_kind,
        }


@dataclass(frozen=True)
class EntityState:
    declared: Classification
    observed: Classification
    effective: Classification

    def validate(self) -> None:
        self.declared.validate()
        self.observed.validate()
        self.effective.validate()
        if self.declared.domain_kind != self.observed.domain_kind:
            raise StateError("declared and observed domain kinds differ")
        if self.effective != self.observed:
            raise StateError("effective state must reflect the observed state until reconciliation exists")

    def as_dict(self) -> dict[str, dict[str, str | None]]:
        self.validate()
        return {
            "declared": self.declared.as_dict(),
            "observed": self.observed.as_dict(),
            "effective": self.effective.as_dict(),
        }


class SQLiteRepository:
    """The sole M1 writer for classified entities in a SQLite transaction."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_kind TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    state_json TEXT NOT NULL
                );
                """
            )

    def put_entity(self, entity_id: str, entity_kind: str, state: EntityState, *, expected_revision: int | None) -> int:
        if not entity_id or not entity_kind:
            raise StateError("entity ID and kind are required")
        encoded = json.dumps(state.as_dict(), separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT revision FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
            actual = None if current is None else int(current["revision"])
            if actual != expected_revision:
                raise StateError(f"revision mismatch: expected {expected_revision!r}, got {actual!r}")
            revision = 1 if actual is None else actual + 1
            connection.execute(
                "INSERT INTO entities(entity_id, entity_kind, revision, state_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(entity_id) DO UPDATE SET entity_kind=excluded.entity_kind, revision=excluded.revision, state_json=excluded.state_json",
                (entity_id, entity_kind, revision, encoded),
            )
            return revision

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT entity_id, entity_kind, revision, state_json FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["entity_id"],
            "kind": row["entity_kind"],
            "revision": row["revision"],
            "state": json.loads(row["state_json"]),
        }


class AuditLedger:
    """Append-only, hash-chained mutation intent and outcome ledger."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS audit_events (sequence INTEGER PRIMARY KEY, payload_json TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append(self, payload: dict[str, Any]) -> str:
        required = {"actor", "operation", "outcome", "target", "trustDomain"}
        if not required.issubset(payload) or not all(isinstance(payload[key], str) and payload[key] for key in required):
            raise StateError("audit event is missing required identity, operation, outcome, target, or domain")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
            sequence = 1 if previous is None else int(previous["sequence"]) + 1
            previous_hash = "" if previous is None else str(previous["event_hash"])
            event_hash = _canonical_digest({"sequence": sequence, "previousHash": previous_hash, "payload": payload})
            connection.execute(
                "INSERT INTO audit_events(sequence, payload_json, previous_hash, event_hash) VALUES (?, ?, ?, ?)",
                (sequence, encoded, previous_hash, event_hash),
            )
            return event_hash

    def verify(self) -> bool:
        previous_hash = ""
        with self._connect() as connection:
            rows = connection.execute("SELECT sequence, payload_json, previous_hash, event_hash FROM audit_events ORDER BY sequence").fetchall()
        for expected_sequence, row in enumerate(rows, start=1):
            if row["sequence"] != expected_sequence or row["previous_hash"] != previous_hash:
                return False
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                return False
            expected_hash = _canonical_digest({"sequence": expected_sequence, "previousHash": previous_hash, "payload": payload})
            if row["event_hash"] != expected_hash:
                return False
            previous_hash = row["event_hash"]
        return True
