from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_state import AtomicJsonStore, AuditLedger, Classification, EntityState, SQLiteRepository, StateError  # noqa: E402


def legacy() -> Classification:
    return Classification("unclassified", "legacy", "none", "legacy-rootful", "legacy")


class ArgusStateTest(unittest.TestCase):
    def test_domain_constraints_fail_closed(self) -> None:
        legacy().validate()
        with self.assertRaises(StateError):
            Classification("personal", "legacy", "none", "legacy-rootful", "legacy").validate()
        with self.assertRaises(StateError):
            Classification(None, None, "none", "argus-management", "management").validate()
        with self.assertRaises(StateError):
            Classification("unclassified", "sandbox", "dev", "workload-a", "workload").validate()

    def test_effective_state_cannot_claim_more_than_observed(self) -> None:
        observed = legacy()
        effective = Classification("personal", "managed", "production", "personal-prod", "workload")
        with self.assertRaises(StateError):
            EntityState(observed, observed, effective).validate()

    def test_repository_requires_matching_revision_and_persists_atomically(self) -> None:
        state = EntityState(legacy(), legacy(), legacy())
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteRepository(Path(directory) / "argus.sqlite3")
            self.assertEqual(1, repository.put_entity("project-a", "project", state, expected_revision=None))
            self.assertEqual(2, repository.put_entity("project-a", "project", state, expected_revision=1))
            with self.assertRaises(StateError):
                repository.put_entity("project-a", "project", state, expected_revision=1)
            self.assertEqual(2, repository.get_entity("project-a")["revision"])

    def test_snapshot_import_requires_semantic_parity(self) -> None:
        state = EntityState(legacy(), legacy(), legacy()).as_dict()
        snapshot = [{"id": "project-a", "kind": "project", "state": state}]
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteRepository(Path(directory) / "argus.sqlite3")
            repository.import_snapshot(snapshot)
            self.assertTrue(repository.semantic_parity(snapshot))
            self.assertFalse(repository.semantic_parity([{**snapshot[0], "kind": "service"}]))

    def test_json_store_journals_and_recovers_applied_write_without_commit_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AtomicJsonStore(root / "legacy.json", root / "journal.jsonl")
            self.assertEqual(1, store.replace({"value": "one"}, expected_revision=0, operation="replace-legacy"))
            record = store.read()
            lines = (root / "journal.jsonl").read_text().splitlines()
            (root / "journal.jsonl").write_text("\n".join(lines[:-1]) + "\n")
            outcomes = store.recover()
            self.assertEqual("committed", outcomes[record["transactionId"]])
            self.assertEqual(1, store.read()["revision"])

    def test_json_store_recovery_aborts_prepared_write_not_reflected_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AtomicJsonStore(root / "legacy.json", root / "journal.jsonl")
            store._append({"phase": "PREPARED", "transactionId": "lost", "expectedRevision": 0, "operation": "replace", "payloadChecksum": "sha256:test"})
            self.assertEqual({"lost": "aborted"}, store.recover())

    def test_audit_ledger_is_hash_chained_and_detects_tampering(self) -> None:
        payload = {"actor": "operator-1", "operation": "approve", "outcome": "accepted", "target": "project-a", "trustDomain": "legacy-rootful"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite3"
            ledger = AuditLedger(path)
            ledger.append(payload)
            ledger.append({**payload, "operation": "reconcile"})
            self.assertTrue(ledger.verify())
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE audit_events SET payload_json = ? WHERE sequence = 1", ('{}',))
            self.assertFalse(ledger.verify())

    def test_audit_ledger_rejects_unattributed_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StateError):
                AuditLedger(Path(directory) / "audit.sqlite3").append({"operation": "approve"})

    def test_break_glass_requires_durable_intent_and_reconciles_abandonment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = AuditLedger(Path(directory) / "audit.sqlite3")
            with self.assertRaises(StateError):
                ledger.begin_break_glass(actor="operator", target="project-a", trust_domain="legacy-rootful", operation="recover", correlation_id="x", bypass_non_waivable=True)
            ledger.begin_break_glass(actor="operator", target="project-a", trust_domain="legacy-rootful", operation="recover", correlation_id="x")
            self.assertEqual(["x"], ledger.reconcile_abandoned_break_glass(actor="reconciler"))
            with self.assertRaises(StateError):
                ledger.complete_break_glass(actor="operator", target="project-a", trust_domain="legacy-rootful", operation="recover", correlation_id="missing", outcome="accepted")
            self.assertTrue(ledger.verify())
