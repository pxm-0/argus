"""Fail-closed Argus V1 entity classification and SQLite repository primitives."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REALMS = {"unclassified", "personal", "work"}
ZONES = {"legacy", "sandbox", "managed"}
STAGES = {"none", "dev", "staging", "production"}
DOMAIN_KINDS = {"management", "legacy", "workload"}


class StateError(ValueError):
    """Raised when an entity cannot be safely represented or persisted."""


def authorize_relationship(source_domain: str, target_domain: str, relation: str, *, authenticated_gateway: bool = False) -> None:
    """Reject resource sharing across trust domains unless an explicit gateway mediates it."""
    if not source_domain or not target_domain or not relation:
        raise StateError("relationship source, target, and type are required")
    if source_domain == target_domain:
        return
    if relation != "service-gateway" or not authenticated_gateway:
        raise StateError("cross-domain resources require an authenticated explicit service gateway")


def authorize_mutation(**dependencies: bool) -> None:
    """Fail closed whenever a mandatory mutation dependency is unavailable."""
    required = {"policy", "store", "authorization", "freshness", "observation", "reconciliation", "audit"}
    unknown = set(dependencies) - required
    missing = required - set(dependencies)
    failed = sorted(name for name in required if not dependencies.get(name, False))
    if unknown or missing or failed:
        detail = ", ".join(sorted(unknown | missing | set(failed)))
        raise StateError(f"mutation denied: unavailable dependency {detail}")


def legacy_workload_snapshot(workloads: list[dict[str, Any]], classifications: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Map legacy registry entries into quarantined M1 project entities."""
    result = []
    for workload in workloads:
        workload_id = str(workload.get("id", ""))
        classification = classifications.get(workload_id)
        if not workload_id or not isinstance(classification, dict):
            raise StateError("every legacy workload requires a quarantine classification")
        state = Classification(
            classification.get("realm"), classification.get("zone"), classification.get("stage"),
            str(classification.get("trustDomain", "")), "legacy",
        )
        entity_state = EntityState(state, state, state).as_dict()
        result.append({"id": workload_id, "kind": "project", "state": entity_state})
    return result


