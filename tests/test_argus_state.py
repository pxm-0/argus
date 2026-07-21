from __future__ import annotations

import tempfile
import unittest
import sqlite3
import json
import os
import subprocess
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_state import AccessMutationWriter, AtomicJsonStore, AuditLedger, Classification, EntityState, PrivacyMutationWriter, SQLiteRepository, StateError, StoreCutover, authorize_mutation, authorize_relationship, legacy_workload_snapshot, verify_audit_checkpoint  # noqa: E402
from argus_m1_verify import VerificationError, verify_m1_state  # noqa: E402
from argus_m1_reconcile import ReconcileError, reconcile  # noqa: E402


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
            self.assertTrue(verify_audit_checkpoint(checkpoint))
            self.assertFalse(verify_audit_checkpoint({**checkpoint, "sequence": 2}))

    def test_audit_checkpoint_cli_exports_only_a_nonempty_verified_ledger(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            ledger_path = root / "audit.sqlite3"
            output = root / "checkpoint.json"
            ledger = AuditLedger(ledger_path)
            failed = subprocess.run([sys.executable, str(ROOT / "scripts" / "argus-m1-audit-checkpoint"), "--ledger", str(ledger_path), "--output", str(output)], text=True, capture_output=True)
            self.assertNotEqual(0, failed.returncode)
            ledger.append({"actor": "operator", "operation": "approve", "outcome": "accepted", "target": "project-a", "trustDomain": "legacy-rootful"})
            exported = subprocess.run([sys.executable, str(ROOT / "scripts" / "argus-m1-audit-checkpoint"), "--ledger", str(ledger_path), "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(0, exported.returncode, exported.stderr)
            self.assertEqual(0o600, os.stat(output).st_mode & 0o777)
            verified = subprocess.run([sys.executable, str(ROOT / "scripts" / "argus-m1-audit-checkpoint"), "--verify", str(output)], text=True, capture_output=True)
            self.assertEqual(0, verified.returncode, verified.stderr)
            self.assertTrue(verify_audit_checkpoint(json.loads(output.read_text())))

    def test_audit_ledger_rejects_unattributed_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StateError):
                AuditLedger(Path(directory) / "audit.sqlite3").append({"operation": "approve"})

    def test_privacy_writer_keeps_json_and_sqlite_in_parity_with_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            privacy_path = root / "privacy.json"
            privacy_path.write_text(json.dumps({"defaultPrivacy": "unclassified", "states": ["unclassified", "internal"], "workloads": {"project-a": {"privacy": "unclassified", "reason": "initial"}}}))
            writer = PrivacyMutationWriter(privacy_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
            self.assertEqual(("unclassified", "internal"), writer.set_privacy(workload_id="project-a", privacy_value="internal", reason="reviewed", actor="operator", timestamp="2026-07-18T00:00:00Z"))
            self.assertEqual("internal", json.loads(privacy_path.read_text())["workloads"]["project-a"]["privacy"])
            self.assertTrue(writer._parity(writer._read_privacy()))
            self.assertTrue(writer.ledger.verify())

    def test_privacy_writer_recovers_prepared_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            privacy_path = root / "privacy.json"
            replacement = {"defaultPrivacy": "unclassified", "states": ["unclassified", "internal"], "workloads": {"project-a": {"privacy": "internal", "reason": "reviewed"}}}
            privacy_path.write_text(json.dumps(replacement))
            writer = PrivacyMutationWriter(privacy_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
            outcome = {"actor": "operator", "operation": "privacy.set", "outcome": "accepted", "target": "project-a", "trustDomain": "legacy-rootful", "correlationId": "test"}
            writer._append({"phase": "PREPARED", "transactionId": "test", "privacyChecksum": "sha256:" + __import__("hashlib").sha256(json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "outcome": outcome})
            writer.recover()
            self.assertTrue(writer._parity(replacement))
            self.assertTrue(writer.ledger.verify())

    def test_access_writer_reconciles_only_exact_reviewed_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "access.json"
            before = {"desired": "cloudflare-protected", "effective": "local"}
            after = {"desired": "cloudflare-protected", "effective": "none"}
            deployed = {"states": ["none", "local", "cloudflare-protected"], "workloads": {"project-a": after}}
            path.write_text(json.dumps(deployed))
            writer = AccessMutationWriter(path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
            writer._project({"states": deployed["states"], "workloads": {"project-a": before}})
            result = writer.reconcile_deployed(workload_id="project-a", expected_before=before, expected_after=after, actor="operator", trust_domain="personal-sandbox")
            self.assertEqual({"reconciled": True, "alreadyApplied": False}, result)
            self.assertTrue(writer._parity(deployed))
            self.assertEqual({"reconciled": True, "alreadyApplied": True}, writer.reconcile_deployed(workload_id="project-a", expected_before=before, expected_after=after, actor="operator", trust_domain="personal-sandbox"))

    def test_access_writer_rejects_unreviewed_deployment_or_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "access.json"
            before = {"desired": "local", "effective": "local"}
            after = {"desired": "none", "effective": "none"}
            path.write_text(json.dumps({"states": ["none", "local"], "workloads": {"project-a": after}}))
            writer = AccessMutationWriter(path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
            writer._project({"states": ["none", "local"], "workloads": {"project-a": {"desired": "local", "effective": "none"}}})
            with self.assertRaisesRegex(StateError, "pre-deployment"):
                writer.reconcile_deployed(workload_id="project-a", expected_before=before, expected_after=after, actor="operator", trust_domain="personal-sandbox")

    def test_access_deployment_reconciliation_recovers_after_prepared_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "access.json"
            before = {"desired": "local", "effective": "local"}
            after = {"desired": "none", "effective": "none"}
            deployed = {"states": ["none", "local"], "workloads": {"project-a": after}}
            path.write_text(json.dumps(deployed))

            def crash(boundary: str) -> None:
                if boundary == "access-reconcile-after-prepared":
                    raise RuntimeError("injected crash")

            writer = AccessMutationWriter(path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl", fault_hook=crash)
            writer._project({"states": deployed["states"], "workloads": {"project-a": before}})
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                writer.reconcile_deployed(workload_id="project-a", expected_before=before, expected_after=after, actor="operator", trust_domain="personal-sandbox")
            recovered = AccessMutationWriter(path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
            recovered.recover()
            self.assertTrue(recovered._parity(deployed))
            self.assertTrue(recovered.ledger.verify())

    def test_privacy_writer_recovers_each_durable_boundary_without_duplicate_outcome(self) -> None:
        for boundary, expected in {
            "privacy-after-prepared": "unclassified",
            "privacy-after-json": "internal",
            "privacy-after-projection": "internal",
            "privacy-after-outcome": "internal",
            "privacy-after-committed": "internal",
        }.items():
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                privacy_path = root / "privacy.json"
                privacy_path.write_text(json.dumps({"defaultPrivacy": "unclassified", "states": ["unclassified", "internal"], "workloads": {"project-a": {"privacy": "unclassified", "reason": "initial"}}}))

                def crash(point: str) -> None:
                    if point == boundary:
                        raise RuntimeError(point)

                writer = PrivacyMutationWriter(privacy_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl", fault_hook=crash)
                with self.assertRaisesRegex(RuntimeError, boundary):
                    writer.set_privacy(workload_id="project-a", privacy_value="internal", reason="reviewed", actor="operator", timestamp="2026-07-19T00:00:00Z")
                recovered = PrivacyMutationWriter(privacy_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
                recovered.recover()
                self.assertEqual(expected, recovered._read_privacy()["workloads"]["project-a"]["privacy"])
                self.assertTrue(recovered.ledger.verify())
                events = recovered.ledger._events()
                self.assertLessEqual(sum(event.get("outcome") == "accepted" for event in events), 1)

    def test_access_writer_recovers_prepared_or_applied_write(self) -> None:
        for boundary, expected in {"access-after-prepared": "local", "access-after-json": "cloudflare-protected", "access-after-outcome": "cloudflare-protected"}.items():
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                access_path = root / "access.json"
                access_path.write_text(json.dumps({"states": ["local", "cloudflare-protected"], "workloads": {"project-a": {"desired": "local", "effective": "local", "lastError": "", "lastAppliedAt": ""}}}))

                def crash(point: str) -> None:
                    if point == boundary:
                        raise RuntimeError(point)

                writer = AccessMutationWriter(access_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl", fault_hook=crash)
                with self.assertRaisesRegex(RuntimeError, boundary):
                    writer.apply(workload_id="project-a", desired="cloudflare-protected", decision={"allowed": True, "plannedOnly": True, "reason": "planned", "effective": "local"}, actor="operator", timestamp="2026-07-19T00:00:00Z")
                recovered = AccessMutationWriter(access_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
                recovered.recover()
                self.assertEqual(expected, recovered._read_access()["workloads"]["project-a"]["desired"])
                self.assertTrue(recovered.ledger.verify())

    def test_access_writer_requires_policy_and_preserves_planned_only_effective_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access_path = root / "access.json"
            access_path.write_text(json.dumps({"states": ["local", "cloudflare-protected"], "workloads": {"project-a": {"desired": "local", "effective": "local", "lastError": "", "lastAppliedAt": ""}}}))
            writer = AccessMutationWriter(access_path, root / "state.sqlite3", root / "audit.sqlite3", root / "journal.jsonl")
            denied = {"allowed": False}
            with self.assertRaises(StateError):
                writer.apply(workload_id="project-a", desired="local", decision=denied, actor="operator", timestamp="2026-07-18T00:00:00Z")
            result = writer.apply(workload_id="project-a", desired="cloudflare-protected", decision={"allowed": True, "plannedOnly": True, "reason": "planned only", "effective": "local"}, actor="operator", timestamp="2026-07-18T00:00:00Z")
            stored = json.loads(access_path.read_text())["workloads"]["project-a"]
            self.assertTrue(result["plannedOnly"])
            self.assertEqual("cloudflare-protected", stored["desired"])
            self.assertEqual("local", stored["effective"])
            self.assertTrue(writer._parity(writer._read_access()))
            self.assertTrue(writer.ledger.verify())

    def test_m1_verifier_requires_parity_and_returns_only_safe_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            (config / "argus").mkdir(parents=True)
            workloads = {"workloads": [{"id": "project-a"}]}
            classification = {"workloads": {"project-a": {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful"}}}
            privacy = {"states": ["unclassified", "internal"], "workloads": {"project-a": {"privacy": "unclassified", "reason": "initial"}}}
            access = {"states": ["none", "local"], "workloads": {"project-a": {"desired": "none", "effective": "local", "lastError": "", "lastAppliedAt": ""}}}
            for name, value in (("workloads.json", workloads), ("privacy.json", privacy), ("access.json", access)):
                (config / name).write_text(json.dumps(value))
            (config / "argus" / "legacy-classification.json").write_text(json.dumps(classification))
            runtime = root / "runtime" / "argus"
            snapshot = legacy_workload_snapshot(workloads["workloads"], classification["workloads"])
            repository = SQLiteRepository(runtime / "entity-store.sqlite3")
            repository.import_snapshot(snapshot)
            privacy_writer = PrivacyMutationWriter(config / "privacy.json", runtime / "m1" / "state.sqlite3", runtime / "audit.sqlite3", runtime / "m1" / "privacy.jsonl")
            privacy_writer.set_privacy(workload_id="project-a", privacy_value="internal", reason="verified", actor="operator", timestamp="2026-07-19T00:00:00Z")
            access_writer = AccessMutationWriter(config / "access.json", runtime / "m1" / "state.sqlite3", runtime / "audit.sqlite3", runtime / "m1" / "access.jsonl")
            access_writer.apply(workload_id="project-a", desired="local", decision={"allowed": True, "plannedOnly": False, "reason": "safe", "effective": "local"}, actor="operator", timestamp="2026-07-19T00:00:00Z")
            summary = verify_m1_state(root)
            self.assertTrue(summary["verified"])
            self.assertEqual(1, summary["entityCount"])
            self.assertGreaterEqual(summary["auditSequence"], 4)
            self.assertNotIn("project-a", json.dumps(summary))
            (config / "privacy.json").write_text(json.dumps(privacy))
            with self.assertRaises(VerificationError):
                verify_m1_state(root)

    def test_m1_reconciliation_adds_only_missing_fail_closed_records_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config" / "argus").mkdir(parents=True)
            (root / "config" / "workloads.json").write_text(json.dumps({"workloads": [{"id": "one"}, {"id": "two"}]}))
            baseline = {"default": {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful", "status": "legacy-unclassified", "admission": "denied"}, "workloads": {"one": {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful", "status": "legacy-unclassified", "admission": "denied"}}}
            path = root / "config" / "argus" / "legacy-classification.json"
            path.write_text(json.dumps(baseline))
            self.assertEqual(1, reconcile(root, apply=False)["missingCount"])
            result = reconcile(root, apply=True)
            self.assertTrue(result["applied"])
            self.assertTrue(result["backupDigest"].startswith("sha256:"))
            repaired = json.loads(path.read_text())
            self.assertEqual({"one", "two"}, set(repaired["workloads"]))
            self.assertEqual(baseline["default"], repaired["workloads"]["two"])
            self.assertEqual(0, reconcile(root, apply=False)["missingCount"])
            repaired["workloads"]["one"]["admission"] = "allowed"
            path.write_text(json.dumps(repaired))
            with self.assertRaises(ReconcileError):
                reconcile(root, apply=True)

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
