import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import argus_cli_m1  # noqa: E402
from argus_cli import run  # noqa: E402
from argus_sqlite import ClosingConnection  # noqa: E402
from test_argus_m1_onboarded_workloads import ACCESS, OnboardedM1WorkloadRegistrationTests, canonical  # noqa: E402


class M1CliTests(OnboardedM1WorkloadRegistrationTests):
    """Reuses the fixture: new-b is missing from M1, retired-a is a declared stale row."""

    def cli(self, *argv: str, root: bool = True) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("argus_cli_m1.os.geteuid", return_value=0 if root else 1000):
            code = run([*argv, "--json"], repo=self.root, stdout=out, stderr=err)
        return code, json.loads(out.getvalue())

    def test_plan_lists_add_and_remove_without_changing_state(self) -> None:
        code, result = self.cli("m1", "sync")
        self.assertEqual(0, code)
        plan = result["data"]["plan"]
        for store in ("entities", "privacy", "access"):
            self.assertEqual((["new-b"], ["retired-a"], []), (plan[store]["add"], plan[store]["remove"], plan[store]["drift"]))
        self.assertRegex(plan["planDigest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual([], self.rows("entity-store.sqlite3", "SELECT 1 FROM entities WHERE entity_id = 'new-b'"))

    def test_digest_mismatch_refuses_and_changes_nothing(self) -> None:
        code, result = self.cli("m1", "sync", "--apply", "--confirm", "sha256:" + "0" * 64)
        self.assertEqual(3, code)
        self.assertEqual("m1-plan-digest-mismatch", result["error"]["code"])
        self.assertEqual(2, len(self.rows("entity-store.sqlite3", "SELECT 1 FROM entities")))

    def test_apply_requires_root(self) -> None:
        _, preview = self.cli("m1", "sync")
        code, result = self.cli("m1", "sync", "--apply", "--confirm", preview["data"]["plan"]["planDigest"], root=False)
        self.assertEqual((3, "m1-root-required"), (code, result["error"]["code"]))

    def test_apply_with_matching_digest_converges_and_is_idempotent(self) -> None:
        _, preview = self.cli("m1", "sync")
        digest = preview["data"]["plan"]["planDigest"]
        code, result = self.cli("m1", "sync", "--apply", "--confirm", digest)
        self.assertEqual(0, code)
        self.assertFalse(result["data"]["changes"])
        self.assertEqual(["new-b", "project-a"], [row[0] for row in self.rows("entity-store.sqlite3", "SELECT entity_id FROM entities ORDER BY entity_id")])
        sequence = self.ledger.checkpoint()["sequence"]
        _, clean = self.cli("m1", "sync")
        self.assertFalse(clean["data"]["changes"])
        code, again = self.cli("m1", "sync", "--apply", "--confirm", clean["data"]["plan"]["planDigest"])
        self.assertEqual(0, code)
        self.assertEqual(sequence, self.ledger.checkpoint()["sequence"])
        code, verified = self.cli("m1", "verify")
        self.assertEqual((0, True), (code, verified["data"]["verified"]))

    def test_drift_is_reported_and_applied_to_reviewed_config(self) -> None:
        self.cli("m1", "sync", "--apply", "--confirm", self.cli("m1", "sync")[1]["data"]["plan"]["planDigest"])
        with sqlite3.connect(self.runtime / "m1" / "state.sqlite3", factory=ClosingConnection) as connection:
            connection.execute("UPDATE access_projection SET entry_json = ? WHERE workload_id = 'project-a'", (canonical({**ACCESS, "lastError": "x"}),))
        _, preview = self.cli("m1", "sync")
        self.assertEqual(["project-a"], preview["data"]["plan"]["access"]["drift"])
        self.assertEqual("drift", argus_cli_m1.drift_status(self.root)["state"])
        code, _ = self.cli("m1", "sync", "--apply", "--confirm", preview["data"]["plan"]["planDigest"])
        self.assertEqual(0, code)
        self.assertEqual("clean", argus_cli_m1.drift_status(self.root)["state"])

    def test_missing_and_drifted_together_is_refused(self) -> None:
        with sqlite3.connect(self.runtime / "m1" / "state.sqlite3", factory=ClosingConnection) as connection:
            connection.execute("UPDATE access_projection SET entry_json = ? WHERE workload_id = 'project-a'", (canonical({**ACCESS, "lastError": "x"}),))
        _, preview = self.cli("m1", "sync")
        code, result = self.cli("m1", "sync", "--apply", "--confirm", preview["data"]["plan"]["planDigest"])
        self.assertEqual((3, "m1-plan-needs-legacy-path"), (code, result["error"]["code"]))

    def test_off_server_prints_ssh_command(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            out = io.StringIO()
            code = run(["m1", "verify", "--json"], repo=Path(empty), stdout=out, stderr=io.StringIO())
        error = json.loads(out.getvalue())["error"]
        self.assertEqual((3, "m1-server-only"), (code, error["code"]))
        self.assertIn("ssh oreochiserver 'sudo /srv/argus/scripts/argus m1 verify --json'", error["nextAction"])
        self.assertEqual({"state": "not-applicable"}, argus_cli_m1.drift_status(Path(empty)))

    def test_human_plan_is_diff_style(self) -> None:
        out = io.StringIO()
        run(["m1", "sync"], repo=self.root, stdout=out, stderr=io.StringIO())
        self.assertIn("+ entities new-b", out.getvalue())
        self.assertIn("- entities retired-a", out.getvalue())
        self.assertIn("PLAN_DIGEST sha256:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
