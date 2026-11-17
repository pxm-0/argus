from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-access-effective-migrate"
sys.path.insert(0, str(ROOT / "scripts"))

from argus_access_state import load_access  # noqa: E402


REVIEWED = {
    "version": 1,
    "states": ["none", "local", "tailnet", "cloudflare-protected"],
    "workloads": {
        "site": {"desired": "cloudflare-protected", "effective": "none", "urls": {"local": ""}, "lastAppliedAt": "", "lastError": ""},
        "tool": {"desired": "tailnet", "effective": "tailnet", "urls": {}, "lastAppliedAt": "a", "lastError": ""},
    },
}


def dumps(value: dict) -> str:
    return json.dumps(value, indent=2) + "\n"


class MigrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name)
        (self.repo / "config").mkdir()
        self.access = self.repo / "config" / "access.json"
        self.access.write_text(dumps(REVIEWED))
        self.access.chmod(0o664)
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "config/access.json"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        self.head = self.access.read_bytes()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def dirty(self, **changes: dict) -> dict:
        value = json.loads(json.dumps(REVIEWED))
        for workload_id, fields in changes.items():
            value["workloads"][workload_id].update(fields)
        self.access.write_text(dumps(value))
        return value

    def run_script(self, *args: str) -> tuple[int, dict]:
        env = {**os.environ, "ARGUS_ROOT": str(self.repo), "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_dirty_file_becomes_a_matching_overlay_and_a_clean_reviewed_file(self) -> None:
        working = self.dirty(site={"effective": "cloudflare-protected", "lastAppliedAt": "2026-11-01T00:00:00Z"})
        code, result = self.run_script("--apply")
        self.assertEqual(0, code, result)
        self.assertEqual(["site"], result["workloads"])
        self.assertEqual(self.head, self.access.read_bytes())
        self.assertEqual(0o664, self.access.stat().st_mode & 0o777)
        self.assertEqual(working, load_access(self.repo / "config"))
        overlay = json.loads((self.repo / "config" / "access.effective.json").read_text())
        self.assertEqual({"site": {"effective": "cloudflare-protected", "lastAppliedAt": "2026-11-01T00:00:00Z", "lastError": ""}}, overlay["workloads"])
        self.assertEqual(working, json.loads(Path(result["backup"]).read_text()))
        self.assertEqual(0, subprocess.run(["git", "-C", str(self.repo), "diff", "--quiet"], check=False).returncode)

    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        self.dirty(site={"effective": "cloudflare-protected"})
        before = self.access.read_bytes()
        code, result = self.run_script()
        self.assertEqual((0, False), (code, result["apply"]))
        self.assertEqual(["site"], sorted(result["overlay"]["workloads"]))
        self.assertEqual(before, self.access.read_bytes())
        self.assertFalse((self.repo / "config" / "access.effective.json").exists())
        self.assertFalse((self.repo / "runtime").exists())

    def test_refuses_any_reviewed_difference(self) -> None:
        cases = {
            "desired": lambda: self.dirty(site={"desired": "tailnet"}),
            "urls": lambda: self.dirty(site={"urls": {"local": "http://127.0.0.1:1"}}),
            "states": lambda: self.access.write_text(dumps({**REVIEWED, "states": ["none"]})),
            "workload set": lambda: self.access.write_text(dumps({**REVIEWED, "workloads": {"site": REVIEWED["workloads"]["site"]}})),
        }
        for name, make in cases.items():
            with self.subTest(name):
                make()
                before = self.access.read_bytes()
                code, result = self.run_script("--apply")
                self.assertEqual((2, False), (code, result["ok"]))
                self.assertEqual(before, self.access.read_bytes())
                self.assertFalse((self.repo / "config" / "access.effective.json").exists())

    def test_refuses_a_dangling_prepared_journal_record(self) -> None:
        self.dirty(site={"effective": "cloudflare-protected"})
        journal = self.repo / "runtime" / "argus" / "m1" / "access-journal.jsonl"
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({"phase": "PREPARED", "transactionId": "t1"}) + "\n")
        code, result = self.run_script("--apply")
        self.assertEqual(2, code)
        self.assertIn("PREPARED", result["reason"])
        journal.write_text(journal.read_text() + json.dumps({"phase": "COMMITTED", "transactionId": "t1"}) + "\n")
        self.assertEqual(0, self.run_script("--apply")[0])

    def test_is_idempotent(self) -> None:
        working = self.dirty(site={"effective": "cloudflare-protected"})
        self.assertEqual(0, self.run_script("--apply")[0])
        overlay = (self.repo / "config" / "access.effective.json").read_bytes()
        code, result = self.run_script("--apply")
        self.assertEqual((0, True), (code, result["alreadyMigrated"]))
        self.assertEqual(overlay, (self.repo / "config" / "access.effective.json").read_bytes())
        self.assertEqual(working, load_access(self.repo / "config"))
        # An interrupted run (overlay written, file still dirty) completes on the next run.
        self.dirty(site={"effective": "cloudflare-protected"})
        self.assertEqual(0, self.run_script("--apply")[0])
        self.assertEqual(self.head, self.access.read_bytes())


if __name__ == "__main__":
    unittest.main()