def _canonical_digest(value: Any) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_audit_checkpoint(payload: dict[str, Any]) -> bool:
    """Validate the schema and self-hash of a transportable audit checkpoint."""
    if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "sequence", "eventHash", "checkpointHash"}:
        return False
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("sequence"), int) or payload["sequence"] < 0:
        return False
    if not isinstance(payload.get("eventHash"), str) or not isinstance(payload.get("checkpointHash"), str):
        return False
    expected = _canonical_digest({key: payload[key] for key in ("schemaVersion", "sequence", "eventHash")})
    return payload["checkpointHash"] == expected


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json_replace(path: Path, value: dict[str, Any]) -> None:
    """Durably replace a small control record without leaving a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class AtomicJsonStore:
    """Single-writer compatibility store with a durable write-ahead journal."""

    def __init__(self, path: Path, journal_path: Path, *, fault_hook: Callable[[str], None] | None = None):
        self.path = path
        self.journal_path = journal_path
        self.fault_hook = fault_hook
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    def _fault(self, boundary: str) -> None:
        """Test-only crash injection after a durable write boundary."""
        if self.fault_hook is not None:
            self.fault_hook(boundary)

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
        self._fault("after-prepared")
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(replacement, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._fault("after-json-fsync")
            os.replace(temporary, self.path)
            _sync_directory(self.path.parent)
            self._fault("after-replace")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._append({"phase": "COMMITTED", "transactionId": transaction_id})
        self._fault("after-committed")
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

    def import_snapshot(self, entities: list[dict[str, Any]]) -> None:
        """Import a complete shadow snapshot only when every record is valid."""
        validated: list[tuple[str, str, EntityState]] = []
        def classification(value: dict[str, Any]) -> Classification:
            return Classification(
                realm=value.get("realm"),
                zone=value.get("zone"),
                stage=value.get("stage"),
                trust_domain=str(value.get("trustDomain", "")),
                domain_kind=str(value.get("domainKind", "")),
            )
        for entity in entities:
            try:
                state = EntityState(
                    declared=classification(entity["state"]["declared"]),
                    observed=classification(entity["state"]["observed"]),
                    effective=classification(entity["state"]["effective"]),
                )
                validated.append((str(entity["id"]), str(entity["kind"]), state))
            except (KeyError, TypeError) as exc:
                raise StateError("snapshot entity is malformed") from exc
        if len({item[0] for item in validated}) != len(validated):
            raise StateError("snapshot contains duplicate entity IDs")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM entities")
            for entity_id, entity_kind, state in validated:
                connection.execute(
                    "INSERT INTO entities(entity_id, entity_kind, revision, state_json) VALUES (?, ?, 1, ?)",
                    (entity_id, entity_kind, json.dumps(state.as_dict(), separators=(",", ":"), sort_keys=True)),
                )

    def semantic_parity(self, snapshot: list[dict[str, Any]]) -> bool:
        expected = sorted(
            [{"id": str(item.get("id")), "kind": str(item.get("kind")), "state": item.get("state")} for item in snapshot],
            key=lambda item: item["id"],
        )
        with self._connect() as connection:
            rows = connection.execute("SELECT entity_id, entity_kind, state_json FROM entities ORDER BY entity_id").fetchall()
        actual = [{"id": row["entity_id"], "kind": row["entity_kind"], "state": json.loads(row["state_json"])} for row in rows]
        return actual == expected


class StoreCutover:
    """Durably coordinate one-way SQLite activation with a rollback checkpoint."""

    def __init__(self, repository: SQLiteRepository, checkpoint_path: Path):
        self.repository = repository
        self.checkpoint_path = checkpoint_path

    def _read(self) -> dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {"phase": "JSON_ACTIVE"}
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError("cutover checkpoint is malformed") from exc
        if not isinstance(value, dict) or value.get("schemaVersion") != 1 or value.get("phase") not in {"PREPARED", "SQLITE_ACTIVE", "ROLLED_BACK"}:
            raise StateError("cutover checkpoint has an invalid schema")
        return value

    def prepare(self, snapshot: list[dict[str, Any]], *, journal_digest: str) -> dict[str, Any]:
        """Record a parity-proven candidate before pausing legacy writes."""
        if not journal_digest.startswith("sha256:"):
            raise StateError("cutover requires a journal digest")
        if self._read()["phase"] != "JSON_ACTIVE":
            raise StateError("cutover is already prepared, active, or rolled back")
        if not self.repository.semantic_parity(snapshot):
            raise StateError("SQLite shadow store does not have semantic parity")
        checkpoint = {
            "schemaVersion": 1,
            "phase": "PREPARED",
            "journalDigest": journal_digest,
            "snapshotDigest": _canonical_digest(snapshot),
            "snapshot": snapshot,
        }
        _atomic_json_replace(self.checkpoint_path, checkpoint)
        return checkpoint

    def activate(self, snapshot: list[dict[str, Any]], *, journal_digest: str) -> dict[str, Any]:
        """Activate SQLite only after the final paused-write replay still matches."""
        checkpoint = self._read()
        if checkpoint["phase"] != "PREPARED":
            raise StateError("SQLite activation requires a prepared checkpoint")
        if journal_digest != checkpoint.get("journalDigest") or _canonical_digest(snapshot) != checkpoint.get("snapshotDigest"):
            raise StateError("cutover final replay differs from the prepared checkpoint")
        if not self.repository.semantic_parity(snapshot):
            raise StateError("SQLite final replay does not have semantic parity")
        active = {**checkpoint, "phase": "SQLITE_ACTIVE"}
        _atomic_json_replace(self.checkpoint_path, active)
        return active

    def rollback(self) -> list[dict[str, Any]]:
        """Return the retained JSON snapshot only while parity still holds."""
        checkpoint = self._read()
        if checkpoint["phase"] != "SQLITE_ACTIVE":
            raise StateError("rollback requires active SQLite")
        snapshot = checkpoint.get("snapshot")
        if not isinstance(snapshot, list) or _canonical_digest(snapshot) != checkpoint.get("snapshotDigest"):
            raise StateError("rollback checkpoint snapshot is invalid")
        if not self.repository.semantic_parity(snapshot):
            raise StateError("SQLite changed after activation; rollback is unsafe")
        _atomic_json_replace(self.checkpoint_path, {**checkpoint, "phase": "ROLLED_BACK"})
        return snapshot


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

    def _events(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload_json FROM audit_events ORDER BY sequence").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def has_correlation_outcome(self, correlation_id: str) -> bool:
        """Return whether a durable non-intent outcome already exists."""
        return any(
            event.get("correlationId") == correlation_id and event.get("outcome") != "intent"
            for event in self._events()
        )

    def begin_break_glass(self, *, actor: str, target: str, trust_domain: str, operation: str, correlation_id: str, bypass_non_waivable: bool = False) -> str:
        if bypass_non_waivable:
            raise StateError("break-glass cannot bypass non-waivable isolation or exposure controls")
        if not correlation_id:
            raise StateError("break-glass requires a correlation ID")
        return self.append(
            {
                "actor": actor,
                "operation": operation,
                "outcome": "intent",
                "target": target,
                "trustDomain": trust_domain,
                "correlationId": correlation_id,
                "breakGlass": True,
            }
        )

    def complete_break_glass(self, *, actor: str, target: str, trust_domain: str, operation: str, correlation_id: str, outcome: str) -> str:
        if outcome not in {"accepted", "denied", "error", "rolled-back"}:
            raise StateError("break-glass outcome is invalid")
        intents = {event.get("correlationId") for event in self._events() if event.get("breakGlass") and event.get("outcome") == "intent"}
        if correlation_id not in intents:
            raise StateError("break-glass outcome has no durable intent")
        return self.append(
            {
                "actor": actor,
                "operation": operation,
                "outcome": outcome,
                "target": target,
                "trustDomain": trust_domain,
                "correlationId": correlation_id,
                "breakGlass": True,
            }
        )

    def reconcile_abandoned_break_glass(self, *, actor: str) -> list[str]:
        events = self._events()
        intents = {event.get("correlationId") for event in events if event.get("breakGlass") and event.get("outcome") == "intent"}
        completed = {event.get("correlationId") for event in events if event.get("breakGlass") and event.get("outcome") != "intent"}
        abandoned = sorted(correlation for correlation in intents - completed if isinstance(correlation, str))
        for correlation_id in abandoned:
            intent = next(event for event in events if event.get("correlationId") == correlation_id and event.get("outcome") == "intent")
            self.complete_break_glass(
                actor=actor,
                target=str(intent["target"]),
                trust_domain=str(intent["trustDomain"]),
                operation=str(intent["operation"]),
                correlation_id=correlation_id,
                outcome="error",
            )
        return abandoned

    def checkpoint(self) -> dict[str, Any]:
        """Return a deterministic, transport-neutral off-host anchor payload."""
        with self._connect() as connection:
            row = connection.execute("SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
        sequence = 0 if row is None else int(row["sequence"])
        event_hash = "" if row is None else str(row["event_hash"])
        payload = {"schemaVersion": 1, "sequence": sequence, "eventHash": event_hash}
        return {**payload, "checkpointHash": _canonical_digest(payload)}


class PrivacyMutationWriter:
    """Dual-schema privacy writer with a replayable, fail-closed journal."""

    def __init__(self, privacy_path: Path, state_path: Path, ledger_path: Path, journal_path: Path, *, fault_hook: Callable[[str], None] | None = None):
        self.privacy_path = privacy_path
        self.state_path = state_path
        self.ledger = AuditLedger(ledger_path)
        self.journal_path = journal_path
        self.fault_hook = fault_hook
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS privacy_projection (workload_id TEXT PRIMARY KEY, entry_json TEXT NOT NULL)")

    def _fault(self, boundary: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(boundary)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.state_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _read_privacy(self) -> dict[str, Any]:
        try:
            value = json.loads(self.privacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError("privacy compatibility store is malformed") from exc
        if not isinstance(value, dict) or not isinstance(value.get("workloads"), dict):
            raise StateError("privacy compatibility store has an invalid schema")
        return value

    def _append(self, record: dict[str, Any]) -> None:
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(self.journal_path.parent)

    def _project(self, privacy: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM privacy_projection")
            connection.executemany(
                "INSERT INTO privacy_projection(workload_id, entry_json) VALUES (?, ?)",
                [(workload_id, json.dumps(entry, sort_keys=True, separators=(",", ":"))) for workload_id, entry in privacy["workloads"].items()],
            )

    def _parity(self, privacy: dict[str, Any]) -> bool:
        expected = sorted((key, json.dumps(value, sort_keys=True, separators=(",", ":"))) for key, value in privacy["workloads"].items())
        with self._connect() as connection:
            actual = [(str(row["workload_id"]), str(row["entry_json"])) for row in connection.execute("SELECT workload_id, entry_json FROM privacy_projection ORDER BY workload_id")]
        return actual == expected

    def recover(self) -> None:
        """Complete only a prepared mutation whose JSON replacement is present."""
        if not self.journal_path.exists():
            return
        prepared: dict[str, dict[str, Any]] = {}
        committed: set[str] = set()
        aborted: set[str] = set()
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                transaction_id = str(record["transactionId"])
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise StateError("privacy writer journal is malformed") from exc
            if record.get("phase") == "PREPARED":
                prepared[transaction_id] = record
            elif record.get("phase") == "COMMITTED":
                committed.add(transaction_id)
            elif record.get("phase") == "ABORTED":
                aborted.add(transaction_id)
        current = self._read_privacy()
        for transaction_id, record in prepared.items():
            if transaction_id in committed or transaction_id in aborted:
                continue
            if record.get("privacyChecksum") != _canonical_digest(current):
                if record.get("previousChecksum") != _canonical_digest(current):
                    raise StateError("privacy writer has an unresolved mutation; refusing a divergent write")
                if not self.ledger.has_correlation_outcome(transaction_id):
                    self.ledger.append({**record["outcome"], "outcome": "error"})
                self._append({"phase": "ABORTED", "transactionId": transaction_id})
                continue
            self._project(current)
            if not self._parity(current):
                raise StateError("privacy writer replay did not restore parity")
            if not self.ledger.has_correlation_outcome(transaction_id):
                self.ledger.append(record["outcome"])
            self._append({"phase": "COMMITTED", "transactionId": transaction_id})

    def set_privacy(self, *, workload_id: str, privacy_value: str, reason: str, actor: str, timestamp: str) -> tuple[str, str]:
        if not workload_id or not reason or not actor:
            raise StateError("privacy mutation requires workload, reason, and actor")
        authorize_mutation(policy=True, store=True, authorization=True, freshness=True, observation=True, reconciliation=True, audit=self.ledger.verify())
        self.recover()
        current = self._read_privacy()
        if privacy_value not in current.get("states", []):
            raise StateError("invalid privacy state")
        old = str(current["workloads"].get(workload_id, {}).get("privacy", current.get("defaultPrivacy", "unclassified")))
        replacement = json.loads(json.dumps(current))
        replacement["workloads"][workload_id] = {"privacy": privacy_value, "reason": reason, "updatedAt": timestamp, "updatedBy": actor}
        transaction_id = str(uuid.uuid4())
        intent = {"actor": actor, "operation": "privacy.set", "outcome": "intent", "target": workload_id, "trustDomain": "legacy-rootful", "correlationId": transaction_id}
        outcome = {**intent, "outcome": "accepted", "from": old, "to": privacy_value}
        self.ledger.append(intent)
        self._append({"phase": "PREPARED", "transactionId": transaction_id, "previousChecksum": _canonical_digest(current), "privacyChecksum": _canonical_digest(replacement), "outcome": outcome})
        self._fault("privacy-after-prepared")
        _atomic_json_replace(self.privacy_path, replacement)
        self._fault("privacy-after-json")
        self._project(replacement)
        self._fault("privacy-after-projection")
        if not self._parity(replacement):
            raise StateError("privacy writer refused to complete without JSON/SQLite parity")
        self.ledger.append(outcome)
        self._fault("privacy-after-outcome")
        self._append({"phase": "COMMITTED", "transactionId": transaction_id})
        self._fault("privacy-after-committed")
        return old, privacy_value


class AccessMutationWriter:
    """Dual-schema writer for policy-approved access state transitions."""

    def __init__(self, access_path: Path, state_path: Path, ledger_path: Path, journal_path: Path, *, fault_hook: Callable[[str], None] | None = None):
        self.access_path = access_path
        self.state_path = state_path
        self.ledger = AuditLedger(ledger_path)
        self.journal_path = journal_path
        self.fault_hook = fault_hook
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS access_projection (workload_id TEXT PRIMARY KEY, entry_json TEXT NOT NULL)")

    def _fault(self, boundary: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(boundary)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.state_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _read_access(self) -> dict[str, Any]:
        try:
            value = json.loads(self.access_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError("access compatibility store is malformed") from exc
        if not isinstance(value, dict) or not isinstance(value.get("workloads"), dict):
            raise StateError("access compatibility store has an invalid schema")
        return value

    def _append(self, record: dict[str, Any]) -> None:
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(self.journal_path.parent)

    def _project(self, access: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM access_projection")
            connection.executemany(
                "INSERT INTO access_projection(workload_id, entry_json) VALUES (?, ?)",
                [(workload_id, json.dumps(entry, sort_keys=True, separators=(",", ":"))) for workload_id, entry in access["workloads"].items()],
            )

    def _parity(self, access: dict[str, Any]) -> bool:
        expected = sorted((key, json.dumps(value, sort_keys=True, separators=(",", ":"))) for key, value in access["workloads"].items())
        with self._connect() as connection:
            actual = [(str(row["workload_id"]), str(row["entry_json"])) for row in connection.execute("SELECT workload_id, entry_json FROM access_projection ORDER BY workload_id")]
        return actual == expected

    def _projected_entry(self, workload_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT entry_json FROM access_projection WHERE workload_id = ?", (workload_id,)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row["entry_json"]))
        except json.JSONDecodeError as exc:
            raise StateError("access projection entry is malformed") from exc
        if not isinstance(value, dict):
            raise StateError("access projection entry has an invalid schema")
        return value

    def recover(self) -> None:
        if not self.journal_path.exists():
            return
        prepared: dict[str, dict[str, Any]] = {}
        committed: set[str] = set()
        aborted: set[str] = set()
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                transaction_id = str(record["transactionId"])
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise StateError("access writer journal is malformed") from exc
            if record.get("phase") == "PREPARED":
                prepared[transaction_id] = record
            elif record.get("phase") == "COMMITTED":
                committed.add(transaction_id)
            elif record.get("phase") == "ABORTED":
                aborted.add(transaction_id)
        current = self._read_access()
        for transaction_id, record in prepared.items():
            if transaction_id in committed or transaction_id in aborted:
                continue
            if record.get("accessChecksum") != _canonical_digest(current):
                if record.get("previousChecksum") != _canonical_digest(current):
                    raise StateError("access writer has an unresolved mutation; refusing a divergent write")
                if not self.ledger.has_correlation_outcome(transaction_id):
                    self.ledger.append({**record["outcome"], "outcome": "error"})
                self._append({"phase": "ABORTED", "transactionId": transaction_id})
                continue
            self._project(current)
            if not self._parity(current):
                raise StateError("access writer replay did not restore parity")
            if not self.ledger.has_correlation_outcome(transaction_id):
                self.ledger.append(record["outcome"])
            self._append({"phase": "COMMITTED", "transactionId": transaction_id})

    def apply(self, *, workload_id: str, desired: str, decision: dict[str, Any], actor: str, timestamp: str) -> dict[str, Any]:
        if not workload_id or not actor or not decision.get("allowed"):
            raise StateError("access writer requires an allowed policy decision")
        authorize_mutation(policy=True, store=True, authorization=True, freshness=True, observation=True, reconciliation=True, audit=self.ledger.verify())
        self.recover()
        current = self._read_access()
        if desired not in current.get("states", []) or workload_id not in current["workloads"]:
            raise StateError("invalid access workload or state")
        before = dict(current["workloads"][workload_id])
        replacement = json.loads(json.dumps(current))
        entry = replacement["workloads"][workload_id]
        entry["desired"] = desired
        if decision.get("plannedOnly"):
            entry["lastError"] = str(decision.get("reason", ""))
        else:
            entry["effective"] = decision.get("effective")
            entry["lastError"] = ""
        entry["lastAppliedAt"] = timestamp
        transaction_id = str(uuid.uuid4())
        intent = {"actor": actor, "operation": "access.apply", "outcome": "intent", "target": workload_id, "trustDomain": "legacy-rootful", "correlationId": transaction_id}
        outcome = {**intent, "outcome": "accepted", "oldDesired": str(before.get("desired", "")), "desired": desired, "oldEffective": str(before.get("effective", "")), "effective": str(entry.get("effective", "")), "plannedOnly": bool(decision.get("plannedOnly"))}
        self.ledger.append(intent)
        self._append({"phase": "PREPARED", "transactionId": transaction_id, "previousChecksum": _canonical_digest(current), "accessChecksum": _canonical_digest(replacement), "outcome": outcome})
        self._fault("access-after-prepared")
        _atomic_json_replace(self.access_path, replacement)
        self._fault("access-after-json")
        self._project(replacement)
        self._fault("access-after-projection")
        if not self._parity(replacement):
            raise StateError("access writer refused to complete without JSON/SQLite parity")
        self.ledger.append(outcome)
        self._fault("access-after-outcome")
        self._append({"phase": "COMMITTED", "transactionId": transaction_id})
        self._fault("access-after-committed")
        return {"oldDesired": before.get("desired"), "oldEffective": before.get("effective"), "effective": entry.get("effective"), "plannedOnly": bool(decision.get("plannedOnly")), "reason": str(decision.get("reason", ""))}

    def reconcile_deployed(self, *, workload_id: str, expected_before: dict[str, Any], expected_after: dict[str, Any], actor: str, trust_domain: str) -> dict[str, Any]:
        """Reconcile one reviewed Git deployment into the private projection."""
        if not workload_id or not actor or not trust_domain or not isinstance(expected_before, dict) or not isinstance(expected_after, dict):
            raise StateError("deployed access reconciliation requires exact before and after state")
        authorize_mutation(policy=True, store=True, authorization=True, freshness=True, observation=True, reconciliation=True, audit=self.ledger.verify())
        self.recover()
        current = self._read_access()
        if current.get("workloads", {}).get(workload_id) != expected_after:
            raise StateError("deployed access state does not match the reviewed transition")
        projected = self._projected_entry(workload_id)
        if projected == expected_after:
            if not self._parity(current):
                raise StateError("access projection differs outside the reviewed transition")
            return {"reconciled": True, "alreadyApplied": True}
        if projected != expected_before:
            raise StateError("access projection does not match the reviewed pre-deployment state")
        transaction_id = str(uuid.uuid4())
        intent = {"actor": actor, "operation": "access.reconcile-deployed", "outcome": "intent", "target": workload_id, "trustDomain": trust_domain, "correlationId": transaction_id}
        outcome = {**intent, "outcome": "accepted", "oldEffective": str(expected_before.get("effective", "")), "effective": str(expected_after.get("effective", ""))}
        self.ledger.append(intent)
        self._append({"phase": "PREPARED", "transactionId": transaction_id, "previousChecksum": _canonical_digest(current), "accessChecksum": _canonical_digest(current), "outcome": outcome})
        self._fault("access-reconcile-after-prepared")
        self._project(current)
        self._fault("access-reconcile-after-projection")
        if not self._parity(current):
            raise StateError("deployed access reconciliation did not restore parity")
        self.ledger.append(outcome)
        self._fault("access-reconcile-after-outcome")
        self._append({"phase": "COMMITTED", "transactionId": transaction_id})
        self._fault("access-reconcile-after-committed")
        return {"reconciled": True, "alreadyApplied": False}
