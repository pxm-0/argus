from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path


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
        operation, _ = self.create(operation_type="health.refresh")
        self.ledger.transition(str(operation["operation_id"]), {"queued"}, "running", started_at=int(time.time()))
        recovered = OperationLedger(self.path).get(str(operation["operation_id"]))
        self.assertEqual(recovered["state"], "indeterminate")
        self.assertEqual(recovered["error_class"], "process-restarted")


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
