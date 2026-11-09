from __future__ import annotations

import gc
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_operations import OperationLedger  # noqa: E402
from argus_sqlite import ClosingConnection  # noqa: E402


class ClosingConnectionTests(unittest.TestCase):
    def test_context_manager_commits_and_closes_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            connection = sqlite3.connect(database, factory=ClosingConnection)
            with connection as managed:
                managed.execute("CREATE TABLE entries (value TEXT)")
                managed.execute("INSERT INTO entries(value) VALUES ('saved')")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            with sqlite3.connect(database, factory=ClosingConnection) as check:
                self.assertEqual("saved", check.execute("SELECT value FROM entries").fetchone()[0])

    def test_context_manager_rolls_back_and_closes_after_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            with sqlite3.connect(database, factory=ClosingConnection) as setup:
                setup.execute("CREATE TABLE entries (value TEXT)")
            connection = sqlite3.connect(database, factory=ClosingConnection)
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with connection as managed:
                    managed.execute("INSERT INTO entries(value) VALUES ('lost')")
                    raise RuntimeError("boom")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            with sqlite3.connect(database, factory=ClosingConnection) as check:
                self.assertIsNone(check.execute("SELECT value FROM entries").fetchone())

    @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "Linux descriptor inventory required")
    def test_operation_ledger_polling_does_not_accumulate_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = OperationLedger(Path(directory) / "operations.sqlite3")
            operation, _ = ledger.create(
                workload_id="demo",
                trust_domain="personal-sandbox",
                operation_type="health.refresh",
                requested_by="operator@example.com",
                parameters={},
                preview_digest="preview",
                expected_revision="revision",
                policy_version="1",
                idempotency_key="polling",
            )
            gc.collect()
            baseline = len(os.listdir("/proc/self/fd"))
            for _ in range(2_000):
                self.assertIsNotNone(ledger.get(str(operation["operation_id"])))
            gc.collect()
            self.assertLessEqual(len(os.listdir("/proc/self/fd")), baseline + 3)


if __name__ == "__main__":
    unittest.main()
