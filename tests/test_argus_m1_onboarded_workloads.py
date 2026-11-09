import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m1_onboarded_workloads import OnboardedReconcileError, reconcile_onboarded_workloads
from argus_m1_retired_workloads import RetirementReconcileError, reconcile_retired_workloads
from argus_m1_verify import verify_m1_state
from argus_sqlite import ClosingConnection
from argus_state import AuditLedger, legacy_workload_snapshot


CLASSIFICATION = {"realm": "unclassified", "zone": "legacy", "stage": "none", "trustDomain": "legacy-rootful"}
ACCESS = {"desired": "none", "effective": "none", "lastError": "", "lastAppliedAt": ""}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class OnboardedM1WorkloadRegistrationTests(unittest.TestCase):
    """Config: project-a (in M1, revision 7) and new-b (onboarded, absent). M1 also holds retired-a."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.runtime = self.root / "runtime" / "argus"
        config = self.root / "config"
        (config / "argus").mkdir(parents=True)
        (self.runtime / "m1").mkdir(parents=True)
        active = {"project-a": CLASSIFICATION, "new-b": CLASSIFICATION}
        files = {
            "workloads.json": {"workloads": [{"id": "project-a"}, {"id": "new-b"}]},
            "privacy.json": {"workloads": {key: {"privacy": "internal", "reason": key} for key in active}},
            "access.json": {"workloads": {key: ACCESS for key in active}},
            "argus/legacy-classification.json": {"workloads": active},
            "argus/workload-classification.json": {"workloads": active},
            "argus/retired-workloads.json": {"schemaVersion": 1, "workloads": ["retired-a"]},
        }
        for name, value in files.items():
            (config / name).write_text(json.dumps(value), encoding="utf-8")
        present = ("project-a", "retired-a")
        states = {
            str(entry["id"]): entry["state"]
            for entry in legacy_workload_snapshot([{"id": key} for key in present], {key: CLASSIFICATION for key in present})
        }
        with sqlite3.connect(self.runtime / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            connection.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY, entity_kind TEXT NOT NULL, revision INTEGER NOT NULL, state_json TEXT NOT NULL)")
            connection.executemany(
                "INSERT INTO entities VALUES (?, 'project', ?, ?)",
                [("project-a", 7, canonical(states["project-a"])), ("retired-a", 1, canonical(states["retired-a"]))],
            )
        with sqlite3.connect(self.runtime / "m1" / "state.sqlite3", factory=ClosingConnection) as connection:
            for table, entries in (
                ("privacy_projection", {key: {"privacy": "internal", "reason": key} for key in present}),
                ("access_projection", {key: ACCESS for key in present}),
            ):
                connection.execute(f"CREATE TABLE {table} (workload_id TEXT PRIMARY KEY, entry_json TEXT NOT NULL)")
                connection.executemany(f"INSERT INTO {table} VALUES (?, ?)", [(key, canonical(value)) for key, value in entries.items()])
        self.ledger = AuditLedger(self.runtime / "audit.sqlite3")
        self.ledger.append({"actor": "test", "operation": "seed", "outcome": "accepted", "target": "fixture", "trustDomain": "management"})

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def rows(self, database: str, sql: str) -> list[tuple]:
        with sqlite3.connect(self.runtime / database, factory=ClosingConnection) as connection:
            return connection.execute(sql).fetchall()

    def test_preview_counts_then_apply_inserts_only_missing_rows_with_audit_and_checkpoint(self) -> None:
        preview = reconcile_onboarded_workloads(self.root, apply=False)
        self.assertEqual(
            {"schemaVersion": 1, "ready": True, "entityInsertions": 1, "privacyProjectionInsertions": 1,
             "accessProjectionInsertions": 1, "registered": False, "alreadyApplied": False},
            preview,
        )
        self.assertFalse((self.runtime / "m1" / "onboarding-backups").exists())

        result = reconcile_onboarded_workloads(self.root, apply=True)
        self.assertTrue(result["registered"])
        self.assertFalse(result["alreadyApplied"])
        self.assertEqual(
            [("new-b", 1), ("project-a", 7), ("retired-a", 1)],
            self.rows("entity-store.sqlite3", "SELECT entity_id, revision FROM entities ORDER BY entity_id"),
        )
        for table in ("privacy_projection", "access_projection"):
            self.assertEqual(
                ["new-b", "project-a", "retired-a"],
                [row[0] for row in self.rows("m1/state.sqlite3", f"SELECT workload_id FROM {table} ORDER BY workload_id")],
            )
        backups = sorted(path.name.split("-")[0] for path in (self.runtime / "m1" / "onboarding-backups").iterdir())
        self.assertEqual(["entities", "projections"], backups)
        self.assertFalse((self.runtime / "m1" / "onboarded-workload-register.json").exists())
        self.assertTrue(self.ledger.verify())
        events = [event for event in self.ledger._events() if event["operation"] == "inventory.register"]
        self.assertEqual(["intent", "accepted"], [event["outcome"] for event in events])
        self.assertEqual(1, len({event["correlationId"] for event in events}))
        self.assertEqual(1, events[1]["entityInsertions"])

        sequence = self.ledger.checkpoint()["sequence"]
        again = reconcile_onboarded_workloads(self.root, apply=True)
        self.assertTrue(again["alreadyApplied"])
        self.assertEqual(0, again["entityInsertions"])
        self.assertEqual(sequence, self.ledger.checkpoint()["sequence"])

        reconcile_retired_workloads(self.root, apply=True)
        self.assertTrue(verify_m1_state(self.root)["verified"])

    def test_retired_reconcile_refuses_until_onboarded_workloads_are_registered(self) -> None:
        with self.assertRaisesRegex(RetirementReconcileError, "argus-m1-reconcile-onboarded-workloads"):
            reconcile_retired_workloads(self.root, apply=False)

    def test_drifted_existing_row_is_refused_without_mutation(self) -> None:
        with sqlite3.connect(self.runtime / "m1" / "state.sqlite3", factory=ClosingConnection) as connection:
            connection.execute("UPDATE access_projection SET entry_json = ? WHERE workload_id = 'project-a'", (canonical({**ACCESS, "lastError": "drift"}),))
        with self.assertRaisesRegex(OnboardedReconcileError, "differs from the reviewed configuration"):
            reconcile_onboarded_workloads(self.root, apply=True)
        self.assertEqual([], self.rows("entity-store.sqlite3", "SELECT 1 FROM entities WHERE entity_id = 'new-b'"))
        self.assertFalse((self.runtime / "m1" / "onboarding-backups").exists())

    def test_unapproved_stale_row_is_refused_and_nothing_is_deleted(self) -> None:
        with sqlite3.connect(self.runtime / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            connection.execute("INSERT INTO entities VALUES ('unknown', 'project', 3, '{}')")
        with self.assertRaisesRegex(OnboardedReconcileError, "unapproved stale workload"):
            reconcile_onboarded_workloads(self.root, apply=True)
        self.assertEqual(
            ["project-a", "retired-a", "unknown"],
            [row[0] for row in self.rows("entity-store.sqlite3", "SELECT entity_id FROM entities ORDER BY entity_id")],
        )

    def test_nothing_missing_is_a_no_op_without_audit_or_checkpoint(self) -> None:
        reconcile_onboarded_workloads(self.root, apply=True)
        for path in (self.runtime / "m1" / "onboarding-backups").iterdir():
            path.unlink()
        sequence = self.ledger.checkpoint()["sequence"]
        result = reconcile_onboarded_workloads(self.root, apply=True)
        self.assertEqual((True, True), (result["registered"], result["alreadyApplied"]))
        self.assertEqual([], list((self.runtime / "m1" / "onboarding-backups").iterdir()))
        self.assertEqual(sequence, self.ledger.checkpoint()["sequence"])

    def test_cli_refuses_apply_without_acknowledgement(self) -> None:
        command = [sys.executable, str(ROOT / "scripts" / "argus-m1-reconcile-onboarded-workloads"), "--root", str(self.root)]
        refused = subprocess.run([*command, "--apply"], text=True, capture_output=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("--acknowledge-onboarded-workload-registration", refused.stderr)
        self.assertEqual([], self.rows("entity-store.sqlite3", "SELECT 1 FROM entities WHERE entity_id = 'new-b'"))
        preview = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertEqual(1, json.loads(preview.stdout)["entityInsertions"])
        self.assertNotIn("new-b", preview.stdout)


if __name__ == "__main__":
    unittest.main()
