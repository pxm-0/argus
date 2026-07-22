import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m1_identity_reconcile import IdentityReconcileError, reconcile_identity
from argus_state import AuditLedger


class ArgusM1IdentityReconcileTests(unittest.TestCase):
    def fixture(self) -> Path:
        root = Path(self.tempdir.name)
        (root / "config").mkdir()
        (root / "runtime" / "argus" / "m1").mkdir(parents=True)
        privacy_old = {"demo": {"privacy": "internal", "updatedBy": "oreo-cloud-discovery"}}
        privacy_new = {"demo": {"privacy": "internal", "updatedBy": "argus-discovery"}}
        access_old = {"demo": {"desired": "none", "urls": {"cloudflare": "https://demo.oreo-cloud.invalid"}}}
        access_new = {"demo": {"desired": "none", "urls": {"cloudflare": "https://demo.argus.invalid"}}}
        (root / "config" / "privacy.json").write_text(json.dumps({"workloads": privacy_new}))
        (root / "config" / "access.json").write_text(json.dumps({"workloads": access_new}))
        with sqlite3.connect(root / "runtime" / "argus" / "m1" / "state.sqlite3") as connection:
            for table, entries in (("privacy_projection", privacy_old), ("access_projection", access_old)):
                connection.execute(f"CREATE TABLE {table} (workload_id TEXT PRIMARY KEY, entry_json TEXT NOT NULL)")
                connection.executemany(f"INSERT INTO {table} VALUES (?, ?)", [(key, json.dumps(value, sort_keys=True, separators=(",", ":"))) for key, value in entries.items()])
        ledger = AuditLedger(root / "runtime" / "argus" / "audit.sqlite3")
        ledger.append({"actor": "test", "operation": "seed", "outcome": "accepted", "target": "fixture", "trustDomain": "management"})
        return root

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_identity_change_is_audited_and_reconciled(self) -> None:
        root = self.fixture()
        self.assertTrue(reconcile_identity(root, apply=False)["ready"])
        result = reconcile_identity(root, apply=True)
        self.assertTrue(result["reconciled"])
        self.assertFalse(result["alreadyApplied"])
        self.assertTrue(AuditLedger(root / "runtime" / "argus" / "audit.sqlite3").verify())
        self.assertTrue(reconcile_identity(root, apply=True)["alreadyApplied"])

    def test_unreviewed_difference_is_rejected(self) -> None:
        root = self.fixture()
        privacy = json.loads((root / "config" / "privacy.json").read_text())
        privacy["workloads"]["demo"]["privacy"] = "public"
        (root / "config" / "privacy.json").write_text(json.dumps(privacy))
        with self.assertRaises(IdentityReconcileError):
            reconcile_identity(root, apply=True)


if __name__ == "__main__":
    unittest.main()
