from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("argus_release_install", str(ROOT / "scripts" / "argus-release-install"))
installer = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(installer)

OWNER = (os.getuid(), os.getgid())
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                            capture_output=True, text=True, check=True, env=ENV)
    return result.stdout.strip()


def write(repo: Path, relative: str, text: str, mode: int = 0o644) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


class ReleaseFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name).resolve()
        self.source, self.prefix = tmp / "srv-argus", tmp / "opt-argus"
        self.source.mkdir()
        git(self.source, "init", "-q", "-b", "main")
        write(self.source, "scripts/argus", "#!/usr/bin/env python3\n", 0o755)
        write(self.source, "scripts/helper.py", "x = 1\n", 0o644)
        write(self.source, "config/a.json", "{}\n")
        write(self.source, "runtime/.gitkeep", "")
        write(self.source, "control-plane/dashboard/public/.gitkeep", "")
        os.symlink("a.json", self.source / "config" / "link.json")
        (self.source / "empty-dir").mkdir()
        git(self.source, "add", "-A")
        git(self.source, "commit", "-q", "-m", "one")
        self.sha = git(self.source, "rev-parse", "HEAD")
        git(self.source, "update-ref", "refs/remotes/origin/main", self.sha)

    def install(self, sha: str | None = None) -> Path:
        with patch.dict(os.environ, ENV):
            return installer.install_release(sha or self.sha, source=self.source, prefix=self.prefix, owner=OWNER)

    def second_commit(self) -> str:
        write(self.source, "config/a.json", '{"v": 2}\n')
        git(self.source, "commit", "-q", "-am", "two")
        sha = git(self.source, "rev-parse", "HEAD")
        git(self.source, "update-ref", "refs/remotes/origin/main", sha)
        return sha


