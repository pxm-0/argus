from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from argus_sqlite import ClosingConnection


DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


MIGRATION_CHILD_OPERATIONS = {
    "migration.source-fence",
    "migration.target-prepare",
    "migration.target-start",
    "migration.route-switch",
    "migration.final-verify",
    "migration.target-stop",
    "migration.source-restore",
    "migration.source-verify",
}

# A parent migration is the durable authority record.  These operation types
# are created only by ``ensure_migration_child`` after that parent has crossed
# the dashboard approval boundary; they are never public API intents.
MIGRATION_OPERATION_PHASES = {
    "source-fencing": ("migration.source-fence", "source"),
    "target-preparing": ("migration.target-prepare", "target"),
    "target-starting": ("migration.target-start", "target"),
    "route-switching": ("migration.route-switch", "target"),
    "verifying": ("migration.final-verify", "target"),
    "rollback-target-stopping": ("migration.target-stop", "target"),
    "rollback-source-restoring": ("migration.source-restore", "source"),
    "rollback-verifying": ("migration.source-verify", "source"),
}

MIGRATION_PHASES = {
    "planned",
    "preflight",
    "awaiting-approval",
    "source-fencing",
    "source-fenced",
    "target-preparing",
    "target-starting",
    "target-verified",
    "route-switching",
    "authority-committed",
    "canonical-committed",
    "verifying",
    "succeeded",
    "failed",
    "denied",
    "expired",
    "indeterminate",
    "rollback-target-stopping",
    "rollback-source-restoring",
    "rollback-verifying",
    "rolled-back",
}
MIGRATION_TERMINAL_PHASES = {
    "succeeded", "failed", "denied", "expired", "indeterminate", "rolled-back"
}
MIGRATION_TRANSITIONS = {
    "planned": {"preflight", "failed", "denied", "expired"},
    "preflight": {"awaiting-approval", "failed", "denied", "expired"},
    "awaiting-approval": {"source-fencing", "denied", "expired"},
    "source-fencing": {"source-fenced", "failed", "indeterminate"},
    "source-fenced": {"target-preparing", "rollback-target-stopping", "indeterminate"},
    "target-preparing": {"target-starting", "rollback-target-stopping", "indeterminate"},
    "target-starting": {"target-verified", "rollback-target-stopping", "indeterminate"},
    "target-verified": {"route-switching", "rollback-target-stopping", "indeterminate"},
    "route-switching": {"authority-committed", "rollback-target-stopping", "indeterminate"},
    "authority-committed": {"canonical-committed", "rollback-target-stopping", "indeterminate"},
    "canonical-committed": {"verifying", "rollback-target-stopping", "indeterminate"},
    "verifying": {"succeeded", "rollback-target-stopping", "indeterminate"},
    # Completion is reversible through the same approval-bound parent.  The
    # rollback path still fences the target before restoring the source.
    "succeeded": {"rollback-target-stopping"},
    "rollback-target-stopping": {"rollback-source-restoring", "indeterminate"},
    "rollback-source-restoring": {"rollback-verifying", "indeterminate"},
    "rollback-verifying": {"rolled-back", "indeterminate"},
}

LIFECYCLE_MUTATIONS = {
    "workload.deploy", "workload.start", "workload.stop", "backup.restore",
    "migration.cutover", "migration.rollback", "production.promote",
    "production.rollback", *MIGRATION_CHILD_OPERATIONS,
}
PRIVILEGED_MUTATIONS = {
    "migration.cutover", "migration.rollback", "production.promote",
    "production.rollback", *MIGRATION_CHILD_OPERATIONS,
}
MUTATIONS = {"workload.restart", "backup.create", "access.apply", *LIFECYCLE_MUTATIONS}
TYPED_OPERATIONS = {"health.refresh", "logs.preview", "migration.preflight", *MUTATIONS}
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
SCHEMA_VERSION = 3
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


class OperationValidationError(ValueError):
    pass


