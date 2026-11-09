import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m1_retired_workloads import RetirementReconcileError, reconcile_retired_workloads
from argus_m1_verify import verify_m1_state
from argus_sqlite import ClosingConnection
from argus_state import AuditLedger, legacy_workload_snapshot


class RetiredM1WorkloadReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def fixture(self) -> Path:
        root = Path(self.tempdir.name)
        config = root / "config"
        (config / "argus").mkdir(parents=True)
        runtime = root / "runtime" / "argus" / "m1"
        runtime.mkdir(parents=True)
        active = {
            "project-a": {
                "realm": "unclassified",
                "zone": "legacy",
                "stage": "none",
                "trustDomain": "legacy-rootful",
            }
        }
        retired = {
            "retired-a": {
                "realm": "unclassified",
                "zone": "legacy",
                "stage": "none",
                "trustDomain": "legacy-rootful",
            }
        }
        workloads = {"workloads": [{"id": "project-a"}]}
        legacy = {"workloads": active}
        classified = {"workloads": active}
        privacy = {"workloads": {"project-a": {"privacy": "internal", "reason": "active"}}}
        access = {"workloads": {"project-a": {"desired": "none", "effective": "none", "lastError": "", "lastAppliedAt": ""}}}
        for name, value in (
            ("workloads.json", workloads),
            ("privacy.json", privacy),
            ("access.json", access),
        ):
            (config / name).write_text(json.dumps(value), encoding="utf-8")
        (config / "argus" / "legacy-classification.json").write_text(json.dumps(legacy), encoding="utf-8")
        (config / "argus" / "workload-classification.json").write_text(json.dumps(classified), encoding="utf-8")
        (config / "argus" / "retired-workloads.json").write_text(json.dumps({"schemaVersion": 1, "workloads": ["retired-a"]}), encoding="utf-8")
        entity_path = root / "runtime" / "argus" / "entity-store.sqlite3"
        snapshots = {
            str(entry["id"]): entry["state"]
            for entry in legacy_workload_snapshot(
                [{"id": "project-a"}, {"id": "retired-a"}],
                {**active, **retired},
            )
        }
        with sqlite3.connect(entity_path, factory=ClosingConnection) as connection:
            connection.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY, entity_kind TEXT NOT NULL, revision INTEGER NOT NULL, state_json TEXT NOT NULL)")
            for workload_id in {**active, **retired}:
                connection.execute(
                    "INSERT INTO entities VALUES (?, ?, ?, ?)",
                    (workload_id, "project", 7 if workload_id == "project-a" else 1, json.dumps(snapshots[workload_id], sort_keys=True, separators=(",", ":"))),
                )
        projection_path = root / "runtime" / "argus" / "m1" / "state.sqlite3"
        with sqlite3.connect(projection_path, factory=ClosingConnection) as connection:
            for table, entries in (
                ("privacy_projection", {**privacy["workloads"], "retired-a": {"privacy": "internal", "reason": "retired"}}),
                ("access_projection", {**access["workloads"], "retired-a": {"desired": "none", "effective": "none", "lastError": "", "lastAppliedAt": ""}}),
            ):
                connection.execute(f"CREATE TABLE {table} (workload_id TEXT PRIMARY KEY, entry_json TEXT NOT NULL)")
                connection.executemany(
                    f"INSERT INTO {table} VALUES (?, ?)",
                    [(key, json.dumps(value, sort_keys=True, separators=(",", ":"))) for key, value in entries.items()],
                )
        ledger = AuditLedger(root / "runtime" / "argus" / "audit.sqlite3")
        ledger.append({"actor": "test", "operation": "seed", "outcome": "accepted", "target": "fixture", "trustDomain": "management"})
        return root

    def test_declared_retirements_are_pruned_without_rewriting_active_state(self) -> None:
        root = self.fixture()
        preview = reconcile_retired_workloads(root, apply=False)
        self.assertTrue(preview["ready"])
        self.assertEqual(1, preview["entityRemovals"])
        self.assertFalse(preview["alreadyApplied"])
        result = reconcile_retired_workloads(root, apply=True)
        self.assertTrue(result["reconciled"])
        self.assertTrue(verify_m1_state(root)["verified"])
        with sqlite3.connect(root / "runtime" / "argus" / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            revision = connection.execute("SELECT revision FROM entities WHERE entity_id = 'project-a'").fetchone()[0]
            retired = connection.execute("SELECT COUNT(*) FROM entities WHERE entity_id = 'retired-a'").fetchone()[0]
        self.assertEqual(7, revision)
        self.assertEqual(0, retired)
        self.assertTrue(AuditLedger(root / "runtime" / "argus" / "audit.sqlite3").verify())
        self.assertTrue(reconcile_retired_workloads(root, apply=True)["alreadyApplied"])

    def test_unapproved_stale_state_is_rejected_without_mutation(self) -> None:
        root = self.fixture()
        with sqlite3.connect(root / "runtime" / "argus" / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            connection.execute(
                "INSERT INTO entities VALUES (?, ?, ?, ?)",
                ("unknown", "project", 1, json.dumps({"declared": {}, "observed": {}, "effective": {}})),
            )
        with self.assertRaisesRegex(RetirementReconcileError, "unapproved stale workload"):
            reconcile_retired_workloads(root, apply=True)
        with sqlite3.connect(root / "runtime" / "argus" / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM entities WHERE entity_id = 'retired-a'").fetchone()[0])

    def test_present_active_projection_drift_is_reprojected_to_reviewed_config(self) -> None:
        root = self.fixture()
        with sqlite3.connect(root / "runtime" / "argus" / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            connection.execute(
                "UPDATE entities SET state_json = ? WHERE entity_id = 'project-a'",
                (json.dumps({"invalid": True}),),
            )
        with sqlite3.connect(root / "runtime" / "argus" / "m1" / "state.sqlite3", factory=ClosingConnection) as connection:
            connection.execute(
                "UPDATE privacy_projection SET entry_json = ? WHERE workload_id = 'project-a'",
                (json.dumps({"privacy": "internal", "reason": "stale"}),),
            )
            connection.execute(
                "UPDATE access_projection SET entry_json = ? WHERE workload_id = 'project-a'",
                (json.dumps({"desired": "none", "effective": "none", "lastError": "stale", "lastAppliedAt": ""}),),
            )
        preview = reconcile_retired_workloads(root, apply=False)
        self.assertEqual(1, preview["entityUpdates"])
        self.assertEqual(1, preview["privacyProjectionUpdates"])
        self.assertEqual(1, preview["accessProjectionUpdates"])
        result = reconcile_retired_workloads(root, apply=True)
        self.assertTrue(result["reconciled"])
        self.assertTrue(verify_m1_state(root)["verified"])
        with sqlite3.connect(root / "runtime" / "argus" / "entity-store.sqlite3", factory=ClosingConnection) as connection:
            self.assertEqual(8, connection.execute("SELECT revision FROM entities WHERE entity_id = 'project-a'").fetchone()[0])

    def test_active_registry_overlap_with_retired_registry_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "config" / "argus" / "retired-workloads.json"
        path.write_text(json.dumps({"schemaVersion": 1, "workloads": ["project-a"]}), encoding="utf-8")
        with self.assertRaisesRegex(RetirementReconcileError, "overlaps"):
            reconcile_retired_workloads(root, apply=False)


if __name__ == "__main__":
    unittest.main()