class InstallTests(ReleaseFixture):
    def test_installs_verified_tree_with_expected_modes_and_state_links(self) -> None:
        release = self.install()
        self.assertEqual(self.prefix / "releases" / self.sha, release)
        self.assertEqual(release, (self.prefix / "current").resolve())
        self.assertTrue((self.prefix / "current").is_symlink())
        self.assertEqual(self.sha + "\n", (release / "ARGUS_RELEASE").read_text())
        self.assertEqual(stat.S_IMODE((release / "scripts/argus").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((release / "scripts/helper.py").stat().st_mode), 0o644)
        self.assertEqual("a.json", os.readlink(release / "config" / "link.json"))
        self.assertEqual(self.source / "runtime", Path(os.readlink(release / "runtime")))
        self.assertEqual(self.source / "control-plane/dashboard/public", Path(os.readlink(release / "control-plane/dashboard/public")))
        self.assertFalse((release / "empty-dir").exists())

    def test_no_group_or_other_write_anywhere_and_staging_is_gone(self) -> None:
        release = self.install()
        for current, dirs, files in os.walk(release):
            for name in [*dirs, *files]:
                path = Path(current, name)
                if not path.is_symlink():
                    self.assertEqual(0, path.stat().st_mode & 0o022, path)
        self.assertEqual(0, release.stat().st_mode & 0o022)
        self.assertEqual([self.sha], sorted(p.name for p in (self.prefix / "releases").iterdir()))

    def test_second_release_flips_current_and_keeps_the_first_untouched(self) -> None:
        first = self.install()
        before = (first / "config/a.json").read_text()
        second = self.install(self.second_commit())
        self.assertEqual(second, (self.prefix / "current").resolve())
        self.assertEqual(before, (first / "config/a.json").read_text())
        self.assertEqual('{"v": 2}\n', (second / "config/a.json").read_text())

    def test_tree_hash_matches_git_for_the_extracted_tree(self) -> None:
        release = self.install()
        stage = Path(self._tmp.name, "plain")
        stage.mkdir()
        subprocess.run(f"git -C {self.source} archive {self.sha} | tar -x -C {stage}", shell=True, check=True, env=ENV)
        self.assertEqual(git(self.source, "rev-parse", f"{self.sha}^{{tree}}"), installer.git_tree_hash(stage))
        self.assertTrue(release.is_dir())


class SwitchAtomicityTests(unittest.TestCase):
    # APFS can briefly report EINVAL from readlink while a symlink is renamed over; the server is Linux.
    @unittest.skipUnless(sys.platform.startswith("linux"), "symlink rename atomicity is asserted on Linux only")
    def test_current_is_never_missing_while_switching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a, b, current = base / "a", base / "b", base / "current"
            a.mkdir()
            b.mkdir()
            installer.switch_current(current, a)
            stop = threading.Event()
            seen: set[str] = set()
            errors: list[BaseException] = []

            def reader() -> None:
                while not stop.is_set():
                    try:
                        seen.add(os.readlink(current))
                    except BaseException as exc:  # noqa: BLE001 - any failure is the bug under test
                        errors.append(exc)
                        return

            thread = threading.Thread(target=reader)
            thread.start()
            for index in range(400):
                installer.switch_current(current, (a, b)[index % 2])
            stop.set()
            thread.join()
            self.assertEqual([], errors)
            self.assertLessEqual(seen, {str(a), str(b)})
            self.assertEqual([], [p.name for p in base.iterdir() if p.name.startswith(".current")])


class RefusalTests(ReleaseFixture):
    def assert_refused(self, sha: str, pattern: str) -> None:
        before = os.path.realpath(self.prefix / "current") if (self.prefix / "current").exists() else None
        with self.assertRaisesRegex(installer.ReleaseRefused, pattern):
            self.install(sha)
        after = os.path.realpath(self.prefix / "current") if (self.prefix / "current").exists() else None
        self.assertEqual(before, after)
        releases = self.prefix / "releases"
        self.assertEqual([], [p.name for p in releases.iterdir() if p.name != self.sha] if releases.exists() else [])

    def test_refuses_malformed_sha(self) -> None:
        for bad in ("abc", self.sha.upper(), self.sha[:39], self.sha + "0", "../" + self.sha, ""):
            with self.assertRaisesRegex(installer.ReleaseRefused, "40 lowercase hex"):
                installer.require_clean_commit(self.source, bad, "origin/main")
        self.assertFalse((self.prefix / "current").exists())

    def test_refuses_unknown_sha(self) -> None:
        self.assert_refused("0" * 40, "unknown commit")

    def test_refuses_dirty_checkout_tracked_and_untracked(self) -> None:
        write(self.source, "config/a.json", "dirty\n")
        self.assert_refused(self.sha, "uncommitted")
        git(self.source, "checkout", "--", "config/a.json")
        write(self.source, "stray.txt", "x\n")
        self.assert_refused(self.sha, "uncommitted")

    def test_refuses_commit_not_reachable_from_origin_main(self) -> None:
        git(self.source, "checkout", "-q", "-b", "side")
        write(self.source, "config/a.json", '{"side": true}\n')
        git(self.source, "commit", "-q", "-am", "side")
        side = git(self.source, "rev-parse", "HEAD")
        self.assert_refused(side, "not reachable from origin/main")

    def test_refuses_existing_release_and_leaves_it_alone(self) -> None:
        release = self.install()
        marker = (release / "ARGUS_RELEASE").read_text()
        with self.assertRaisesRegex(installer.ReleaseRefused, "already exists"):
            self.install()
        self.assertEqual(marker, (release / "ARGUS_RELEASE").read_text())

    def test_tree_hash_mismatch_aborts_cleanly_and_keeps_previous_current(self) -> None:
        first = self.install()
        sha = self.second_commit()
        real = installer.extract_archive

        def tampered(source: Path, commit: str, destination: Path) -> None:
            real(source, commit, destination)
            (destination / "scripts" / "injected.py").write_text("evil = True\n")

        with patch.object(installer, "extract_archive", tampered), self.assertRaisesRegex(installer.ReleaseRefused, "tree hash mismatch"):
            self.install(sha)
        self.assertEqual(first, (self.prefix / "current").resolve())
        self.assertEqual([self.sha], sorted(p.name for p in (self.prefix / "releases").iterdir()))


class CliTests(unittest.TestCase):
    def test_requires_root_and_only_accepts_sha(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in ([], ["--sha", "a" * 40, "--prefix", "/etc"], ["--sh", "a" * 40], ["a" * 40]):
                with self.assertRaises(SystemExit) as raised:
                    installer.main(argv)
                self.assertEqual(2, raised.exception.code)
            with patch.object(os, "geteuid", return_value=1000):
                self.assertEqual(3, installer.main(["--sha", "a" * 40]))

    def test_root_run_reports_refusal_as_exit_3(self) -> None:
        with patch.object(os, "geteuid", return_value=0), patch.object(installer, "install_release", side_effect=installer.ReleaseRefused("nope")), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(3, installer.main(["--sha", "a" * 40]))
        self.assertIn("refused: nope", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
