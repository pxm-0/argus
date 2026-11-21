"""argus release apply: guards, sha trust, release activation and history (#427), /etc convergence (#428).

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
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / relative))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules[cls.__module__]
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
        self.visudo_file_ok, self.visudo_live_results = True, []  # results for successive `visudo -c`
        self.sysusers_results: list[bool] = []  # results for successive systemd-sysusers runs (default ok)

    def commands(self) -> list[list[str]]:
        """Calls with the installer path and temp file names reduced to stable words."""
        return [["installer"] if call[0].endswith("argus-release-install") else call[:2] for call in self.calls]

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        if argv[:2] == ["/usr/sbin/visudo", "-cf"]:
            return subprocess.CompletedProcess(argv, 0 if self.visudo_file_ok else 1, "", "" if self.visudo_file_ok else "syntax error\n")
        if argv == ["/usr/sbin/visudo", "-c"]:
            ok = self.visudo_live_results.pop(0) if self.visudo_live_results else True
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "")
        if argv == ["/usr/bin/systemd-sysusers"]:
            ok = self.sysusers_results.pop(0) if self.sysusers_results else True
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "" if ok else "sysusers failed\n")
        if argv == ["/usr/bin/systemctl", "daemon-reload"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
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
        self.etc = apply_module.etc.EtcRoots(systemd=tmp / "etc/systemd/system", sysusers=tmp / "etc/sysusers.d", sudoers=tmp / "etc/sudoers.d")
        for folder in (self.etc.systemd, self.etc.sysusers, self.etc.sudoers):
            folder.mkdir(parents=True)
        self.roots = apply_module.Roots(
            prefix=self.prefix, source=self.source, state_dir=self.state,
            lock=tmp / "apply.lock", boot_id=self.boot_id, etc_roots=self.etc,
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
                  script_path: Path | None = None, now: datetime = NOW) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = apply_module.apply(
                sha, plan_only=confirm is None, confirm=confirm, roots=self.roots, runner=self.runner,
                now=lambda: now, euid=euid, environ=environ if environ is not None else {},
                script_path=script_path or ROOT / "scripts" / "argus-release-apply", owner=OWNER,
            )
        return code, out.getvalue(), err.getvalue()

    def plan_digest(self, sha: str) -> str:
        code, out, err = self.run_apply(sha)
        self.assertEqual(0, code, err)
        lines = [line for line in out.splitlines() if line.startswith("planDigest: ")]
        self.assertEqual(1, len(lines), out)
        return lines[0].removeprefix("planDigest: ")

    def apply_confirmed(self, sha: str, now: datetime = NOW) -> tuple[int, str, str]:
        return self.run_apply(sha, confirm=self.plan_digest(sha), now=now)

    def current(self) -> Path:
        return (self.prefix / "current").resolve()

    def history(self) -> list[dict]:
        path = self.state / "history.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class PlanTests(ApplyFixture):
    def test_plan_writes_nothing_and_runs_no_command(self) -> None:
        second = self.commit('{"v": 2}\n')
        before = tree_digest(self.prefix, self.state, self.source, self.tmp / "etc")
        code, out, _ = self.run_apply(second)
        self.assertEqual(0, code)
        self.assertIn("action: install", out)
        self.assertIn(f"previous: {self.first}", out)
        self.assertIn("gh pr view", out)  # the operator-attested CI gate
        self.assertEqual(before, tree_digest(self.prefix, self.state, self.source, self.tmp / "etc"))
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
        self.assertEqual([["installer"], ["/usr/bin/systemctl", "daemon-reload"]], self.runner.commands())
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
        self.assertEqual(1, self.runner.commands().count(["installer"]))  # switch never reinstalls

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


API_UNIT = "[Service]\nWorkingDirectory=/srv/argus\nExecStart=/srv/argus/scripts/argus-control-api\n"
WORKLOAD_UNIT = "[Service]\nExecStart=/srv/argus/scripts/argus-m5-workload-x\n"  # generated on the host, not in the repo


class EtcTests(ApplyFixture):
    """docs/RELEASE_APPLY.md steps 6 and 11: drift is planned, digested, then converged with backups."""

    def setUp(self) -> None:
        super().setUp()
        (self.source / "scripts" / "argus_sudoers.py").write_bytes((ROOT / "scripts" / "argus_sudoers.py").read_bytes())
        write(self.source, "systemd/argus-control-api.service", API_UNIT)
        write(self.source, "systemd/argus-new.service", "[Service]\nExecStart=/bin/true\n")
        write(self.source, "systemd/argus-smoke.service.d/onfailure.conf", "[Unit]\nOnFailure=x\n")
        write(self.source, "systemd/sysusers.d/argus-api.conf", "u argus-api - - /nonexistent\n")
        write(self.source, "templates/systemd/argus-control-api.service", "[Service]\nExecStart=/srv/argus/TEMPLATE\n")
        write(self.source, "deploy/sudoers/argus-operator", "Defaults:oreo env_reset\n")
        git(self.source, "add", "-A")
        git(self.source, "commit", "-q", "-m", "etc")
        self.release = git(self.source, "rev-parse", "HEAD")
        self.set_main(self.release)
        write(self.etc.systemd, "argus-control-api.service", "[Service]\nExecStart=/srv/argus/old\n")
        write(self.etc.systemd, "argus-control-api.service.d/99-local.conf", "[Service]\nNice=5\n")
        write(self.etc.systemd, "argus-smoke.service", "[Service]\nExecStart=/srv/argus/scripts/argus-smoke-scheduled\n")
        write(self.etc.systemd, "argus-m5-workload-x.service", WORKLOAD_UNIT)
        write(self.etc.sysusers, "argus-api.conf", "u argus-api - - /old\n")

    def etc_text(self, relative: str) -> str:
        return (self.tmp / "etc" / relative).read_text()

    def test_plan_lists_every_change_writes_nothing_and_binds_etc_bytes(self) -> None:
        before = tree_digest(self.tmp / "etc")
        code, out, _ = self.run_apply(self.release)
        self.assertEqual(0, code)
        self.assertEqual(before, tree_digest(self.tmp / "etc"))
        self.assertEqual([], self.runner.calls)
        for line in (
            f"update                   {self.etc.systemd}/argus-control-api.service",
            f"create                   {self.etc.systemd}/argus-smoke.service.d/onfailure.conf",
            f"create                   {self.etc.systemd}/argus-control-api.service.d/10-argus-release.conf",
            f"create                   {self.etc.systemd}/argus-m5-workload-x.service.d/10-argus-release.conf",
            f"update                   {self.etc.sysusers}/argus-api.conf",
            f"create                   {self.etc.sudoers}/argus-operator",
            f"available-not-installed  {self.etc.systemd}/argus-new.service (report only)",
        ):
            self.assertIn(line, out)
        self.assertIn("+ExecStart=/srv/argus/scripts/argus-control-api", out)  # capped unified diff
        digest = self.plan_digest(self.release)
        (self.etc.systemd / "argus-control-api.service.d" / "99-local.conf").write_text("[Service]\nNice=6\n")
        self.assertEqual(digest, self.plan_digest(self.release))  # unmanaged files are not ours
        (self.etc.sysusers / "argus-api.conf").write_text("u argus-api - - /older\n")
        code, _, err = self.run_apply(self.release, confirm=digest)
        self.assertEqual(3, code)
        self.assertIn("plan changed", err)

    def test_confirm_converges_with_backups_modes_and_one_reload(self) -> None:
        code, _, err = self.apply_confirmed(self.release)
        self.assertEqual(0, code, err)
        self.assertEqual(API_UNIT, self.etc_text("systemd/system/argus-control-api.service"))
        self.assertEqual("[Unit]\nOnFailure=x\n", self.etc_text("systemd/system/argus-smoke.service.d/onfailure.conf"))
        override = self.etc_text("systemd/system/argus-control-api.service.d/10-argus-release.conf")
        self.assertIn("ExecStart=/opt/argus/current/scripts/argus-control-api", override)
        self.assertNotIn("TEMPLATE", override)  # templates/systemd is never a source
        self.assertIn("/opt/argus/current/scripts/argus-m5-workload-x",
                      self.etc_text("systemd/system/argus-m5-workload-x.service.d/10-argus-release.conf"))
        self.assertEqual("[Service]\nNice=5\n", self.etc_text("systemd/system/argus-control-api.service.d/99-local.conf"))
        self.assertFalse((self.etc.systemd / "argus-new.service").exists())
        sudoers = self.etc.sudoers / "argus-operator"
        self.assertEqual(0o440, sudoers.stat().st_mode & 0o777)
        self.assertEqual(0o644, (self.etc.systemd / "argus-control-api.service").stat().st_mode & 0o777)
        self.assertEqual([], [p.name for p in self.etc.sudoers.iterdir() if p.name.startswith(".")])
        commands = self.runner.commands()
        self.assertEqual(["/usr/sbin/visudo", "-cf"], commands[0])  # checked before any change
        self.assertEqual(["installer"], commands[1])
        self.assertEqual(1, commands.count(["/usr/bin/systemctl", "daemon-reload"]))
        self.assertEqual(["/usr/bin/systemctl", "daemon-reload"], commands[-1])
        self.assertIn(["/usr/bin/systemd-sysusers"], commands)
        finished = self.history()[-1]
        backup = self.state / "runs" / finished["runId"] / "backup"
        self.assertEqual("[Service]\nExecStart=/srv/argus/old\n",
                         (backup / str(self.etc.systemd / "argus-control-api.service").lstrip("/")).read_text())
        changed = {Path(entry["path"]).name: entry["class"] for entry in finished["changedFiles"]}
        self.assertEqual("update", changed["argus-control-api.service"])
        self.assertEqual("create", changed["argus-operator"])
        # Converged: a re-apply changes nothing and reloads nothing.
        self.runner.calls.clear()
        code, out, _ = self.apply_confirmed(self.release, now=NOW + timedelta(seconds=1))
        self.assertEqual(0, code)
        self.assertIn("etc: 0 to change", out)
        self.assertEqual([], self.runner.calls)

    def test_symlinked_or_foreign_targets_are_refused_before_any_change(self) -> None:
        target = self.etc.systemd / "argus-control-api.service"
        target.unlink()
        target.symlink_to(self.tmp / "elsewhere")
        code, _, err = self.run_apply(self.release)
        self.assertEqual(3, code)
        self.assertIn("not a root-owned regular file", err)
        target.unlink()
        write(self.etc.systemd, "argus-control-api.service", "[Service]\n")
        (self.etc.systemd / "argus-control-api.service.d").chmod(0o777)
        code, _, err = self.run_apply(self.release)
        self.assertEqual(3, code)
        self.assertIn("group/other writable", err)

    def test_rejected_sudoers_refuses_before_any_change(self) -> None:
        self.runner.visudo_file_ok = False
        before = tree_digest(self.tmp / "etc", self.prefix)
        code, _, err = self.apply_confirmed(self.release)
        self.assertEqual(3, code)
        self.assertIn("visudo -cf rejects", err)
        self.assertEqual(before, tree_digest(self.tmp / "etc", self.prefix))
        self.assertEqual([], self.history())

    def test_live_visudo_failure_restores_and_exits_5(self) -> None:
        write(self.etc.sudoers, "argus-operator", "Defaults:oreo old\n", 0o440)
        self.runner.visudo_live_results = [False, True]
        code, _, err = self.apply_confirmed(self.release)
        self.assertEqual(5, code)
        self.assertIn("previous state restored", err)
        self.assertEqual("Defaults:oreo old\n", (self.etc.sudoers / "argus-operator").read_text())
        self.assertEqual(2, self.runner.commands().count(["/usr/sbin/visudo", "-c"]))
        self.assertEqual(("failed", 5), (self.history()[-1]["outcome"], self.history()[-1]["exit"]))

    def test_failed_sysusers_is_recorded_and_retried_by_the_next_apply(self) -> None:
        self.runner.sysusers_results = [False]
        code, _, err = self.apply_confirmed(self.release)
        self.assertEqual(5, code)
        self.assertIn("systemd-sysusers failed", err)
        failed = self.history()[-1]
        self.assertEqual("failed", failed["outcome"])
        # Files written before the failure are recorded, not reported as an empty change set.
        self.assertIn(str(self.etc.sysusers / "argus-api.conf"), [entry["path"] for entry in failed["changedFiles"]])
        self.runner.calls.clear()
        later = NOW + timedelta(seconds=1)
        code, out, _ = self.run_apply(self.release, now=later)
        self.assertEqual(0, code)
        self.assertIn("etc: 0 to change", out)
        self.assertIn("recovering from a failed or unfinished run", out)
        code, _, err = self.apply_confirmed(self.release, now=later)
        self.assertEqual(0, code, err)
        self.assertEqual([["/usr/bin/systemd-sysusers"], ["/usr/bin/systemctl", "daemon-reload"]], self.runner.commands())

    def test_a_release_whose_renderer_was_loaded_can_still_be_switched_back_to(self) -> None:
        """Loading a release's renderer must not leave __pycache__ in it, or verify_existing would refuse it forever."""
        self.assertEqual(0, self.apply_confirmed(self.release)[0])
        self.assertEqual(0, self.apply_confirmed(self.release, now=NOW + timedelta(seconds=1))[0])  # noop loads it in place
        newer = self.commit('{"v": 3}\n')
        self.assertEqual(0, self.apply_confirmed(newer, now=NOW + timedelta(seconds=2))[0])
        self.assertEqual([], list((self.prefix / "releases" / self.release).rglob("__pycache__")))
        code, _, err = self.apply_confirmed(self.release, now=NOW + timedelta(seconds=3))
        self.assertEqual(0, code, err)

    def test_managed_orphan_is_reported_and_left_alone(self) -> None:
        write(self.etc.systemd, "argus-gone.service.d/10-argus-release.conf", "# Managed by scripts/argus-sudoers-render\n[Service]\n")
        code, out, _ = self.run_apply(self.release)
        self.assertEqual(0, code)
        self.assertIn(f"managed-orphan           {self.etc.systemd}/argus-gone.service.d/10-argus-release.conf (report only)", out)
        self.assertEqual(0, self.apply_confirmed(self.release)[0])
        self.assertTrue((self.etc.systemd / "argus-gone.service.d" / "10-argus-release.conf").exists())


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
