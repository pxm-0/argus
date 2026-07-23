from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


MUTATIONS = {"workload.restart", "backup.create", "access.apply"}
TYPED_OPERATIONS = {"health.refresh", "logs.preview", *MUTATIONS}
TERMINAL_STATES = {"succeeded", "failed", "rolled-back", "denied", "expired", "indeterminate"}
ALLOWED_STATES = {
    "planned", "awaiting-approval", "queued", "running", "succeeded", "failed",
    "rollback-running", "rolled-back", "denied", "expired", "indeterminate",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class OperationConflict(Exception):
    pass


class OperationLedger:
    def __init__(self, path: Path, *, recover_on_init: bool = True) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if recover_on_init:
            self.recover_running()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    workload_id TEXT NOT NULL,
                    trust_domain TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    preview_digest TEXT NOT NULL,
                    expected_revision TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    approved_at INTEGER,
                    started_at INTEGER,
                    finished_at INTEGER,
                    error_class TEXT,
                    redacted_summary TEXT NOT NULL DEFAULT '',
                    redacted_result_json TEXT NOT NULL DEFAULT '{}',
                    rollback_operation_id TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_mutation_per_workload
                ON operations(workload_id)
                WHERE operation_type IN ('workload.restart', 'backup.create', 'access.apply')
                  AND state IN ('awaiting-approval', 'queued', 'running', 'rollback-running');
                CREATE TABLE IF NOT EXISTS used_nonces (
                    nonce TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                );
                """
            )
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(operations)")}
            if "redacted_result_json" not in columns:
                connection.execute(
                    "ALTER TABLE operations ADD COLUMN redacted_result_json TEXT NOT NULL DEFAULT '{}'"
                )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["parameters"] = json.loads(result.pop("parameters_json"))
        result["redactedResult"] = json.loads(result.pop("redacted_result_json"))
        return result

    def recover_running(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operations
                SET state = 'indeterminate', finished_at = ?, error_class = 'process-restarted',
                    redacted_summary = 'Outcome unknown after control-plane restart; no automatic retry.'
                WHERE state IN ('running', 'rollback-running')
                """,
                (int(time.time()),),
            )
        return int(cursor.rowcount)

    def create(
        self, *, workload_id: str, trust_domain: str, operation_type: str,
        requested_by: str, parameters: dict[str, Any], preview_digest: str,
        expected_revision: str, policy_version: str, idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        if operation_type not in TYPED_OPERATIONS:
            raise ValueError("unsupported operation type")
        if not idempotency_key:
            raise ValueError("idempotency key required")
        existing = self.by_idempotency(idempotency_key)
        if existing:
            return existing, False
        operation_id = str(uuid.uuid4())
        state = "awaiting-approval" if operation_type in MUTATIONS else "queued"
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO operations (
                        operation_id, idempotency_key, workload_id, trust_domain, operation_type,
                        requested_by, parameters_json, preview_digest, expected_revision,
                        policy_version, state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id, idempotency_key, workload_id, trust_domain, operation_type,
                        requested_by, canonical_json(parameters), preview_digest, expected_revision,
                        policy_version, state, int(time.time()),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.by_idempotency(idempotency_key)
            if existing:
                return existing, False
            raise OperationConflict("workload already has an active mutation") from exc
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
                "SELECT * FROM operations WHERE workload_id = ? ORDER BY created_at DESC",
                (workload_id,),
            ).fetchall()
        return [self._row(row) or {} for row in rows]

    def transition(self, operation_id: str, expected: set[str], state: str, **fields: Any) -> dict[str, Any]:
        if state not in ALLOWED_STATES:
            raise ValueError("invalid operation state")
        assignments = ["state = ?"]
        values: list[Any] = [state]
        for key in ("approved_at", "started_at", "finished_at", "error_class", "redacted_summary", "redacted_result_json", "rollback_operation_id"):
            if key in fields:
                assignments.append(f"{key} = ?")
                values.append(fields[key])
        placeholders = ", ".join("?" for _ in expected)
        values.extend([operation_id, *sorted(expected)])
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE operations SET {', '.join(assignments)} WHERE operation_id = ? AND state IN ({placeholders})",
                values,
            )
        if cursor.rowcount != 1:
            raise OperationConflict("operation state changed")
        return self.get(operation_id) or {}

    def consume_nonce(self, nonce: str, expires_at: int) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM used_nonces WHERE expires_at <= ?", (int(time.time()),))
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


class OperationRunner:
    def __init__(self, ledger: OperationLedger, agent_for: Callable[[str], DomainAgent]) -> None:
        self.ledger = ledger
        self.agent_for = agent_for

    def dispatch(self, operation_id: str, capability: str) -> None:
        thread = threading.Thread(target=self._run, args=(operation_id, capability), daemon=True)
        thread.start()

    def _run(self, operation_id: str, capability: str) -> None:
        operation = self.ledger.get(operation_id)
        if not operation:
            return
        current = int(time.time())
        try:
            self.ledger.transition(operation_id, {"queued"}, "running", started_at=current)
            request = {
                key: operation[key]
                for key in ("workload_id", "trust_domain", "operation_type", "parameters", "expected_revision", "preview_digest", "policy_version", "idempotency_key")
            }
            request["capability"] = capability
            result = self.agent_for(str(operation["trust_domain"])).execute(request)
            self.ledger.transition(
                operation_id, {"running"}, "succeeded", finished_at=int(time.time()),
                redacted_summary=str(result.get("summary", "Operation succeeded."))[:1000],
                redacted_result_json=canonical_json(result),
            )
        except PermissionError as exc:
            self.ledger.transition(
                operation_id, {"running"}, "denied", finished_at=int(time.time()),
                error_class="policy-denied", redacted_summary=str(exc)[:1000],
            )
        except Exception as exc:  # noqa: BLE001 - durable terminal state is required.
            self.ledger.transition(
                operation_id, {"running"}, "failed", finished_at=int(time.time()),
                error_class=exc.__class__.__name__, redacted_summary="Domain agent rejected or failed the operation.",
            )


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
