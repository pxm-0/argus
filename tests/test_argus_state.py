from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_state import AtomicJsonStore, AuditLedger, Classification, EntityState, SQLiteRepository, StateError, StoreCutover, authorize_mutation, authorize_relationship, legacy_workload_snapshot  # noqa: E402


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

    def test_cross_domain_resources_require_authenticated_gateway(self) -> None:
        authorize_relationship("personal-prod", "personal-prod", "volume")
        authorize_relationship("personal-prod", "work-prod", "service-gateway", authenticated_gateway=True)
        with self.assertRaises(StateError):
            authorize_relationship("personal-prod", "work-prod", "volume")
        with self.assertRaises(StateError):
            authorize_relationship("personal-prod", "work-prod", "service-gateway")

    def test_mutation_gate_fails_closed_for_any_missing_dependency(self) -> None:
        dependencies = {"policy": True, "store": True, "authorization": True, "freshness": True, "observation": True, "reconciliation": True, "audit": True}
        authorize_mutation(**dependencies)
        dependencies["audit"] = False
        with self.assertRaises(StateError):
            authorize_mutation(**dependencies)

    def test_legacy_snapshot_preserves_quarantine(self) -> None:
        snapshot = legacy_workload_snapshot([{"id": "legacy-a"}], {"legacy-a": {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful"}})
        self.assertEqual("legacy-a", snapshot[0]["id"])
        self.assertEqual("legacy", snapshot[0]["state"]["effective"]["domainKind"])

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

    def test_cutover_requires_parity_and_retains_a_safe_rollback_checkpoint(self) -> None:
        state = EntityState(legacy(), legacy(), legacy()).as_dict()
        snapshot = [{"id": "project-a", "kind": "project", "state": state}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = SQLiteRepository(root / "argus.sqlite3")
            cutover = StoreCutover(repository, root / "cutover.json")
            with self.assertRaises(StateError):
                cutover.prepare(snapshot, journal_digest="sha256:journal")
            repository.import_snapshot(snapshot)
            prepared = cutover.prepare(snapshot, journal_digest="sha256:journal")
            self.assertEqual("PREPARED", prepared["phase"])
            with self.assertRaises(StateError):
                cutover.activate(snapshot, journal_digest="sha256:changed")
            active = cutover.activate(snapshot, journal_digest="sha256:journal")
            self.assertEqual("SQLITE_ACTIVE", active["phase"])
            self.assertEqual(snapshot, cutover.rollback())

    def test_cutover_refuses_rollback_after_sqlite_diverges(self) -> None:
        state = EntityState(legacy(), legacy(), legacy())
        snapshot = [{"id": "project-a", "kind": "project", "state": state.as_dict()}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = SQLiteRepository(root / "argus.sqlite3")
            repository.import_snapshot(snapshot)
            cutover = StoreCutover(repository, root / "cutover.json")
            cutover.prepare(snapshot, journal_digest="sha256:journal")
            cutover.activate(snapshot, journal_digest="sha256:journal")
            repository.put_entity("project-a", "service", state, expected_revision=1)
            with self.assertRaises(StateError):
                cutover.rollback()

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

    def test_json_store_crash_injection_recovers_every_durable_boundary(self) -> None:
        for boundary, expected in {
            "after-prepared": 0,
            "after-json-fsync": 0,
            "after-replace": 1,
            "after-committed": 1,
        }.items():
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)

                def crash(point: str) -> None:
                    if point == boundary:
                        raise RuntimeError(f"injected crash: {point}")

                store = AtomicJsonStore(root / "legacy.json", root / "journal.jsonl", fault_hook=crash)
                with self.assertRaisesRegex(RuntimeError, "injected crash"):
                    store.replace({"value": "one"}, expected_revision=0, operation="replace-legacy")
                outcomes = store.recover()
                self.assertEqual(expected, store.read()["revision"])
                self.assertTrue(outcomes or boundary == "after-committed")

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

    def test_audit_checkpoint_is_transport_neutral_and_bound_to_latest_event(self) -> None:
        payload = {"actor": "operator-1", "operation": "approve", "outcome": "accepted", "target": "project-a", "trustDomain": "legacy-rootful"}
        with tempfile.TemporaryDirectory() as directory:
            ledger = AuditLedger(Path(directory) / "audit.sqlite3")
            self.assertEqual(0, ledger.checkpoint()["sequence"])
            event_hash = ledger.append(payload)
            checkpoint = ledger.checkpoint()
            self.assertEqual(1, checkpoint["sequence"])
            self.assertEqual(event_hash, checkpoint["eventHash"])
            self.assertTrue(checkpoint["checkpointHash"].startswith("sha256:"))

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
