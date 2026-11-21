"""argus release apply, task 1/5 (#427): guards, sha trust, release activation and history.

Spec: docs/RELEASE_APPLY.md. Everything runs unprivileged against temp roots: euid is injected and the
release owner is the test user instead of root.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / relative))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


installer = load("argus_release_install", "scripts/argus-release-install")
apply_module = load("argus_release_apply", "scripts/argus-release-apply")

OWNER = (os.getuid(), os.getgid())
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}
NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                            capture_output=True, text=True, check=True, env=ENV)
    return result.stdout.strip()


def write(repo: Path, relative: str, text: str, mode: int = 0o644) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def tree_digest(*roots: Path) -> str:
    """Bytes, modes, link targets and mtimes of everything under `roots`."""
    digest = hashlib.sha256()
    for root in roots:
        if not root.exists():
            digest.update(f"absent {root}\n".encode())
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            for name in sorted([*dirs, *files]):
                path = Path(current, name)
                info = path.lstat()
                digest.update(f"{path} {info.st_mode} {info.st_mtime_ns}\n".encode())
                if path.is_symlink():
                    digest.update(os.readlink(path).encode())
                elif path.is_file():
                    digest.update(path.read_bytes())
    return digest.hexdigest()


class FakeRunner:
    """The only subprocess seam. The installer argv runs install_release in-process as the test user."""

    def __init__(self, source: Path, prefix: Path) -> None:
        self.source, self.prefix, self.calls, self.fail_install = source, prefix, [], False

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        if argv[0].endswith("scripts/argus-release-install"):
            if self.fail_install:
                return subprocess.CompletedProcess(argv, 3, "", "refused: injected\n")
            installer.install_release(argv[argv.index("--sha") + 1], source=self.source, prefix=self.prefix, owner=OWNER)
            return subprocess.CompletedProcess(argv, 0, "installed\n", "")
        raise AssertionError(f"unexpected command {argv}")


class ApplyFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name).resolve()
        self.tmp = tmp
        self.source, self.prefix, self.state = tmp / "srv-argus", tmp / "opt-argus", tmp / "var-lib-argus-releases"
        self.source.mkdir()
        git(self.source, "init", "-q", "-b", "main")
        write(self.source, "scripts/argus", "#!/usr/bin/env python3\n", 0o755)
        write(self.source, "config/a.json", "{}\n")
        write(self.source, "runtime/.gitkeep", "")
        write(self.source, "control-plane/dashboard/public/.gitkeep", "")
        git(self.source, "add", "-A")
        git(self.source, "commit", "-q", "-m", "one")
        self.first = git(self.source, "rev-parse", "HEAD")
        self.set_main(self.first)
        # Bootstrap stays manual (root-owned-release.md): current must already point into releases/.
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install_release(self.first, source=self.source, prefix=self.prefix, owner=OWNER)
        self.boot_id = tmp / "boot_id"
        self.boot_id.write_text("boot-1\n")
        self.roots = apply_module.Roots(
            prefix=self.prefix, source=self.source, state_dir=self.state,
            lock=tmp / "apply.lock", boot_id=self.boot_id,
        )
        self.runner = FakeRunner(self.source, self.prefix)

    def set_main(self, sha: str) -> None:
        git(self.source, "update-ref", "refs/remotes/origin/main", sha)

    def commit(self, text: str) -> str:
        write(self.source, "config/a.json", text)
        git(self.source, "commit", "-q", "-am", text.strip())
        sha = git(self.source, "rev-parse", "HEAD")
        self.set_main(sha)
        return sha

    def run_apply(self, sha: str, *, confirm: str | None = None, euid: int = 0, environ: dict | None = None,
                  script_path: Path | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = apply_module.apply(
                sha, plan_only=confirm is None, confirm=confirm, roots=self.roots, runner=self.runner,
                now=lambda: NOW, euid=euid, environ=environ if environ is not None else {},
                script_path=script_path or ROOT / "scripts" / "argus-release-apply", owner=OWNER,
            )
        return code, out.getvalue(), err.getvalue()

    def plan_digest(self, sha: str) -> str:
        code, out, err = self.run_apply(sha)
        self.assertEqual(0, code, err)
        lines = [line for line in out.splitlines() if line.startswith("planDigest: ")]
        self.assertEqual(1, len(lines), out)
        return lines[0].removeprefix("planDigest: ")

    def apply_confirmed(self, sha: str) -> tuple[int, str, str]:
        return self.run_apply(sha, confirm=self.plan_digest(sha))

    def current(self) -> Path:
        return (self.prefix / "current").resolve()

    def history(self) -> list[dict]:
        path = self.state / "history.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class PlanTests(ApplyFixture):
    def test_plan_writes_nothing_and_runs_no_command(self) -> None:
        second = self.commit('{"v": 2}\n')
        before = tree_digest(self.prefix, self.state, self.source)
        code, out, _ = self.run_apply(second)
        self.assertEqual(0, code)
        self.assertIn("action: install", out)
        self.assertIn(f"previous: {self.first}", out)
        self.assertIn("gh pr view", out)  # the operator-attested CI gate
        self.assertEqual(before, tree_digest(self.prefix, self.state, self.source))
        self.assertEqual([], self.runner.calls)

    def test_digest_is_stable_and_a_changed_world_refuses_confirm(self) -> None:
        second = self.commit('{"v": 2}\n')
        digest = self.plan_digest(second)
        self.assertEqual(digest, self.plan_digest(second))
        self.boot_id.write_text("boot-2\n")  # anything bound into the digest moving must invalidate it
        code, _, err = self.run_apply(second, confirm=digest)
        self.assertEqual(3, code)
        self.assertIn("plan changed", err)
        self.assertEqual(self.prefix / "releases" / self.first, self.current())
        self.assertEqual([], self.history())


class GuardTests(ApplyFixture):
    def test_requires_root(self) -> None:
        self.assertEqual(3, self.run_apply(self.first, euid=1000)[0])

    def test_refuses_any_sudo_environment(self) -> None:
        for name in ("SUDO_USER", "SUDO_UID", "SUDO_COMMAND"):
            code, _, err = self.run_apply(self.first, environ={name: "x"})
            self.assertEqual(3, code, name)
            self.assertIn("root shell", err)

    def test_refuses_a_script_that_lives_in_a_writable_directory(self) -> None:
        unsealed = self.tmp / "unsealed"
        unsealed.mkdir()
        unsealed.chmod(0o775)
        script = unsealed / "argus-release-apply"
        script.write_text("")
        code, _, err = self.run_apply(self.first, script_path=script)
        self.assertEqual(3, code)
        self.assertIn("not sealed", err)

    def test_lock_held_exits_4(self) -> None:
        with open(self.roots.lock, "w") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            code, _, err = self.run_apply(self.first)
        self.assertEqual(4, code)
        self.assertIn("another apply", err)

    def test_unreadable_current_stamp_is_a_refusal_not_a_traceback(self) -> None:
        (self.prefix / "releases" / self.first / installer.STAMP).unlink()
        code, _, err = self.run_apply(self.first)
        self.assertEqual(3, code)
        self.assertIn("cannot read", err)

    def test_bootstrap_stays_manual_when_current_is_not_a_release_symlink(self) -> None:
        (self.prefix / "current").unlink()
        (self.prefix / "current").mkdir()
        code, _, err = self.run_apply(self.first)
        self.assertEqual(3, code)
        self.assertIn("bootstrap", err)


class TrustTests(ApplyFixture):
    def test_missing_commit_names_the_oreo_fetch_command(self) -> None:
        code, _, err = self.run_apply("a" * 40)
        self.assertEqual(3, code)
        self.assertIn("runuser -u oreo -- git -C", err)

    def test_refuses_a_commit_not_reachable_from_origin_main(self) -> None:
        git(self.source, "switch", "-q", "-c", "side")
        side = self.commit('{"side": 1}\n')
        self.set_main(self.first)
        code, _, err = self.run_apply(side)
        self.assertEqual(3, code)
        self.assertIn("not reachable", err)

    def test_refuses_a_branch_commit_that_is_only_reachable_through_a_merge(self) -> None:
        git(self.source, "switch", "-q", "-c", "feature")
        branch_commit = self.commit('{"feature": 1}\n')
        git(self.source, "switch", "-q", "main")
        git(self.source, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "feature")
        merge = git(self.source, "rev-parse", "HEAD")
        self.set_main(merge)
        code, _, err = self.run_apply(branch_commit)
        self.assertEqual(3, code)
        self.assertIn("not a merge to main", err)
        self.assertEqual(0, self.run_apply(merge)[0])

    def test_refuses_malformed_sha(self) -> None:
        for bad in (self.first[:12], self.first.upper(), "main"):
            self.assertEqual(3, self.run_apply(bad)[0], bad)


class ActivationTests(ApplyFixture):
    def test_install_runs_the_previously_trusted_installer_and_records_history(self) -> None:
        second = self.commit('{"v": 2}\n')
        code, out, err = self.apply_confirmed(second)
        self.assertEqual(0, code, err)
        self.assertEqual(self.prefix / "releases" / second, self.current())
        installer_call = self.runner.calls[0]
        self.assertEqual(str(self.prefix / "releases" / self.first / "scripts/argus-release-install"), installer_call[0])
        self.assertEqual(["--sha", second], installer_call[1:])
        started, finished = self.history()
        self.assertEqual(("started", "finished"), (started["phase"], finished["phase"]))
        self.assertEqual(started["runId"], finished["runId"])
        self.assertRegex(started["runId"], rf"^20261121T120000Z-\d+-{second[:12]}$")
        for row in (started, finished):
            self.assertEqual(second, row["sha"])
            self.assertEqual(self.first, row["previousSha"])
            self.assertEqual("install", row["action"])
            self.assertEqual({"source": "operator-attested"}, row["checks"])
            self.assertTrue(row["planDigest"].startswith("sha256:"))
        self.assertEqual(("applied", 0), (finished["outcome"], finished["exit"]))
        self.assertEqual(f"argus release apply --sha {self.first} --plan", finished["rollbackCommand"])
        plan = json.loads((self.state / "runs" / started["runId"] / "plan.json").read_text())
        self.assertEqual(second, plan["sha"])
        self.assertIn(f"applied {second}", out)

    def test_installer_refusal_after_intent_exits_5_with_a_rollback_line(self) -> None:
        second = self.commit('{"v": 2}\n')
        self.runner.fail_install = True
        code, _, err = self.apply_confirmed(second)
        self.assertEqual(5, code)
        self.assertIn(f"argus release apply --sha {self.first} --plan", err)
        self.assertEqual(self.prefix / "releases" / self.first, self.current())
        self.assertEqual(["started", "finished"], [row["phase"] for row in self.history()])
        self.assertEqual(("failed", 5), (self.history()[-1]["outcome"], self.history()[-1]["exit"]))

    def test_reapply_is_a_noop_with_a_new_row(self) -> None:
        code, out, err = self.apply_confirmed(self.first)
        self.assertEqual(0, code, err)
        self.assertIn("action: noop", out)
        self.assertEqual([], self.runner.calls)
        self.assertEqual("noop", self.history()[-1]["outcome"])

    def test_rollback_switches_back_with_a_warning(self) -> None:
        second = self.commit('{"v": 2}\n')
        self.assertEqual(0, self.apply_confirmed(second)[0])
        code, out, _ = self.run_apply(self.first)
        self.assertEqual(0, code)
        self.assertIn("action: switch", out)
        self.assertIn("ROLLBACK: forward-only schema migrations are not undone", out)
        self.assertEqual(0, self.apply_confirmed(self.first)[0])
        self.assertEqual(self.prefix / "releases" / self.first, self.current())
        self.assertTrue(self.history()[-1]["rollback"])
        self.assertEqual(1, len(self.runner.calls))  # switch never reinstalls

    def test_a_dangling_started_row_is_shown_and_bound_into_the_digest(self) -> None:
        second = self.commit('{"v": 2}\n')
        before = self.plan_digest(second)
        self.state.mkdir(parents=True)
        (self.state / "history.jsonl").write_text(json.dumps({"runId": "crashed-run", "phase": "started"}) + "\n")
        code, out, _ = self.run_apply(second)
        self.assertEqual(0, code)
        self.assertIn("crashed-run", out)
        self.assertNotEqual(before, self.plan_digest(second))
        self.assertEqual(0, self.apply_confirmed(second)[0])
        self.assertEqual("crashed-run", self.history()[-1]["resumesRunId"])
        # Confirming acknowledged it: later plans no longer carry it.
        code, out, _ = self.run_apply(second)
        self.assertEqual(0, code)
        self.assertNotIn("crashed-run", out)

    def test_evidence_never_touches_the_operator_owned_runtime(self) -> None:
        before = tree_digest(self.source / "runtime")
        self.assertEqual(0, self.apply_confirmed(self.commit('{"v": 2}\n'))[0])
        self.assertEqual(before, tree_digest(self.source / "runtime"))


class TamperTests(ApplyFixture):
    def setUp(self) -> None:
        super().setUp()
        self.second = self.commit('{"v": 2}\n')
        self.assertEqual(0, self.apply_confirmed(self.second)[0])
        self.old = self.prefix / "releases" / self.first

    def assert_switch_refused(self) -> None:
        code, _, err = self.run_apply(self.first)
        self.assertEqual(3, code)
        self.assertIn("release dir tampered", err)
        self.assertEqual(self.prefix / "releases" / self.second, self.current())

    def test_changed_byte_is_refused(self) -> None:
        (self.old / "config/a.json").chmod(0o644)
        (self.old / "config/a.json").write_text("{ }\n")
        self.assert_switch_refused()

    def test_extra_file_is_refused(self) -> None:
        (self.old / "scripts" / "planted.py").write_text("x = 1\n")
        self.assert_switch_refused()

    def test_group_writable_file_is_refused(self) -> None:
        (self.old / "config/a.json").chmod(0o664)
        self.assert_switch_refused()

    def test_redirected_state_symlink_is_refused(self) -> None:
        (self.old / "runtime").unlink()
        (self.old / "runtime").symlink_to(self.tmp)
        self.assert_switch_refused()

    def test_wrong_stamp_is_refused(self) -> None:
        (self.old / installer.STAMP).write_text(self.second + "\n")
        self.assert_switch_refused()


class StaticTests(unittest.TestCase):
    def test_never_fetches_runs_status_or_archive_or_writes_the_runtime_audit_log(self) -> None:
        source = (ROOT / "scripts" / "argus-release-apply").read_text()
        for forbidden in ('"status"', '"archive"', '"fetch"', "audit("):
            self.assertNotIn(forbidden, source)

    def test_cli_rejects_bad_invocations_with_exit_2(self) -> None:
        malformed = [["--sha", bad, "--plan"] for bad in ("a" * 12, "A" * 40, "main")]
        for argv in ([], ["--sha", "a" * 40], ["--sha", "a" * 40, "--plan", "--confirm", "x"], ["--sha", "a" * 40, "--plan", "extra"], *malformed):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                apply_module.parse_args(argv)
            self.assertEqual(2, raised.exception.code, argv)


if __name__ == "__main__":
    unittest.main()