def validate_typed_parameters(
    operation_type: str,
    parameters: dict[str, Any],
) -> None:
    schemas: dict[str, set[str]] = {
        "health.refresh": set(),
        "logs.preview": {"maxLines"},
        "migration.preflight": {"targetTrustDomain"},
        "workload.restart": {"healthTimeoutSeconds"},
        "backup.create": {"planRevision"},
        "workload.deploy": {"targetRevision"},
        "workload.start": set(),
        "workload.stop": set(),
        "backup.restore": {"artifactId"},
        "migration.cutover": {"preflightOperationId"},
        "migration.rollback": {"cutoverOperationId"},
        "production.promote": {"sourceOperationId", "targetTrustDomain"},
        "production.rollback": {"promotionOperationId"},
        "access.apply": {"desired"},
        "migration.source-fence": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.target-prepare": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.target-start": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.route-switch": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.final-verify": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.target-stop": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.source-restore": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
        "migration.source-verify": {
            "migrationId", "authorityEpoch", "sourceTrustDomain", "targetTrustDomain",
        },
    }
    if operation_type not in schemas:
        raise OperationValidationError("unsupported operation type")
    unknown = set(parameters) - schemas[operation_type]
    if unknown:
        raise OperationValidationError(
            f"unknown operation parameter(s): {','.join(sorted(unknown))}"
        )
    if operation_type == "logs.preview" and "maxLines" in parameters:
        max_lines = parameters["maxLines"]
        if (
            isinstance(max_lines, bool)
            or not isinstance(max_lines, int)
            or not 1 <= max_lines <= 100
        ):
            raise OperationValidationError("maxLines must be an integer from 1 to 100")
    if operation_type == "workload.restart" and "healthTimeoutSeconds" in parameters:
        timeout = parameters["healthTimeoutSeconds"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 300
        ):
            raise OperationValidationError(
                "healthTimeoutSeconds must be an integer from 1 to 300"
            )
    if operation_type == "backup.create" and "planRevision" in parameters:
        revision = parameters["planRevision"]
        if (
            not isinstance(revision, str)
            or len(revision) != 64
            or any(character not in "0123456789abcdef" for character in revision)
        ):
            raise OperationValidationError(
                "planRevision must be a lowercase SHA-256 digest"
            )
    if operation_type == "workload.deploy":
        revision = parameters.get("targetRevision")
        if not isinstance(revision, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
            raise OperationValidationError("targetRevision must be an immutable sha256 digest")
    required_strings = {
        "migration.preflight": "targetTrustDomain",
        "backup.restore": "artifactId",
        "production.promote": "targetTrustDomain",
    }
    required = required_strings.get(operation_type)
    if required and (not isinstance(parameters.get(required), str) or not parameters[required].strip()):
        raise OperationValidationError(f"{required} must be a non-empty string")
    for field in {"targetTrustDomain"} & set(parameters):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", str(parameters[field])):
            raise OperationValidationError(f"{field} must be a canonical trust-domain id")
    if operation_type == "backup.restore" and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(parameters["artifactId"])
    ):
        raise OperationValidationError("artifactId must be a canonical artifact id")
    references = {
        "migration.cutover": "preflightOperationId",
        "migration.rollback": "cutoverOperationId",
        "production.promote": "sourceOperationId",
        "production.rollback": "promotionOperationId",
    }
    reference = references.get(operation_type)
    if reference:
        try:
            uuid.UUID(str(parameters.get(reference, "")))
        except ValueError as exc:
            raise OperationValidationError(f"{reference} must be a UUID") from exc
    if operation_type == "access.apply":
        if parameters.get("desired") not in {"none", "local", "tailnet"}:
            raise OperationValidationError(
                "desired must be none, local, or tailnet"
            )
    if operation_type in MIGRATION_CHILD_OPERATIONS:
        for field in ("migrationId", "authorityEpoch"):
            try:
                uuid.UUID(str(parameters.get(field, "")))
            except ValueError as exc:
                raise OperationValidationError(f"{field} must be a UUID") from exc
        for field in ("sourceTrustDomain", "targetTrustDomain"):
            value = parameters.get(field)
            if not isinstance(value, str) or not DOMAIN_ID.fullmatch(value):
                raise OperationValidationError(
                    f"{field} must be a canonical trust-domain id"
                )
        if parameters["sourceTrustDomain"] == parameters["targetTrustDomain"]:
            raise OperationValidationError("migration source and target must differ")


