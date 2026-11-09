from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_cli import run  # noqa: E402
from argus_workload_retire import prune  # noqa: E402

TEMPLATE = (ROOT / "docs" / "RETIRED_TEMPLATE.md").read_text(encoding="utf-8")


def write(root: Path, rel: str, value: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n", encoding="utf-8")


class FakeRunner:
    """Fake git/gh/check runner; ls-files reflects the fixture tree."""

    def __init__(self, root: Path, check_rc: int = 0, dirty: bool = False) -> None:
        self.root, self.check_rc, self.dirty, self.calls = root, check_rc, dirty, []

    def __call__(self, command: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        out = ""
        if command[:2] == ["git", "ls-files"]:
            out = "\0".join(str(p.relative_to(self.root)) for p in sorted(self.root.rglob("*")) if p.is_file())
        elif command[:2] == ["git", "status"]:
            out = " M x" if self.dirty else ""
        elif command[:3] == ["gh", "pr", "create"]:
            out = "https://github.com/pxm-0/argus/pull/999\n"
        rc = self.check_rc if command[0].endswith("argus-check") else 0
        return subprocess.CompletedProcess(command, rc, out, "")


class WorkloadRetireTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        r = self.root
        write(r, "config/workloads.json", {"workloads": [{"id": "gone", "name": "Gone", "paths": {"root": "/srv/argus/workloads/gone", "legacy": "/home/oreo/gone"}, "runtime": {"composeProject": "gone", "service": "web"}}, {"id": "gone-staging"}, {"id": "keep"}]})
        write(r, "config/access.json", {"workloads": {"gone": {"desired": "none"}, "keep": {"desired": "none"}}})
        write(r, "config/routes.json", {"workloadRoutes": {"gone": {"tailnet": {"url": "https://h:8446"}}, "keep": {}}})
        write(r, "config/argus/observation-sources.json", {"sources": [{"workload": "gone", "x": 1}, {"workload": "keep"}]})
        write(r, "config/argus/retired-workloads.json", {"schemaVersion": 1, "workloads": ["old"]})
        write(r, "workloads/gone/manifest.json", {"id": "gone"})
        write(r, "docs/NOTES.md", "mentions gone here\nbut not gone-staging\n")
        write(r, "docs/RETIRED_TEMPLATE.md", TEMPLATE)
        write(r, "scripts/argus-check", "#!/bin/sh\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def invoke(self, runner: FakeRunner, *args: str) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        code = run(["workload", "retire", *args, "--json"], repo=self.root, stdout=out, stderr=err, command_runner=runner)
        return code, json.loads(out.getvalue())

    def snapshot(self) -> dict[str, str]:
        return {str(p): p.read_text() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def test_apply_removes_every_reference_and_opens_pr(self) -> None:
        runner = FakeRunner(self.root)
        code, result = self.invoke(runner, "gone")
        self.assertEqual(code, 0, result)
        r = self.root
        self.assertNotIn("gone", json.loads((r / "config/access.json").read_text())["workloads"])
        self.assertIn("keep", json.loads((r / "config/access.json").read_text())["workloads"])
        self.assertNotIn("gone", json.loads((r / "config/routes.json").read_text())["workloadRoutes"])
        self.assertEqual(json.loads((r / "config/argus/observation-sources.json").read_text())["sources"], [{"workload": "keep"}])
        self.assertEqual([w["id"] for w in json.loads((r / "config/workloads.json").read_text())["workloads"]], ["gone-staging", "keep"])
        self.assertFalse((r / "workloads/gone").exists())
        self.assertEqual(json.loads((r / "config/argus/retired-workloads.json").read_text())["workloads"], ["gone", "old"])
        self.assertIn("Gone Retirement", (r / "docs/RETIRED_GONE.md").read_text())
        self.assertEqual(result["data"]["prUrl"], "https://github.com/pxm-0/argus/pull/999")
        self.assertEqual(result["data"]["textReferencesToReview"], {"docs/NOTES.md": 1})
        self.assertTrue(any(c[0].endswith("argus-check") for c in runner.calls))
        self.assertIn(["gh", "pr", "comment"], [c[:3] for c in runner.calls])

    def test_dry_run_writes_nothing_and_prints_runbook(self) -> None:
        before = self.snapshot()
        runner = FakeRunner(self.root)
        code, result = self.invoke(runner, "gone", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(before, self.snapshot())
        self.assertEqual([c[0] for c in runner.calls], ["git"])
        self.assertIn("1. Confirm a verified", result["data"]["runbook"])
        self.assertIn("argus m1 sync", result["data"]["runbook"])
        self.assertIn("config/access.json", result["data"]["jsonEdits"])

    def test_unknown_and_already_retired_ids_are_refused(self) -> None:
        for workload_id in ("nope", "old"):
            before = self.snapshot()
            code, result = self.invoke(FakeRunner(self.root), workload_id)
            self.assertEqual(code, 3)
            self.assertFalse(result["ok"])
            self.assertEqual(before, self.snapshot())

    def test_invalid_id_is_refused(self) -> None:
        code, result = self.invoke(FakeRunner(self.root), "../x")
        self.assertEqual(code, 2)

    def test_dirty_tree_is_refused_without_edits(self) -> None:
        before = self.snapshot()
        code, result = self.invoke(FakeRunner(self.root, dirty=True), "gone")
        self.assertEqual((code, result["error"]["code"]), (3, "tree-dirty"))
        self.assertEqual(before, self.snapshot())

    def test_failed_check_stops_before_commit(self) -> None:
        runner = FakeRunner(self.root, check_rc=1)
        code, result = self.invoke(runner, "gone")
        self.assertEqual((code, result["error"]["code"]), (3, "repository-check-failed"))
        self.assertNotIn("commit", [c[1] for c in runner.calls if c[0] == "git" and len(c) > 1])

    def test_prune_is_non_mutating_and_exact(self) -> None:
        original = {"gone": 1, "gone-staging": 2, "l": ["gone", "gone-staging", {"id": "gone"}]}
        self.assertEqual(prune(original, "gone"), {"gone-staging": 2, "l": ["gone-staging"]})
        self.assertIn("gone", original)

    def test_real_repo_dry_run_finds_references(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        first = json.loads((ROOT / "config/workloads.json").read_text())["workloads"][0]["id"]
        code = run(["workload", "retire", first, "--dry-run", "--json"], repo=ROOT, stdout=out, stderr=err)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("config/workloads.json", json.loads(out.getvalue())["data"]["jsonEdits"])


if __name__ == "__main__":
    unittest.main()
