from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_operations import (  # noqa: E402
    CapabilityCodec,
    DomainAgent,
    OperationConflict,
    OperationLedger,
    capability_claims,
    digest,
)
from argus_sessions import SessionStore  # noqa: E402


class SessionStoreTests(unittest.TestCase):
    def test_session_requires_matching_identity_and_csrf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            session = store.create("operator@example.com")
            self.assertIsNotNone(store.get(session.session_id, "operator@example.com"))
            self.assertIsNone(store.get(session.session_id, "attacker@example.com"))
            self.assertTrue(store.csrf_valid(session.session_id, session.csrf_token))
            self.assertFalse(store.csrf_valid(session.session_id, "wrong"))
            rotated = store.rotate_csrf(session.session_id)
            self.assertTrue(store.csrf_valid(session.session_id, rotated))
            self.assertFalse(store.csrf_valid(session.session_id, session.csrf_token))
            self.assertTrue(session.step_up_valid)

    def test_expiry_logout_and_identity_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3", ttl_seconds=-1)
            expired = store.create("operator@example.com")
            self.assertIsNone(store.get(expired.session_id, expired.identity))
            active_store = SessionStore(Path(directory) / "active.sqlite3")
            first = active_store.create("operator@example.com")
            second = active_store.create("operator@example.com")
            active_store.revoke(first.session_id)
            self.assertIsNone(active_store.get(first.session_id, first.identity))
            self.assertEqual(active_store.revoke_identity(second.identity), 1)
            self.assertIsNone(active_store.get(second.session_id, second.identity))


class OperationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "operations.sqlite3"
        self.ledger = OperationLedger(self.path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create(self, **overrides: object) -> tuple[dict[str, object], bool]:
        values: dict[str, object] = {
            "workload_id": "demo",
            "trust_domain": "personal-sandbox",
            "operation_type": "workload.restart",
            "requested_by": "operator@example.com",
            "parameters": {},
            "preview_digest": "preview",
            "expected_revision": "revision",
            "policy_version": "1",
            "idempotency_key": "idem-1",
        }
        values.update(overrides)
        return self.ledger.create(**values)  # type: ignore[arg-type]

    def test_idempotency_and_single_mutation_lock(self) -> None:
        first, created = self.create()
        repeated, repeated_created = self.create()
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(first["operation_id"], repeated["operation_id"])
        with self.assertRaises(OperationConflict):
            self.create(operation_type="backup.create", idempotency_key="idem-2")
        with self.assertRaisesRegex(OperationConflict, "different operation intent"):
            self.create(
                workload_id="other",
                operation_type="workload.restart",
                idempotency_key="idem-1",
            )

    def test_terminal_operation_releases_lock(self) -> None:
        operation, _ = self.create()
        self.ledger.transition(
            str(operation["operation_id"]), {"awaiting-approval"}, "denied",
            finished_at=int(time.time()), redacted_summary="cancelled",
        )
        second, created = self.create(operation_type="backup.create", idempotency_key="idem-2")
        self.assertTrue(created)
        self.assertEqual(second["state"], "awaiting-approval")

    def test_restart_marks_unknown_running_outcome_indeterminate(self) -> None:
        current = [1_000_000]
        ledger = OperationLedger(self.path, clock=lambda: current[0])
        operation, _ = ledger.create(
            workload_id="demo",
            trust_domain="personal-sandbox",
            operation_type="health.refresh",
            requested_by="operator@example.com",
            parameters={},
            preview_digest="preview",
            expected_revision="revision",
            policy_version="1",
            idempotency_key="stale-running",
        )
        claimed = ledger.claim(str(operation["operation_id"]))
        self.assertEqual("running", claimed["state"])
        current[0] += 29
        self.assertEqual(0, ledger.recover_running())
        self.assertEqual("running", ledger.get(str(operation["operation_id"]))["state"])
        current[0] += 2
        self.assertEqual(1, ledger.recover_running())
        recovered = ledger.get(str(operation["operation_id"]))
        self.assertEqual(recovered["state"], "indeterminate")
        self.assertEqual(recovered["error_class"], "worker-recovery-timeout")
        self.assertEqual(
            ["queued", "running", "indeterminate"],
            [event["state"] for event in ledger.events(str(operation["operation_id"]))],
        )

    def test_required_schema_digests_events_and_pragmas(self) -> None:
        operation, _ = self.create()
        self.assertEqual(64, len(str(operation["parameters_digest"])))
        self.assertEqual({}, operation["parameters"])
        self.assertEqual("demo", operation["preview"]["workloadId"])
        self.assertTrue(str(operation["created_at"]).endswith("Z"))
        self.assertEqual(
            ["awaiting-approval"],
            [event["state"] for event in self.ledger.events(str(operation["operation_id"]))],
        )
        with self.ledger._connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(operations)")
            }
            self.assertTrue(
                {
                    "parameters_digest",
                    "preview_json",
                    "heartbeat_at",
                    "rollback_operation_id",
                }.issubset(columns)
            )
            self.assertEqual("wal", connection.execute("PRAGMA journal_mode").fetchone()[0])
            self.assertEqual(2, connection.execute("PRAGMA synchronous").fetchone()[0])
            self.assertEqual(1, connection.execute("PRAGMA foreign_keys").fetchone()[0])
            self.assertEqual(1, connection.execute("PRAGMA user_version").fetchone()[0])

    def test_state_change_and_event_are_one_transaction(self) -> None:
        operation, _ = self.create()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_queued_event
                BEFORE INSERT ON operation_events
                WHEN NEW.state = 'queued'
                BEGIN
                  SELECT RAISE(ABORT, 'event rejected');
                END
                """
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "event rejected"):
            self.ledger.transition(
                str(operation["operation_id"]),
                {"awaiting-approval"},
                "queued",
                approved_at=int(time.time()),
            )
        self.assertEqual(
            "awaiting-approval",
            self.ledger.get(str(operation["operation_id"]))["state"],
        )

    def test_concurrent_idempotency_returns_one_operation(self) -> None:
        barrier = threading.Barrier(6)
        results: list[tuple[str, bool]] = []
        failures: list[Exception] = []

        def create() -> None:
            try:
                barrier.wait()
                operation, created = self.create()
                results.append((str(operation["operation_id"]), created))
            except Exception as exc:  # noqa: BLE001
                failures.append(exc)

        threads = [threading.Thread(target=create) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], failures)
        self.assertEqual(1, len({operation_id for operation_id, _ in results}))
        self.assertEqual(1, sum(1 for _, created in results if created))

    def test_legacy_schema_is_backed_up_and_migrated(self) -> None:
        legacy_path = Path(self.directory.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE operations (
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
                )
                """
            )
            connection.execute(
                """
                INSERT INTO operations VALUES (
                    'op', 'idem', 'demo', 'personal-sandbox',
                    'health.refresh', 'operator@example.com', '{}', 'preview',
                    'revision', '1', 'queued', 1000, NULL, NULL, NULL, NULL,
                    '', '{}', NULL
                )
                """
            )
        migrated = OperationLedger(legacy_path)
        self.assertTrue(
            legacy_path.with_name("legacy.sqlite3.pre-v1.bak").is_file()
        )
        operation = migrated.get("op")
        self.assertEqual("queued", operation["state"])
        self.assertEqual({}, operation["parameters"])
        self.assertEqual(["queued"], [event["state"] for event in migrated.events("op")])

    def test_declared_current_schema_must_be_structurally_complete(self) -> None:
        incomplete_path = Path(self.directory.name) / "incomplete.sqlite3"
        with sqlite3.connect(incomplete_path) as connection:
            connection.execute(
                "CREATE TABLE operations (operation_id TEXT PRIMARY KEY)"
            )
            connection.execute("PRAGMA user_version=1")
        with self.assertRaisesRegex(
            RuntimeError,
            "missing operations columns",
        ):
            OperationLedger(incomplete_path)

    def test_non_owner_clients_validate_without_changing_ledger_mode(self) -> None:
        with patch("argus_operations.os.chmod") as chmod:
            client = OperationLedger(
                self.path,
                require_existing=True,
                migrate_schema=False,
            )
        chmod.assert_not_called()
        self.assertIsNotNone(client)

    def test_recovery_preserves_queued_terminal_and_indeterminate_states(self) -> None:
        queued, _ = self.create(
            operation_type="health.refresh",
            idempotency_key="queued",
        )
        succeeded, _ = self.create(
            workload_id="succeeded",
            operation_type="health.refresh",
            idempotency_key="succeeded",
        )
        self.ledger.claim(str(succeeded["operation_id"]))
        self.ledger.transition(
            str(succeeded["operation_id"]),
            {"running"},
            "succeeded",
            finished_at=int(time.time()),
        )
        unknown, _ = self.create(
            workload_id="unknown",
            operation_type="health.refresh",
            idempotency_key="unknown",
        )
        self.ledger.claim(str(unknown["operation_id"]))
        self.ledger.mark_dispatch_indeterminate(str(unknown["operation_id"]))

        self.assertEqual(0, self.ledger.recover_running(stale_after_seconds=0))
        self.assertEqual("queued", self.ledger.get(str(queued["operation_id"]))["state"])
        self.assertEqual(
            "succeeded",
            self.ledger.get(str(succeeded["operation_id"]))["state"],
        )
        self.assertEqual(
            "indeterminate",
            self.ledger.get(str(unknown["operation_id"]))["state"],
        )


class DomainCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = OperationLedger(Path(self.directory.name) / "operations.sqlite3")
        self.codec = CapabilityCodec(b"x" * 32)
        self.executed: list[tuple[str, str, dict[str, object]]] = []
        preview = {
            "workloadId": "demo",
            "trustDomain": "personal-sandbox",
            "operationType": "workload.restart",
            "parameters": {},
            "expectedRevision": "revision",
            "policyVersion": "1",
        }
        self.operation, _ = self.ledger.create(
            workload_id="demo",
            trust_domain="personal-sandbox",
            operation_type="workload.restart",
            requested_by="operator@example.com",
            parameters={},
            preview_digest=digest(preview),
            expected_revision="revision",
            policy_version="1",
            idempotency_key="idem",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def agent(self, domain: str = "personal-sandbox") -> DomainAgent:
        def execute(operation_type: str, workload_id: str, parameters: dict[str, object]) -> dict[str, object]:
            self.executed.append((operation_type, workload_id, parameters))
            return {"summary": "ok"}

        return DomainAgent(
            domain, self.ledger, self.codec, execute,
            lambda _workload, _operation, _parameters: (True, ""),
            lambda _workload: "revision",
        )

    def request(self, **claim_overrides: object) -> dict[str, object]:
        claims = capability_claims(self.operation)
        claims.update(claim_overrides)
        request = {
            key: self.operation[key]
            for key in ("workload_id", "trust_domain", "operation_type", "parameters", "expected_revision", "preview_digest", "policy_version", "idempotency_key")
        }
        request["capability"] = self.codec.issue(claims)
        return request

    def test_valid_capability_executes_once(self) -> None:
        request = self.request()
        self.agent().execute(request)
        self.assertEqual(len(self.executed), 1)
        with self.assertRaisesRegex(ValueError, "replayed"):
            self.agent().execute(request)

    def test_wrong_domain_expired_stale_and_mismatch_fail_closed(self) -> None:
        cases = [
            ({"trust_domain": "other"}, "wrong capability domain"),
            ({"expires_at": int(time.time()) - 1}, "expired"),
            ({"expected_revision": "old"}, "mismatch"),
            ({"parameters": {"unexpected": True}}, "mismatch"),
        ]
        for index, (overrides, message) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaisesRegex(ValueError, message):
                    self.agent().execute(self.request(nonce=f"nonce-{index}", **overrides))
        self.assertEqual(self.executed, [])

    def test_agent_domain_and_policy_are_independently_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "wrong capability domain"):
            self.agent("other").execute(self.request())
        denying = DomainAgent(
            "personal-sandbox", self.ledger, self.codec, lambda *_args: {},
            lambda *_args: (False, "blocked by exact policy"), lambda _workload: "revision",
        )
        with self.assertRaisesRegex(PermissionError, "blocked by exact policy"):
            denying.execute(self.request(nonce="policy-nonce"))


if __name__ == "__main__":
    unittest.main()
