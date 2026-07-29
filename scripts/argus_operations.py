from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


MUTATIONS = {"workload.restart", "backup.create", "access.apply"}
TYPED_OPERATIONS = {"health.refresh", "logs.preview", *MUTATIONS}
TERMINAL_STATES = {"succeeded", "failed", "rolled-back", "denied", "expired", "indeterminate"}
ALLOWED_STATES = {
    "planned", "awaiting-approval", "queued", "running", "succeeded", "failed",
    "rollback-running", "rolled-back", "denied", "expired", "indeterminate",
}
ALLOWED_TRANSITIONS = {
    "planned": {"awaiting-approval", "denied", "expired"},
    "awaiting-approval": {"queued", "denied", "expired"},
    "queued": {"running", "denied", "expired"},
    "running": {"succeeded", "failed", "rollback-running", "indeterminate"},
    "failed": {"rollback-running", "indeterminate"},
    "rollback-running": {"rolled-back", "indeterminate"},
}
SCHEMA_VERSION = 1
STALE_HEARTBEAT_SECONDS = 30
EVENT_RETENTION_SECONDS = 365 * 24 * 60 * 60
TIMESTAMP_FIELDS = {"approved_at", "started_at", "heartbeat_at", "finished_at"}


def format_timestamp(value: int | float | str | None = None) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include UTC timezone")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    instant = time.time() if value is None else float(value)
    return datetime.fromtimestamp(instant, tz=UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> int:
    if not value:
        return 0
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def operation_result_failure(operation_type: str, result: dict[str, Any]) -> tuple[str, str] | None:
    """Classify failures that are returned as redacted typed-operation evidence."""
    if operation_type != "health.refresh":
        return None
    health = result.get("health")
    if not isinstance(health, dict):
        return "health-evidence-invalid", "Runtime health evidence was invalid."
    status = str(health.get("status", "")).lower()
    if status in {"unavailable", "invalid"}:
        return f"health-evidence-{status}", f"Runtime health evidence was {status}."
    return None


class OperationConflict(Exception):
    pass


class OperationLedger:
    def __init__(
        self,
        path: Path,
        *,
        recover_on_init: bool = False,
        require_existing: bool = False,
        migrate_schema: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.clock = clock
        self.migrate_schema = migrate_schema
        self.manage_permissions = not require_existing
        if require_existing and not self.path.is_file():
            raise RuntimeError("operation ledger must be initialized by the worker")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if recover_on_init:
            self.recover_running()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _now(self) -> int:
        return int(self.clock())

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _backup_before_migration(self, source: sqlite3.Connection, version: int) -> None:
        tables = source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if not tables:
            return
        backup_path = self.path.with_name(f"{self.path.name}.pre-v{version + 1}.bak")
        if backup_path.exists():
            return
        descriptor, temporary = tempfile.mkstemp(prefix=f".{backup_path.name}.", dir=backup_path.parent)
        os.close(descriptor)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
            destination.close()
            os.chmod(temporary, 0o600)
            os.replace(temporary, backup_path)
        finally:
            try:
                destination.close()
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                workload_id TEXT NOT NULL,
                trust_domain TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                parameters_digest TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                preview_digest TEXT NOT NULL,
                expected_revision TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN (
                        'planned', 'awaiting-approval', 'queued', 'running',
                        'succeeded', 'failed', 'rollback-running', 'rolled-back',
                        'denied', 'expired', 'indeterminate'
                    )
                ),
                created_at TEXT NOT NULL,
                approved_at TEXT,
                started_at TEXT,
                heartbeat_at TEXT,
                finished_at TEXT,
                error_class TEXT,
                redacted_summary TEXT NOT NULL DEFAULT '',
                redacted_result_json TEXT NOT NULL DEFAULT '{}',
                rollback_operation_id TEXT REFERENCES operations(operation_id)
            )
            """,
            """
            CREATE UNIQUE INDEX one_mutation_per_workload
              ON operations(workload_id)
              WHERE operation_type IN (
                  'workload.restart', 'backup.create', 'access.apply'
              )
                AND state IN (
                    'awaiting-approval', 'queued', 'running',
                    'rollback-running', 'indeterminate'
                )
            """,
            """
            CREATE TABLE operation_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL REFERENCES operations(operation_id),
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                redacted_detail TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE INDEX operation_events_operation
              ON operation_events(operation_id, sequence)
            """,
            """
            CREATE TABLE IF NOT EXISTS used_nonces (
                nonce TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL
            )
            """,
        )
        for statement in statements:
            connection.execute(statement)

    def _migrate_v1(self, connection: sqlite3.Connection) -> None:
        required = {
            "operation_id",
            "idempotency_key",
            "workload_id",
            "trust_domain",
            "operation_type",
            "requested_by",
            "parameters_json",
            "parameters_digest",
            "preview_json",
            "preview_digest",
            "expected_revision",
            "policy_version",
            "state",
            "created_at",
            "approved_at",
            "started_at",
            "heartbeat_at",
            "finished_at",
            "error_class",
            "redacted_summary",
            "redacted_result_json",
            "rollback_operation_id",
        }
        if not self._table_exists(connection, "operations"):
            self._create_schema(connection)
            return
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(operations)").fetchall()
        }
        if required.issubset(columns):
            connection.execute("DROP INDEX IF EXISTS one_active_mutation_per_workload")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS one_mutation_per_workload
                  ON operations(workload_id)
                  WHERE operation_type IN (
                      'workload.restart', 'backup.create', 'access.apply'
                  )
                    AND state IN (
                        'awaiting-approval', 'queued', 'running',
                        'rollback-running', 'indeterminate'
                    )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operation_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    redacted_detail TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS operation_events_operation
                  ON operation_events(operation_id, sequence)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS used_nonces (
                    nonce TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            return

        rows = connection.execute("SELECT * FROM operations").fetchall()
        connection.execute("DROP INDEX IF EXISTS one_active_mutation_per_workload")
        connection.execute("DROP INDEX IF EXISTS one_mutation_per_workload")
        connection.execute("DROP TABLE IF EXISTS operation_events")
        connection.execute("ALTER TABLE operations RENAME TO operations_legacy")
        self._create_schema(connection)
        rollback_links: list[tuple[str, str]] = []
        for row in rows:
            legacy = dict(row)
            parameters_json = str(legacy.get("parameters_json") or "{}")
            try:
                parameters = json.loads(parameters_json)
            except json.JSONDecodeError:
                parameters = {}
                parameters_json = canonical_json(parameters)
            preview = {
                "workloadId": legacy["workload_id"],
                "trustDomain": legacy["trust_domain"],
                "operationType": legacy["operation_type"],
                "parameters": parameters,
                "expectedRevision": legacy["expected_revision"],
                "policyVersion": legacy["policy_version"],
            }
            created_at = format_timestamp(legacy.get("created_at") or self._now())
            started_at = (
                format_timestamp(legacy["started_at"])
                if legacy.get("started_at") is not None
                else None
            )
            connection.execute(
                """
                INSERT INTO operations (
                    operation_id, idempotency_key, workload_id, trust_domain,
                    operation_type, requested_by, parameters_json,
                    parameters_digest, preview_json, preview_digest,
                    expected_revision, policy_version, state, created_at,
                    approved_at, started_at, heartbeat_at, finished_at,
                    error_class, redacted_summary, redacted_result_json,
                    rollback_operation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    legacy["operation_id"],
                    legacy["idempotency_key"],
                    legacy["workload_id"],
                    legacy["trust_domain"],
                    legacy["operation_type"],
                    legacy["requested_by"],
                    parameters_json,
                    digest(parameters),
                    canonical_json(preview),
                    legacy["preview_digest"],
                    legacy["expected_revision"],
                    legacy["policy_version"],
                    legacy["state"],
                    created_at,
                    format_timestamp(legacy["approved_at"])
                    if legacy.get("approved_at") is not None
                    else None,
                    started_at,
                    started_at if legacy["state"] in {"running", "rollback-running"} else None,
                    format_timestamp(legacy["finished_at"])
                    if legacy.get("finished_at") is not None
                    else None,
                    legacy.get("error_class"),
                    str(legacy.get("redacted_summary") or ""),
                    str(legacy.get("redacted_result_json") or "{}"),
                ),
            )
            connection.execute(
                """
                INSERT INTO operation_events (
                    operation_id, state, created_at, redacted_detail
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    legacy["operation_id"],
                    legacy["state"],
                    created_at,
                    "Imported during operation-ledger schema migration.",
                ),
            )
            if legacy.get("rollback_operation_id"):
                rollback_links.append(
                    (str(legacy["rollback_operation_id"]), str(legacy["operation_id"]))
                )
        for rollback_operation_id, operation_id in rollback_links:
            connection.execute(
                """
                UPDATE operations SET rollback_operation_id = ?
                WHERE operation_id = ?
                """,
                (rollback_operation_id, operation_id),
            )
        connection.execute("DROP TABLE operations_legacy")

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        required_tables = {
            "operations": {
                "operation_id",
                "idempotency_key",
                "workload_id",
                "trust_domain",
                "operation_type",
                "requested_by",
                "parameters_json",
                "parameters_digest",
                "preview_json",
                "preview_digest",
                "expected_revision",
                "policy_version",
                "state",
                "created_at",
                "approved_at",
                "started_at",
                "heartbeat_at",
                "finished_at",
                "error_class",
                "redacted_summary",
                "redacted_result_json",
                "rollback_operation_id",
            },
            "operation_events": {
                "sequence",
                "operation_id",
                "state",
                "created_at",
                "redacted_detail",
            },
            "used_nonces": {"nonce", "expires_at"},
        }
        for table, required_columns in required_tables.items():
            if not self._table_exists(connection, table):
                raise RuntimeError(
                    f"operation ledger schema {SCHEMA_VERSION} is missing table {table}"
                )
            columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing = required_columns - columns
            if missing:
                raise RuntimeError(
                    "operation ledger schema "
                    f"{SCHEMA_VERSION} is missing {table} columns: "
                    f"{','.join(sorted(missing))}"
                )
        indexes = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        for index in {"one_mutation_per_workload", "operation_events_operation"}:
            if index not in indexes:
                raise RuntimeError(
                    f"operation ledger schema {SCHEMA_VERSION} is missing index {index}"
                )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"operation ledger schema {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version < SCHEMA_VERSION:
                if not self.migrate_schema:
                    raise RuntimeError(
                        "operation ledger schema must be migrated by the worker"
                    )
                self._backup_before_migration(connection, version)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._migrate_v1(connection)
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            self._validate_schema(connection)
        if self.manage_permissions:
            os.chmod(self.path, 0o660)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["parameters"] = json.loads(result.pop("parameters_json"))
        result["preview"] = json.loads(result.pop("preview_json"))
        result["redactedResult"] = json.loads(result.pop("redacted_result_json"))
        return result

    @staticmethod
    def _idempotency_matches(
        operation: dict[str, Any],
        *,
        workload_id: str,
        trust_domain: str,
        operation_type: str,
        requested_by: str,
        parameters: dict[str, Any],
        preview_digest: str,
        expected_revision: str,
        policy_version: str,
    ) -> bool:
        expected = (
            workload_id,
            trust_domain,
            operation_type,
            requested_by,
            digest(parameters),
            preview_digest,
            expected_revision,
            policy_version,
        )
        actual = (
            operation["workload_id"],
            operation["trust_domain"],
            operation["operation_type"],
            operation["requested_by"],
            operation["parameters_digest"],
            operation["preview_digest"],
            operation["expected_revision"],
            operation["policy_version"],
        )
        return actual == expected

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        operation_id: str,
        state: str,
        created_at: str,
        detail: str = "",
    ) -> None:
        connection.execute(
            """
            INSERT INTO operation_events (
                operation_id, state, created_at, redacted_detail
            ) VALUES (?, ?, ?, ?)
            """,
            (operation_id, state, created_at, detail[:1000]),
        )

    def recover_running(self, *, stale_after_seconds: int = STALE_HEARTBEAT_SECONDS) -> int:
        cutoff = format_timestamp(self._now() - stale_after_seconds)
        finished_at = format_timestamp(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT operation_id FROM operations
                WHERE state IN ('running', 'rollback-running')
                  AND COALESCE(heartbeat_at, started_at, created_at) <= ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                operation_id = str(row["operation_id"])
                connection.execute(
                    """
                    UPDATE operations
                    SET state = 'indeterminate', finished_at = ?,
                        error_class = 'worker-recovery-timeout',
                        redacted_summary = ?
                    WHERE operation_id = ?
                      AND state IN ('running', 'rollback-running')
                    """,
                    (
                        finished_at,
                        "Outcome unknown after stale worker/agent heartbeat; no automatic retry.",
                        operation_id,
                    ),
                )
                self._event(
                    connection,
                    operation_id,
                    "indeterminate",
                    finished_at,
                    "Stale running operation recovered without redispatch.",
                )
            connection.commit()
        return len(rows)

    def create(
        self, *, workload_id: str, trust_domain: str, operation_type: str,
        requested_by: str, parameters: dict[str, Any], preview_digest: str,
        expected_revision: str, policy_version: str, idempotency_key: str,
        preview: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if operation_type not in TYPED_OPERATIONS:
            raise ValueError("unsupported operation type")
        if not idempotency_key:
            raise ValueError("idempotency key required")
        operation_id = str(uuid.uuid4())
        state = "awaiting-approval" if operation_type in MUTATIONS else "queued"
        created_at = format_timestamp(self._now())
        preview_payload = preview or {
            "workloadId": workload_id,
            "trustDomain": trust_domain,
            "operationType": operation_type,
            "parameters": parameters,
            "expectedRevision": expected_revision,
            "policyVersion": policy_version,
        }
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing_row = connection.execute(
                    "SELECT * FROM operations WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    connection.rollback()
                    existing = self._row(existing_row) or {}
                    if not self._idempotency_matches(
                        existing,
                        workload_id=workload_id,
                        trust_domain=trust_domain,
                        operation_type=operation_type,
                        requested_by=requested_by,
                        parameters=parameters,
                        preview_digest=preview_digest,
                        expected_revision=expected_revision,
                        policy_version=policy_version,
                    ):
                        raise OperationConflict(
                            "idempotency key is bound to a different operation intent"
                        )
                    return existing, False
                connection.execute(
                    """
                    INSERT INTO operations (
                        operation_id, idempotency_key, workload_id, trust_domain, operation_type,
                        requested_by, parameters_json, parameters_digest, preview_json,
                        preview_digest, expected_revision, policy_version, state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id, idempotency_key, workload_id, trust_domain, operation_type,
                        requested_by, canonical_json(parameters), digest(parameters),
                        canonical_json(preview_payload), preview_digest, expected_revision,
                        policy_version, state, created_at,
                    ),
                )
                self._event(connection, operation_id, state, created_at, "Operation intent persisted.")
                connection.commit()
        except sqlite3.IntegrityError as exc:
            existing = self.by_idempotency(idempotency_key)
            if existing:
                if not self._idempotency_matches(
                    existing,
                    workload_id=workload_id,
                    trust_domain=trust_domain,
                    operation_type=operation_type,
                    requested_by=requested_by,
                    parameters=parameters,
                    preview_digest=preview_digest,
                    expected_revision=expected_revision,
                    policy_version=policy_version,
                ):
                    raise OperationConflict(
                        "idempotency key is bound to a different operation intent"
                    ) from exc
                return existing, False
            if operation_type in MUTATIONS:
                with self._connect() as connection:
                    active = connection.execute(
                        """
                        SELECT 1 FROM operations
                        WHERE workload_id = ?
                          AND operation_type IN (
                              'workload.restart', 'backup.create', 'access.apply'
                          )
                          AND state IN (
                              'awaiting-approval', 'queued', 'running',
                              'rollback-running', 'indeterminate'
                          )
                        LIMIT 1
                        """,
                        (workload_id,),
                    ).fetchone()
                if active is not None:
                    raise OperationConflict(
                        "workload already has an active mutation"
                    ) from exc
            raise
        return self.get(operation_id) or {}, True

    def get(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
        return self._row(row)

    def by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
        return self._row(row)

    def list_for_workload(self, workload_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operations WHERE workload_id = ? ORDER BY created_at DESC, operation_id DESC",
                (workload_id,),
            ).fetchall()
        return [self._row(row) or {} for row in rows]

    def events(self, operation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, operation_id, state, created_at, redacted_detail
                FROM operation_events
                WHERE operation_id = ?
                ORDER BY sequence
                """,
                (operation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition(
        self,
        operation_id: str,
        expected: set[str],
        state: str,
        *,
        event_detail: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        if state not in ALLOWED_STATES:
            raise ValueError("invalid operation state")
        if not expected:
            raise ValueError("expected operation state required")
        invalid_sources = {
            source
            for source in expected
            if state not in ALLOWED_TRANSITIONS.get(source, set())
        }
        if invalid_sources:
            raise ValueError(
                f"invalid operation transition from {','.join(sorted(invalid_sources))} to {state}"
            )
        assignments = ["state = ?"]
        values: list[Any] = [state]
        for key in (
            "approved_at",
            "started_at",
            "heartbeat_at",
            "finished_at",
            "error_class",
            "redacted_summary",
            "redacted_result_json",
            "rollback_operation_id",
        ):
            if key in fields:
                assignments.append(f"{key} = ?")
                value = fields[key]
                values.append(
                    format_timestamp(value)
                    if key in TIMESTAMP_FIELDS and value is not None
                    else value
                )
        placeholders = ", ".join("?" for _ in expected)
        values.extend([operation_id, *sorted(expected)])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE operations SET {', '.join(assignments)} WHERE operation_id = ? AND state IN ({placeholders})",
                values,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise OperationConflict("operation state changed")
            self._event(
                connection,
                operation_id,
                state,
                format_timestamp(self._now()),
                event_detail,
            )
            connection.commit()
        return self.get(operation_id) or {}

    def list_queued(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE state = 'queued'
                ORDER BY created_at, operation_id
                """
            ).fetchall()
        return [self._row(row) or {} for row in rows]

    def claim(self, operation_id: str) -> dict[str, Any] | None:
        claimed_at = format_timestamp(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE operations
                SET state = 'running', started_at = ?, heartbeat_at = ?
                WHERE operation_id = ? AND state = 'queued'
                """,
                (claimed_at, claimed_at, operation_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            self._event(
                connection,
                operation_id,
                "running",
                claimed_at,
                "Claimed by operation worker.",
            )
            connection.commit()
        return self.get(operation_id)

    def claim_next(self) -> dict[str, Any] | None:
        queued = self.list_queued()
        if not queued:
            return None
        return self.claim(str(queued[0]["operation_id"]))

    def heartbeat(self, operation_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operations SET heartbeat_at = ?
                WHERE operation_id = ?
                  AND state IN ('running', 'rollback-running')
                """,
                (format_timestamp(self._now()), operation_id),
            )
        return cursor.rowcount == 1

    def mark_dispatch_indeterminate(self, operation_id: str) -> dict[str, Any]:
        return self.transition(
            operation_id,
            {"running"},
            "indeterminate",
            finished_at=self._now(),
            error_class="agent-dispatch-unconfirmed",
            redacted_summary="Agent dispatch could not be confirmed; operation was not retried.",
            event_detail="Agent dispatch acknowledgement was unavailable.",
        )

    def purge_events(self) -> int:
        cutoff = format_timestamp(self._now() - EVENT_RETENTION_SECONDS)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM operation_events WHERE created_at <= ?",
                (cutoff,),
            )
        return int(cursor.rowcount)

    def consume_nonce(self, nonce: str, expires_at: int) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM used_nonces WHERE expires_at <= ?", (self._now(),))
            try:
                connection.execute("INSERT INTO used_nonces VALUES (?, ?)", (nonce, expires_at))
            except sqlite3.IntegrityError:
                return False
        return True


