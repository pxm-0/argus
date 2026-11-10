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

from argus_cli import render_human, run  # noqa: E402
from argus_workload_retire import prune  # noqa: E402

TEMPLATE = (ROOT / "docs" / "RETIRED_TEMPLATE.md").read_text(encoding="utf-8")


def write(root: Path, rel: str, value: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n", encoding="utf-8")


class FakeRunner:
    """Fake git/gh/check runner; ls-files reflects the fixture tree."""

    def __init__(self, root: Path, check_rc: int = 0, dirty: bool = False, head: str = "abc\n", branch_exists: bool = False, noisy_url: bool = False) -> None:
        self.root, self.check_rc, self.dirty, self.calls = root, check_rc, dirty, []
        self.head, self.branch_exists, self.noisy_url = head, branch_exists, noisy_url

    def __call__(self, command: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        out = ""
        if command[:2] == ["git", "ls-files"]:
            out = "\0".join(str(p.relative_to(self.root)) for p in sorted(self.root.rglob("*")) if p.is_file())
        elif command[:2] == ["git", "status"]:
            out = " M x" if self.dirty else ""
        elif command[:3] == ["gh", "pr", "create"]:
            out = "https://github.com/pxm-0/argus/pull/999\n"
        elif command[:3] == ["git", "rev-parse", "HEAD"] or command[:3] == ["git", "rev-parse", "origin/main"]:
            out = self.head
        rc = self.check_rc if command[0].endswith("argus-check") else 0
        if command[:3] == ["git", "rev-parse", "--verify"]:
            rc = 0 if self.branch_exists else 1
        if command[:3] == ["gh", "pr", "create"] and self.noisy_url:
            out = "Warning: something\n" + out
        return subprocess.CompletedProcess(command, rc, out, "")


class WorkloadRetireTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        r = self.root
        write(r, "config/workloads.json", {"workloads": [{"id": "gone", "name": "Gone", "paths": {"root": "/srv/argus/workloads/gone", "legacy": "/home/oreo/gone"}, "runtime": {"composeProject": "gone", "service": "web"}, "migration": {"targetTrustDomain": "personal-sandbox"}}, {"id": "gone-staging"}, {"id": "keep"}]})
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
        self.assertIn("argus-m1-reconcile-retired-workloads` (preview)", result["data"]["runbook"])
        self.assertIn("--apply --acknowledge-retired-workload-reconciliation", result["data"]["runbook"])
        self.assertNotIn("argus m1 sync", result["data"]["runbook"])
        self.assertIn("config/access.json", result["data"]["jsonEdits"])

    def test_human_render_of_dry_runs_never_crashes(self) -> None:
        cases = [
            ({"command": "workload.retire", "dryRun": True, "runbook": "1. step\n"}, "1. step"),
            ({"command": "release.pin", "dryRun": True, "diff": "--- a\n+++ b\n"}, "+++ b"),
            ({"command": "workload.retire", "dryRun": True}, '"dryRun": true'),
        ]
        for data, expected in cases:
            out, err = io.StringIO(), io.StringIO()
            render_human({"ok": True, "data": data}, out, err, "")
            self.assertIn(expected, out.getvalue())

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

    def test_head_not_main_and_existing_branch_are_refused(self) -> None:
        class Moved(FakeRunner):
            def __call__(self, command, repo):
                result = super().__call__(command, repo)
                if command[:3] == ["git", "rev-parse", "origin/main"]:
                    result.stdout = "def\n"
                return result

        before = self.snapshot()
        code, result = self.invoke(Moved(self.root), "gone")
        self.assertEqual((code, result["error"]["code"]), (3, "head-not-main"))
        code, result = self.invoke(FakeRunner(self.root, branch_exists=True), "gone")
        self.assertEqual((code, result["error"]["code"]), (3, "branch-exists"))
        self.assertEqual(before, self.snapshot())

    def test_pr_url_is_last_line_of_gh_output(self) -> None:
        code, result = self.invoke(FakeRunner(self.root, noisy_url=True), "gone")
        self.assertEqual(result["data"]["prUrl"], "https://github.com/pxm-0/argus/pull/999")

    def test_templates_systemd_units_are_listed(self) -> None:
        write(self.root, "templates/systemd/gone-backup.timer", "[Timer]\n")
        code, result = self.invoke(FakeRunner(self.root), "gone", "--dry-run")
        self.assertEqual(result["data"]["unitFiles"], ["templates/systemd/gone-backup.timer"])
        self.assertIn("templates/systemd/gone-backup.timer", result["data"]["runbook"])

    def test_unit_matching_ignores_longer_workload_ids(self) -> None:
        write(self.root, "systemd/argus-gone.service", "[Service]\n")
        write(self.root, "systemd/argus-gone-staging.service", "[Service]\n")
        write(self.root, "systemd/argus-gonesome.service", "[Service]\n")
        code, result = self.invoke(FakeRunner(self.root), "gone", "--dry-run")
        self.assertEqual(result["data"]["unitFiles"], ["systemd/argus-gone.service"])

    def runbook(self, workload_id: str = "gone") -> str:
        return self.invoke(FakeRunner(self.root), workload_id, "--dry-run")[1]["data"]["runbook"]

    def test_runbook_step_zero_removes_timer_first(self) -> None:
        rb = self.runbook()
        step0 = next(line for line in rb.splitlines() if line.startswith("0. "))
        self.assertIn("argus-m5-workload-gone.timer", step0)
        self.assertIn("argus-m5-workload-gone.service", step0)
        self.assertIn("systemctl list-unit-files | grep gone` prints nothing", step0)

    def test_runbook_backup_step_names_snapshot_and_restore_dry_run(self) -> None:
        step1 = next(line for line in self.runbook().splitlines() if line.startswith("1. "))
        self.assertIn("snapshot ID", step1)
        self.assertIn("argus-backup-restore --workload gone --artifact-id <snapshot-id> --acknowledge-isolated-restore", step1)
        self.assertIn("sudo python3 scripts/argus-backup-restore", step1)
        self.assertIn("python3 scripts/argus-backup-run gone --confirm gone", step1)
        self.assertIn("argus-m5-workload-staging/gone/", step1)

    def test_runbook_serve_off_and_listener_check(self) -> None:
        rb = self.runbook()
        self.assertIn("sudo tailscale serve --https=8446 off", rb)
        self.assertIn("tailscale serve status", rb)
        self.assertIn("ss -ltn", rb)

    def test_runbook_directories_and_legacy_clone_wait_for_backup(self) -> None:
        rb = self.runbook()
        for path in ("/var/lib/argus/migration-runtime/personal-sandbox/gone", "/var/lib/argus/migration-staging/personal-sandbox/gone", "/var/lib/argus/migration-cutovers/gone", "/var/backups/argus-m5-workload-staging/gone"):
            self.assertIn(path, rb)
        self.assertIn("KEEP `/var/lib/argus/migration-cutovers/gone`", rb)
        self.assertIn("keep it until then", rb)
        self.assertLess(rb.index("Directories, each only after"), rb.index("legacy source checkout"))

    def test_runbook_nodens_residue_is_classified(self) -> None:
        write(self.root, "config/workloads.json", {"workloads": [{"id": "nodens", "runtime": {"composeProject": "nodens"}}]})
        write(self.root, "config/routes.json", {"workloadRoutes": {"nodens": {"tailnet": {"url": "https://h:8444"}}}})
        rb = self.runbook("nodens")
        self.assertIn("sudo tailscale serve --https=8444 off", rb)
        self.assertIn("`nodens-live_postgres-data` (KEEP)", rb)
        self.assertIn("`nodens-live_caddy-data` (REMOVE)", rb)
        for network in ("nodens_default", "nodens-net", "nodens-sprint55-net"):
            self.assertIn(f"docker network rm {network}", rb)
        self.assertIn("docker image rm sha256:2633eeb26a5f", rb)

    def test_runbook_warns_when_image_digest_is_shared(self) -> None:
        shared = "sha256:" + "e8f2abf0300b" + "0" * 52
        own = "sha256:" + "1" * 64
        write(self.root, "workloads/gone/source/compose.yml", f"services:\n  a:\n    image: {shared}  # x\n  b:\n    image: {own}\n")
        write(self.root, "workloads/gone-staging/source/compose.yml", f"services:\n  a:\n    image: {shared}\n")
        rb = self.runbook()
        self.assertIn(f"WARNING: `{shared[:19]}` is also pinned by `gone-staging`; do NOT remove it", rb)
        self.assertIn(f"docker image rm {own[:19]}", rb)
        self.assertNotIn(f"docker image rm {shared[:19]}", rb)

    def test_real_repo_staging_runbook_warns_about_production_image(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        code = run(["workload", "retire", "nodens-staging", "--dry-run", "--json"], repo=ROOT, stdout=out, stderr=err)
        self.assertEqual(code, 0, out.getvalue())
        rb = json.loads(out.getvalue())["data"]["runbook"]
        self.assertIn("`sha256:e8f2abf0300b` is also pinned by `nodens-production`", rb)

    def test_failed_check_opens_draft_pr(self) -> None:
        runner = FakeRunner(self.root, check_rc=1)
        code, result = self.invoke(runner, "gone")
        self.assertEqual((code, result["data"]["checks"]), (0, "fail"))
        create = next(c for c in runner.calls if c[:3] == ["gh", "pr", "create"])
        self.assertIn("--draft", create)

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