class OperationLedger:
    def __init__(
        self,
        path: Path,
        *,
        recover_on_init: bool = False,
        require_existing: bool = False,
        migrate_schema: bool = True,
        read_only: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.clock = clock
        self.migrate_schema = migrate_schema
        self.read_only = read_only
        self.manage_permissions = not require_existing and not read_only
        if read_only and (not require_existing or migrate_schema):
            raise ValueError("read-only ledger requires an existing current schema")
        if require_existing and not self.path.is_file():
            raise RuntimeError("operation ledger must be initialized by the worker")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if recover_on_init:
            self.recover_running()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.path}?mode=ro" if self.read_only else self.path,
            timeout=5,
            uri=self.read_only,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        if not self.read_only:
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
                  'workload.restart', 'backup.create', 'access.apply',
                  'workload.deploy', 'workload.start', 'workload.stop',
                  'backup.restore', 'migration.cutover', 'migration.rollback',
                  'production.promote', 'production.rollback',
                  'migration.source-fence', 'migration.target-prepare',
                  'migration.target-start', 'migration.route-switch',
                  'migration.final-verify', 'migration.target-stop',
                  'migration.source-restore', 'migration.source-verify'
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
            CREATE TABLE migrations (
                migration_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                workload_id TEXT NOT NULL,
                source_trust_domain TEXT NOT NULL,
                target_trust_domain TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                originating_session_hash TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                preview_digest TEXT NOT NULL,
                expected_revision TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                observation_digest TEXT NOT NULL,
                authority_epoch TEXT NOT NULL,
                phase TEXT NOT NULL CHECK (
                    phase IN (
                        'planned', 'preflight', 'awaiting-approval',
                        'source-fencing', 'source-fenced', 'target-preparing',
                        'target-starting', 'target-verified', 'route-switching',
                        'authority-committed', 'canonical-committed', 'verifying',
                        'succeeded', 'failed', 'denied', 'expired', 'indeterminate',
                        'rollback-target-stopping', 'rollback-source-restoring',
                        'rollback-verifying', 'rolled-back'
                    )
                ),
                created_at TEXT NOT NULL,
                approved_at TEXT,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                error_class TEXT,
                redacted_summary TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE UNIQUE INDEX one_active_migration_per_workload
              ON migrations(workload_id)
              WHERE phase NOT IN (
                  'succeeded', 'failed', 'denied', 'expired',
                  'indeterminate', 'rolled-back'
              )
            """,
            """
            CREATE TABLE migration_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id TEXT NOT NULL REFERENCES migrations(migration_id),
                phase TEXT NOT NULL,
                created_at TEXT NOT NULL,
                redacted_detail TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE INDEX migration_events_migration
              ON migration_events(migration_id, sequence)
            """,
            """
            CREATE TABLE migration_children (
                migration_id TEXT NOT NULL REFERENCES migrations(migration_id),
                operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
                phase TEXT NOT NULL,
                authority_epoch TEXT NOT NULL,
                PRIMARY KEY (migration_id, phase)
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
            connection.execute("DROP INDEX IF EXISTS one_mutation_per_workload")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS one_mutation_per_workload
                  ON operations(workload_id)
                  WHERE operation_type IN (
                      'workload.restart', 'backup.create', 'access.apply',
                      'workload.deploy', 'workload.start', 'workload.stop',
                      'backup.restore', 'migration.cutover', 'migration.rollback',
                      'production.promote', 'production.rollback',
                      'migration.source-fence', 'migration.target-prepare',
                      'migration.target-start', 'migration.route-switch',
                      'migration.final-verify', 'migration.target-stop',
                      'migration.source-restore', 'migration.source-verify'
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

    @staticmethod
    def _migrate_v2(connection: sqlite3.Connection) -> None:
        """Add durable migration parents without changing historic operations."""
        required_operation_columns = {
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
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(operations)").fetchall()
        }
        missing = required_operation_columns - columns
        if missing:
            raise RuntimeError(
                "operation ledger schema 2 is missing operations columns: "
                f"{','.join(sorted(missing))}"
            )
        connection.execute("DROP INDEX IF EXISTS one_mutation_per_workload")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS one_mutation_per_workload
              ON operations(workload_id)
              WHERE operation_type IN (
                  'workload.restart', 'backup.create', 'access.apply',
                  'workload.deploy', 'workload.start', 'workload.stop',
                  'backup.restore', 'migration.cutover', 'migration.rollback',
                  'production.promote', 'production.rollback',
                  'migration.source-fence', 'migration.target-prepare',
                  'migration.target-start', 'migration.route-switch',
                  'migration.final-verify', 'migration.target-stop',
                  'migration.source-restore', 'migration.source-verify'
              )
                AND state IN (
                    'awaiting-approval', 'queued', 'running',
                    'rollback-running', 'indeterminate'
                )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS migrations (
                migration_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                workload_id TEXT NOT NULL,
                source_trust_domain TEXT NOT NULL,
                target_trust_domain TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                originating_session_hash TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                preview_digest TEXT NOT NULL,
                expected_revision TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                observation_digest TEXT NOT NULL,
                authority_epoch TEXT NOT NULL,
                phase TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                error_class TEXT,
                redacted_summary TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_migration_per_workload
              ON migrations(workload_id)
              WHERE phase NOT IN (
                  'succeeded', 'failed', 'denied', 'expired',
                  'indeterminate', 'rolled-back'
              )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id TEXT NOT NULL REFERENCES migrations(migration_id),
                phase TEXT NOT NULL,
                created_at TEXT NOT NULL,
                redacted_detail TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS migration_events_migration
              ON migration_events(migration_id, sequence)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_children (
                migration_id TEXT NOT NULL REFERENCES migrations(migration_id),
                operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
                phase TEXT NOT NULL,
                authority_epoch TEXT NOT NULL,
                PRIMARY KEY (migration_id, phase)
            )
            """
        )

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
            "migrations": {
                "migration_id",
                "idempotency_key",
                "workload_id",
                "source_trust_domain",
                "target_trust_domain",
                "requested_by",
                "originating_session_hash",
                "preview_json",
                "preview_digest",
                "expected_revision",
                "policy_version",
                "observation_digest",
                "authority_epoch",
                "phase",
                "created_at",
                "approved_at",
                "updated_at",
                "finished_at",
                "error_class",
                "redacted_summary",
            },
            "migration_events": {
                "sequence",
                "migration_id",
                "phase",
                "created_at",
                "redacted_detail",
            },
            "migration_children": {
                "migration_id",
                "operation_id",
                "phase",
                "authority_epoch",
            },
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
        for index in {
            "one_mutation_per_workload",
            "operation_events_operation",
            "one_active_migration_per_workload",
            "migration_events_migration",
        }:
            if index not in indexes:
                raise RuntimeError(
                    f"operation ledger schema {SCHEMA_VERSION} is missing index {index}"
                )

    def _initialize(self) -> None:
        with self._connect() as connection:
            if not self.read_only:
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
                    while version < SCHEMA_VERSION:
                        if version < 2:
                            self._migrate_v1(connection)
                            version = 2
                        elif version == 2:
                            self._migrate_v2(connection)
                            version = 3
                        connection.execute(f"PRAGMA user_version={version}")
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

    @staticmethod
    def _migration_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["preview"] = json.loads(result.pop("preview_json"))
        return result

    @staticmethod
    def _migration_event(
        connection: sqlite3.Connection,
        migration_id: str,
        phase: str,
        created_at: str,
        detail: str = "",
    ) -> None:
        connection.execute(
            """
            INSERT INTO migration_events (
                migration_id, phase, created_at, redacted_detail
            ) VALUES (?, ?, ?, ?)
            """,
            (migration_id, phase, created_at, detail[:1000]),
        )

    @staticmethod
    def _migration_idempotency_matches(
        migration: dict[str, Any],
        *,
        workload_id: str,
        source_trust_domain: str,
        target_trust_domain: str,
        requested_by: str,
        originating_session_hash: str,
        preview_digest: str,
        expected_revision: str,
        policy_version: str,
        observation_digest: str,
    ) -> bool:
        return (
            migration["workload_id"] == workload_id
            and migration["source_trust_domain"] == source_trust_domain
            and migration["target_trust_domain"] == target_trust_domain
            and migration["requested_by"] == requested_by
            and migration["originating_session_hash"] == originating_session_hash
            and migration["preview_digest"] == preview_digest
            and migration["expected_revision"] == expected_revision
            and migration["policy_version"] == policy_version
            and migration["observation_digest"] == observation_digest
        )

    @staticmethod
    def _validate_migration_identity(
        *,
        workload_id: str,
        source_trust_domain: str,
        target_trust_domain: str,
        requested_by: str,
        originating_session_hash: str,
        preview: dict[str, Any],
        preview_digest: str,
        expected_revision: str,
        policy_version: str,
        observation_digest: str,
        idempotency_key: str,
    ) -> None:
        if not DOMAIN_ID.fullmatch(source_trust_domain) or not DOMAIN_ID.fullmatch(
            target_trust_domain
        ):
            raise OperationValidationError("migration trust domain is invalid")
        if source_trust_domain == target_trust_domain:
            raise OperationValidationError("migration source and target must differ")
        if not DOMAIN_ID.fullmatch(workload_id):
            raise OperationValidationError("migration workload ID is invalid")
        if (
            not requested_by
            or len(requested_by) > 128
            or any(ord(character) < 32 for character in requested_by)
        ):
            raise OperationValidationError("migration requester is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", originating_session_hash):
            raise OperationValidationError("migration session binding is invalid")
        preview_binding = dict(preview) if isinstance(preview, dict) else None
        if preview_binding is not None:
            preview_binding.pop("previewDigest", None)
        if preview_binding is None or digest(preview_binding) != preview_digest:
            raise OperationValidationError("migration preview binding is invalid")
        if (
            preview.get("previewDigest") != preview_digest
            or preview.get("eligible") is not True
            or preview.get("workloadId") != workload_id
            or preview.get("sourceTrustDomain") != source_trust_domain
            or preview.get("targetTrustDomain") != target_trust_domain
            or preview.get("expectedRevision") != expected_revision
            or preview.get("policyVersion") != policy_version
            or preview.get("observationDigest") != observation_digest
        ):
            raise OperationValidationError("migration preview does not match its authority binding")
        targets = preview.get("eligibleTargets")
        if not isinstance(targets, list) or targets != [target_trust_domain]:
            raise OperationValidationError("migration target is not eligible in the reviewed preview")
        if not target_trust_domain.endswith("-managed"):
            raise OperationValidationError("migration target must be a managed trust domain")
        if not expected_revision or not policy_version:
            raise OperationValidationError("migration canonical binding is invalid")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", observation_digest):
            raise OperationValidationError("migration observation evidence is invalid")
        if not idempotency_key or len(idempotency_key) > 256:
            raise OperationValidationError("migration idempotency key is invalid")

    def _active_migration(
        self,
        connection: sqlite3.Connection,
        workload_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM migrations
            WHERE workload_id = ?
              AND phase NOT IN (
                  'succeeded', 'failed', 'denied', 'expired',
                  'indeterminate', 'rolled-back'
              )
            LIMIT 1
            """,
            (workload_id,),
        ).fetchone()

    def create_migration(
        self,
        *,
        workload_id: str,
        source_trust_domain: str,
        target_trust_domain: str,
        requested_by: str,
        originating_session_hash: str,
        preview: dict[str, Any],
        preview_digest: str,
        expected_revision: str,
        policy_version: str,
        observation_digest: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        """Persist a reviewed parent migration in an inert approval state."""
        self._validate_migration_identity(
            workload_id=workload_id,
            source_trust_domain=source_trust_domain,
            target_trust_domain=target_trust_domain,
            requested_by=requested_by,
            originating_session_hash=originating_session_hash,
            preview=preview,
            preview_digest=preview_digest,
            expected_revision=expected_revision,
            policy_version=policy_version,
            observation_digest=observation_digest,
            idempotency_key=idempotency_key,
        )
        migration_id = str(uuid.uuid4())
        authority_epoch = str(uuid.uuid4())
        created_at = format_timestamp(self._now())
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing_row = connection.execute(
                    "SELECT * FROM migrations WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    connection.rollback()
                    existing = self._migration_row(existing_row) or {}
                    if not self._migration_idempotency_matches(
                        existing,
                        workload_id=workload_id,
                        source_trust_domain=source_trust_domain,
                        target_trust_domain=target_trust_domain,
                        requested_by=requested_by,
                        originating_session_hash=originating_session_hash,
                        preview_digest=preview_digest,
                        expected_revision=expected_revision,
                        policy_version=policy_version,
                        observation_digest=observation_digest,
                    ):
                        raise OperationConflict(
                            "idempotency key is bound to a different migration intent"
                        )
                    return existing, False
                active_operation = connection.execute(
                    """
                    SELECT 1 FROM operations
                    WHERE workload_id = ?
                      AND state IN (
                          'awaiting-approval', 'queued', 'running',
                          'rollback-running', 'indeterminate'
                      )
                      AND operation_type IN (
                          'workload.restart', 'backup.create', 'access.apply',
                          'workload.deploy', 'workload.start', 'workload.stop',
                          'backup.restore', 'migration.cutover', 'migration.rollback',
                          'production.promote', 'production.rollback',
                          'migration.source-fence', 'migration.target-prepare',
                          'migration.target-start', 'migration.route-switch',
                          'migration.final-verify', 'migration.target-stop',
                          'migration.source-restore', 'migration.source-verify'
                      )
                    LIMIT 1
                    """,
                    (workload_id,),
                ).fetchone()
                if active_operation is not None:
                    connection.rollback()
                    raise OperationConflict("workload already has an active mutation")
                if self._active_migration(connection, workload_id) is not None:
                    connection.rollback()
                    raise OperationConflict("workload already has an active migration")
                connection.execute(
                    """
                    INSERT INTO migrations (
                        migration_id, idempotency_key, workload_id,
                        source_trust_domain, target_trust_domain, requested_by,
                        originating_session_hash, preview_json, preview_digest,
                        expected_revision, policy_version, observation_digest,
                        authority_epoch, phase, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        migration_id,
                        idempotency_key,
                        workload_id,
                        source_trust_domain,
                        target_trust_domain,
                        requested_by,
                        originating_session_hash,
                        canonical_json(preview),
                        preview_digest,
                        expected_revision,
                        policy_version,
                        observation_digest,
                        authority_epoch,
                        "awaiting-approval",
                        created_at,
                        created_at,
                    ),
                )
                self._migration_event(
                    connection,
                    migration_id,
                    "planned",
                    created_at,
                    "Migration intent persisted without mutation authority.",
                )
                self._migration_event(
                    connection,
                    migration_id,
                    "preflight",
                    created_at,
                    "Reviewed source, target, and observation evidence were bound.",
                )
                self._migration_event(
                    connection,
                    migration_id,
                    "awaiting-approval",
                    created_at,
                    "Awaiting dashboard step-up and exact confirmation.",
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            existing = self.migration_by_idempotency(idempotency_key)
            if existing is not None:
                if self._migration_idempotency_matches(
                    existing,
                    workload_id=workload_id,
                    source_trust_domain=source_trust_domain,
                    target_trust_domain=target_trust_domain,
                    requested_by=requested_by,
                    originating_session_hash=originating_session_hash,
                    preview_digest=preview_digest,
                    expected_revision=expected_revision,
                    policy_version=policy_version,
                    observation_digest=observation_digest,
                ):
                    return existing, False
                raise OperationConflict(
                    "idempotency key is bound to a different migration intent"
                ) from exc
            raise OperationConflict("workload already has an active migration") from exc
        return self.get_migration(migration_id) or {}, True

    def get_migration(self, migration_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM migrations WHERE migration_id = ?", (migration_id,)
            ).fetchone()
            migration = self._migration_row(row)
            if migration is None:
                return None
            children = connection.execute(
                """
                SELECT c.migration_id, c.operation_id, c.phase, c.authority_epoch,
                       o.operation_type, o.trust_domain, o.state, o.created_at,
                       o.started_at, o.finished_at, o.error_class,
                       o.redacted_summary
                FROM migration_children c JOIN operations o
                  ON o.operation_id = c.operation_id
                WHERE c.migration_id = ?
                ORDER BY c.rowid
                """,
                (migration_id,),
            ).fetchall()
        migration["children"] = [dict(child) for child in children]
        return migration

    def migration_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM migrations WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return self._migration_row(row)

    def list_active_migrations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM migrations
                WHERE phase NOT IN (
                    'succeeded', 'failed', 'denied', 'expired',
                    'indeterminate', 'rolled-back'
                )
                ORDER BY created_at, migration_id
                """
            ).fetchall()
        return [self._migration_row(row) or {} for row in rows]

    def list_migrations_for_workload(self, workload_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM migrations WHERE workload_id = ?
                ORDER BY created_at DESC, migration_id DESC
                """,
                (workload_id,),
            ).fetchall()
        return [self._migration_row(row) or {} for row in rows]

    def migration_events(self, migration_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, migration_id, phase, created_at, redacted_detail
                FROM migration_events WHERE migration_id = ? ORDER BY sequence
                """,
                (migration_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition_migration(
        self,
        migration_id: str,
        expected: set[str],
        phase: str,
        *,
        event_detail: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        if phase not in MIGRATION_PHASES:
            raise ValueError("invalid migration phase")
        if not expected:
            raise ValueError("expected migration phase required")
        invalid_sources = {
            source
            for source in expected
            if phase not in MIGRATION_TRANSITIONS.get(source, set())
        }
        if invalid_sources:
            raise ValueError(
                "invalid migration transition from "
                f"{','.join(sorted(invalid_sources))} to {phase}"
            )
        changed_at = format_timestamp(self._now())
        assignments = ["phase = ?", "updated_at = ?"]
        values: list[Any] = [phase, changed_at]
        for key in (
            "approved_at",
            "finished_at",
            "error_class",
            "redacted_summary",
        ):
            if key in fields:
                assignments.append(f"{key} = ?")
                value = fields[key]
                values.append(
                    format_timestamp(value)
                    if key in {"approved_at", "finished_at"} and value is not None
                    else value
                )
        if phase in MIGRATION_TERMINAL_PHASES and "finished_at" not in fields:
            assignments.append("finished_at = ?")
            values.append(changed_at)
        placeholders = ", ".join("?" for _ in expected)
        values.extend([migration_id, *sorted(expected)])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE migrations SET {', '.join(assignments)} "
                f"WHERE migration_id = ? AND phase IN ({placeholders})",
                values,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise OperationConflict("migration phase changed")
            self._migration_event(
                connection,
                migration_id,
                phase,
                changed_at,
                event_detail,
            )
            connection.commit()
        return self.get_migration(migration_id) or {}

    def approve_migration(
        self,
        migration_id: str,
        *,
        requested_by: str,
        originating_session_hash: str,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", originating_session_hash):
            raise OperationValidationError("migration session binding is invalid")
        approved_at = format_timestamp(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE migrations
                SET phase = 'source-fencing', approved_at = ?, updated_at = ?
                WHERE migration_id = ? AND phase = 'awaiting-approval'
                  AND requested_by = ? AND originating_session_hash = ?
                """,
                (
                    approved_at,
                    approved_at,
                    migration_id,
                    requested_by,
                    originating_session_hash,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise OperationConflict("migration approval binding or phase changed")
            self._migration_event(
                connection,
                migration_id,
                "source-fencing",
                approved_at,
                "Dashboard step-up and exact confirmation granted one authority epoch.",
            )
            connection.commit()
        return self.get_migration(migration_id) or {}

    def cancel_migration(
        self,
        migration_id: str,
        *,
        requested_by: str,
        originating_session_hash: str,
    ) -> dict[str, Any]:
        changed_at = format_timestamp(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE migrations
                SET phase = 'denied', updated_at = ?, finished_at = ?,
                    error_class = 'operator-cancelled',
                    redacted_summary = 'Cancelled by operator before approval.'
                WHERE migration_id = ? AND phase = 'awaiting-approval'
                  AND requested_by = ? AND originating_session_hash = ?
                """,
                (
                    changed_at,
                    changed_at,
                    migration_id,
                    requested_by,
                    originating_session_hash,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise OperationConflict("migration cancellation binding or phase changed")
            self._migration_event(
                connection,
                migration_id,
                "denied",
                changed_at,
                "Cancelled by the originating dashboard session before approval.",
            )
            connection.commit()
        return self.get_migration(migration_id) or {}

    def begin_migration_rollback(
        self,
        migration_id: str,
        *,
        requested_by: str,
        originating_session_hash: str,
    ) -> dict[str, Any]:
        """Fence the target before restoring a source after a reviewed rollback."""
        allowed = {
            "source-fenced",
            "target-preparing",
            "target-starting",
            "target-verified",
            "route-switching",
            "authority-committed",
            "canonical-committed",
            "verifying",
            "succeeded",
        }
        changed_at = format_timestamp(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT phase FROM migrations
                WHERE migration_id = ? AND requested_by = ?
                  AND originating_session_hash = ?
                """,
                (migration_id, requested_by, originating_session_hash),
            ).fetchone()
            if current is None or str(current["phase"]) not in allowed:
                connection.rollback()
                raise OperationConflict("migration rollback binding or phase changed")
            active_child = connection.execute(
                """
                SELECT 1 FROM migration_children c JOIN operations o
                  ON o.operation_id = c.operation_id
                WHERE c.migration_id = ? AND o.state IN ('queued', 'running')
                LIMIT 1
                """,
                (migration_id,),
            ).fetchone()
            if active_child is not None:
                connection.rollback()
                raise OperationConflict("migration child is still active")
            cursor = connection.execute(
                """
                UPDATE migrations
                SET phase = 'rollback-target-stopping', updated_at = ?,
                    finished_at = NULL, error_class = NULL, redacted_summary = ''
                WHERE migration_id = ? AND phase = ?
                """,
                (changed_at, migration_id, current["phase"]),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise OperationConflict("migration rollback phase changed")
            self._migration_event(
                connection,
                migration_id,
                "rollback-target-stopping",
                changed_at,
                "Dashboard approved a fenced rollback under the existing authority epoch.",
            )
            connection.commit()
        return self.get_migration(migration_id) or {}

    def ensure_migration_child(self, migration_id: str) -> tuple[dict[str, Any], bool]:
        """Idempotently queue the single child authorized for the parent phase."""
        created_at = format_timestamp(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM migrations WHERE migration_id = ?", (migration_id,)
            ).fetchone()
            migration = self._migration_row(row)
            if migration is None:
                connection.rollback()
                raise OperationValidationError("migration is unknown")
            phase = str(migration["phase"])
            plan = MIGRATION_OPERATION_PHASES.get(phase)
            if plan is None or not migration.get("approved_at"):
                connection.rollback()
                raise OperationValidationError("migration phase has no authorized child")
            existing = connection.execute(
                """
                SELECT o.* FROM migration_children c JOIN operations o
                  ON o.operation_id = c.operation_id
                WHERE c.migration_id = ? AND c.phase = ?
                """,
                (migration_id, phase),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return self._row(existing) or {}, False
            operation_type, domain_role = plan
            trust_domain = str(
                migration[
                    "source_trust_domain"
                    if domain_role == "source"
                    else "target_trust_domain"
                ]
            )
            parameters = {
                "migrationId": migration_id,
                "authorityEpoch": str(migration["authority_epoch"]),
                "sourceTrustDomain": str(migration["source_trust_domain"]),
                "targetTrustDomain": str(migration["target_trust_domain"]),
            }
            validate_typed_parameters(operation_type, parameters)
            operation_id = str(uuid.uuid4())
            preview = {
                "workloadId": migration["workload_id"],
                "trustDomain": trust_domain,
                "operationType": operation_type,
                "parameters": parameters,
                "expectedRevision": migration["expected_revision"],
                "policyVersion": migration["policy_version"],
            }
            try:
                connection.execute(
                    """
                    INSERT INTO operations (
                        operation_id, idempotency_key, workload_id, trust_domain,
                        operation_type, requested_by, parameters_json,
                        parameters_digest, preview_json, preview_digest,
                        expected_revision, policy_version, state, created_at,
                        approved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        operation_id,
                        f"migration:{migration_id}:{phase}:{migration['authority_epoch']}",
                        migration["workload_id"],
                        trust_domain,
                        operation_type,
                        migration["requested_by"],
                        canonical_json(parameters),
                        digest(parameters),
                        canonical_json(preview),
                        digest(preview),
                        migration["expected_revision"],
                        migration["policy_version"],
                        created_at,
                        migration["approved_at"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO migration_children (
                        migration_id, operation_id, phase, authority_epoch
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (migration_id, operation_id, phase, migration["authority_epoch"]),
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise OperationConflict("migration child authority changed") from exc
            self._event(
                connection,
                operation_id,
                "queued",
                created_at,
                "Parent migration authorized this one phase-specific child.",
            )
            connection.commit()
        return self.get(operation_id) or {}, True

    def migration_child_binding(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT m.*, c.operation_id AS child_operation_id,
                       c.phase AS child_phase,
                       c.authority_epoch AS child_authority_epoch
                FROM migration_children c JOIN migrations m
                  ON m.migration_id = c.migration_id
                WHERE c.operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        return self._migration_row(row)

    def migration_child_authorized(
        self,
        operation_id: str,
        *,
        workload_id: str,
        operation_type: str,
        trust_domain: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        migration = self.migration_child_binding(operation_id)
        if migration is None:
            return None
        plan = MIGRATION_OPERATION_PHASES.get(str(migration.get("child_phase", "")))
        if plan is None:
            return None
        expected_type, domain_role = plan
        expected_domain = migration[
            "source_trust_domain" if domain_role == "source" else "target_trust_domain"
        ]
        if (
            operation_type != expected_type
            or trust_domain != expected_domain
            or migration.get("phase") != migration.get("child_phase")
            or migration.get("workload_id") != workload_id
            or not migration.get("approved_at")
            or parameters.get("migrationId") != migration.get("migration_id")
            or parameters.get("authorityEpoch") != migration.get("authority_epoch")
            or parameters.get("authorityEpoch") != migration.get("child_authority_epoch")
            or parameters.get("sourceTrustDomain")
            != migration.get("source_trust_domain")
            or parameters.get("targetTrustDomain")
            != migration.get("target_trust_domain")
        ):
            return None
        return migration

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

    def _validate_dependency(
        self,
        workload_id: str,
        trust_domain: str,
        operation_type: str,
        expected_revision: str,
        parameters: dict[str, Any],
    ) -> None:
        reference_fields = {
            "migration.cutover": ("preflightOperationId", "migration.preflight"),
            "migration.rollback": ("cutoverOperationId", "migration.cutover"),
            "production.rollback": ("promotionOperationId", "production.promote"),
        }
        if operation_type in reference_fields:
            field, required_type = reference_fields[operation_type]
            try:
                source = self.get(str(parameters[field]))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise OperationValidationError("referenced lifecycle evidence is malformed") from exc
            if (
                source is None
                or source["state"] != "succeeded"
                or source["operation_type"] != required_type
                or source["workload_id"] != workload_id
                or source["expected_revision"] != expected_revision
            ):
                raise OperationValidationError("referenced lifecycle evidence is not eligible")
            linked = source.get("rollback_operation_id")
            if linked:
                replacement = self.get(str(linked))
                if replacement is None or replacement["state"] not in {"failed", "denied", "expired"}:
                    raise OperationValidationError("referenced operation already has a rollback")
            if operation_type == "migration.cutover":
                result = source.get("redactedResult")
                if not isinstance(result, dict) or result.get("readyForCutover") is not True:
                    raise OperationValidationError("migration preflight did not prove cutover readiness")
                if source["parameters"].get("targetTrustDomain") != trust_domain:
                    raise OperationValidationError("migration preflight target does not match")
            return
        if operation_type != "production.promote":
            return
        try:
            source = self.get(str(parameters["sourceOperationId"]))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise OperationValidationError("promotion source evidence is malformed") from exc
        target = str(parameters["targetTrustDomain"])
        if (
            source is None
            or source["state"] != "succeeded"
            or source["workload_id"] != workload_id
            or source["expected_revision"] != expected_revision
            or source["trust_domain"] == target
        ):
            raise OperationValidationError("promotion source evidence is not eligible")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT redacted_result_json, finished_at FROM operations
                WHERE workload_id = ? AND trust_domain = ?
                  AND operation_type = 'health.refresh' AND state = 'succeeded'
                ORDER BY finished_at DESC LIMIT 1
                """,
                (workload_id, source["trust_domain"]),
            ).fetchone()
        if row is None or self._now() - parse_timestamp(str(row["finished_at"])) > 300:
            raise OperationValidationError("promotion requires fresh source health evidence")
        try:
            health = json.loads(str(row["redacted_result_json"])).get("health", {})
        except (json.JSONDecodeError, AttributeError):
            health = {}
        if health.get("ok") is not True:
            raise OperationValidationError("promotion source health evidence is unhealthy")

    def runtime_domain(self, workload_id: str, fallback: str) -> str:
        """Return the latest proven runtime placement for one workload.

        Desired classification and effective placement intentionally diverge
        during a reviewed migration.  Placement changes are derived only from
        successful fenced lifecycle results; callers cannot supply an
        arbitrary execution domain.
        """
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", fallback):
            raise OperationValidationError("fallback runtime domain is invalid")
        with self._connect() as connection:
            migration_rows = connection.execute(
                """
                SELECT source_trust_domain, target_trust_domain, phase
                FROM migrations
                WHERE workload_id = ?
                  AND phase IN (
                      'authority-committed', 'canonical-committed',
                      'verifying', 'succeeded', 'rollback-target-stopping',
                      'rollback-source-restoring', 'rollback-verifying',
                      'rolled-back'
                  )
                ORDER BY updated_at DESC, migration_id DESC
                """,
                (workload_id,),
            ).fetchall()
            rows = connection.execute(
                """
                SELECT operation_type, redacted_result_json
                FROM operations
                WHERE workload_id = ?
                  AND operation_type IN (
                    'migration.cutover', 'migration.rollback',
                    'production.promote', 'production.rollback'
                  )
                  AND state = 'succeeded'
                ORDER BY finished_at DESC, rowid DESC
                """,
                (workload_id,),
            ).fetchall()
        for row in migration_rows:
            field = (
                "source_trust_domain"
                if str(row["phase"]) == "rolled-back"
                else "target_trust_domain"
            )
            domain = row[field]
            if isinstance(domain, str) and DOMAIN_ID.fullmatch(domain):
                return domain
        for row in rows:
            try:
                result = json.loads(str(row["redacted_result_json"]))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            field = (
                "sourceTrustDomain"
                if str(row["operation_type"]).endswith("rollback")
                else "targetTrustDomain"
            )
            domain = result.get(field) if isinstance(result, dict) else None
            if isinstance(domain, str) and re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,62}", domain
            ):
                return domain
        return fallback

    def create(
        self, *, workload_id: str, trust_domain: str, operation_type: str,
        requested_by: str, parameters: dict[str, Any], preview_digest: str,
        expected_revision: str, policy_version: str, idempotency_key: str,
        preview: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        validate_typed_parameters(operation_type, parameters)
        if operation_type in MIGRATION_CHILD_OPERATIONS:
            raise OperationValidationError(
                "migration phase children may only be created by the migration coordinator"
            )
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
        self._validate_dependency(
            workload_id, trust_domain, operation_type, expected_revision, parameters
        )
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
                if operation_type in MUTATIONS and self._active_migration(
                    connection, workload_id
                ) is not None:
                    connection.rollback()
                    raise OperationConflict("workload already has an active migration")
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
                rollback_reference = {
                    "migration.rollback": "cutoverOperationId",
                    "production.rollback": "promotionOperationId",
                }.get(operation_type)
                if rollback_reference:
                    updated = connection.execute(
                        """
                        UPDATE operations SET rollback_operation_id = ?
                        WHERE operation_id = ?
                          AND (
                            rollback_operation_id IS NULL OR rollback_operation_id IN (
                              SELECT operation_id FROM operations
                              WHERE state IN ('failed', 'denied', 'expired')
                            )
                          )
                        """,
                        (operation_id, str(parameters[rollback_reference])),
                    )
                    if updated.rowcount != 1:
                        raise OperationConflict("referenced operation already has a rollback")
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
                              'workload.restart', 'backup.create', 'access.apply',
                              'workload.deploy', 'workload.start', 'workload.stop',
                              'backup.restore', 'migration.cutover', 'migration.rollback',
                              'production.promote', 'production.rollback'
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