class CapabilityCodec:
    """Domain-side capability codec. Keys belong in each agent's private runtime."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("domain capability key must be at least 32 bytes")
        self.key = key

    def issue(self, claims: dict[str, Any]) -> str:
        payload = canonical_json(claims).encode()
        signature = hmac.new(self.key, payload, hashlib.sha256).hexdigest()
        return f"{payload.hex()}.{signature}"

    def verify(self, token: str) -> dict[str, Any]:
        encoded, separator, signature = token.partition(".")
        if not separator:
            raise ValueError("malformed capability")
        try:
            payload = bytes.fromhex(encoded)
        except ValueError as exc:
            raise ValueError("malformed capability") from exc
        expected = hmac.new(self.key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid capability signature")
        return json.loads(payload)


class DomainAgent:
    def __init__(
        self, domain_id: str, ledger: OperationLedger, codec: CapabilityCodec,
        executor: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        policy_check: Callable[[str, str, dict[str, Any]], tuple[bool, str]],
        revision: Callable[[str], str],
    ) -> None:
        self.domain_id = domain_id
        self.ledger = ledger
        self.codec = codec
        self.executor = executor
        self.policy_check = policy_check
        self.revision = revision

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        claims = self.codec.verify(str(request.get("capability", "")))
        required = {
            "operator", "workload_id", "trust_domain", "operation_type", "parameters",
            "expected_revision", "preview_digest", "policy_version", "expires_at",
            "nonce", "idempotency_key",
        }
        if not required.issubset(claims):
            raise ValueError("incomplete capability")
        if claims["trust_domain"] != self.domain_id:
            raise ValueError("wrong capability domain")
        if claims["operation_type"] not in TYPED_OPERATIONS:
            raise ValueError("untyped operation")
        if int(claims["expires_at"]) <= int(time.time()):
            raise ValueError("expired capability")
        approved = {key: request.get(key) for key in ("workload_id", "trust_domain", "operation_type", "parameters", "expected_revision", "preview_digest", "policy_version", "idempotency_key")}
        claimed = {key: claims.get(key) for key in approved}
        if not hmac.compare_digest(digest(approved), digest(claimed)):
            raise ValueError("capability request mismatch")
        if self.revision(str(claims["workload_id"])) != claims["expected_revision"]:
            raise ValueError("stale canonical revision")
        preview = {
            "workloadId": claims["workload_id"],
            "trustDomain": claims["trust_domain"],
            "operationType": claims["operation_type"],
            "parameters": claims["parameters"],
            "expectedRevision": claims["expected_revision"],
            "policyVersion": claims["policy_version"],
        }
        if digest(preview) != claims["preview_digest"]:
            raise ValueError("preview digest mismatch")
        allowed, reason = self.policy_check(str(claims["workload_id"]), str(claims["operation_type"]), dict(claims["parameters"]))
        if not allowed:
            raise PermissionError(reason)
        if not self.ledger.consume_nonce(str(claims["nonce"]), int(claims["expires_at"])):
            raise ValueError("replayed capability")
        execution_parameters = dict(claims["parameters"])
        execution_parameters["_operator"] = str(claims["operator"])
        return self.executor(str(claims["operation_type"]), str(claims["workload_id"]), execution_parameters)


def capability_claims(operation: dict[str, Any], *, ttl_seconds: int = 60) -> dict[str, Any]:
    return {
        "operator": operation["requested_by"],
        "workload_id": operation["workload_id"],
        "trust_domain": operation["trust_domain"],
        "operation_type": operation["operation_type"],
        "parameters": operation["parameters"],
        "expected_revision": operation["expected_revision"],
        "preview_digest": operation["preview_digest"],
        "policy_version": operation["policy_version"],
        "expires_at": int(time.time()) + ttl_seconds,
        "nonce": secrets.token_urlsafe(24),
        "idempotency_key": operation["idempotency_key"],
    }
