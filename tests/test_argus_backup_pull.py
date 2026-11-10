from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PULL = ROOT / "scripts" / "argus-backup-pull"


def stamp(hours_ago: float) -> str:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
    return when.strftime("%Y%m%dT%H%M%SZ")


def make_archive(path: Path, tamper: bool = False, truncate: bool = False) -> None:
    """A real snapshot-shaped tar (manifest + sqlite db + file), 'encrypted' by the fake age stub (identity)."""
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "m1.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("create table t (v text)")
        connection.execute("insert into t values ('x')")
        connection.commit()
        connection.close()
        members = {"db/m1-state.sqlite3": database.read_bytes(), "state/git-head.txt": b"deadbeef\n"}
        manifest = {"version": 1, "createdAt": "2026-01-01T00:00:00Z", "reason": "nightly", "commands": {},
                    "members": {n: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in members.items()}}
        if tamper:
            members["state/git-head.txt"] = b"evilbeef\n"
        with tarfile.open(path, "w") as tar:
            for name, data in [("manifest.json", json.dumps(manifest).encode()), *members.items()]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    if truncate:
        path.write_bytes(path.read_bytes()[: path.stat().st_size // 2])


class BackupPullTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.source, self.dest, self.bin = base / "server-pull-dir", base / "mac" / "argus-snapshots", base / "bin"
        self.source.mkdir()
        self.bin.mkdir()
        (self.bin / "age").write_text('#!/bin/sh\n[ "$1" = "-d" ] || exit 2\ncat "$4"\n')
        (self.bin / "age").chmod(0o755)
        self.identity = base / "age.key"
        self.identity.write_text("AGE-SECRET-KEY-fake\n")
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}

    def pull(self, source: str | None = None, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PULL), "--source", source or f"{self.source}/", "--dest", str(self.dest),
             "--identity", str(self.identity), "--no-notify", *extra],
            env=self.env, text=True, capture_output=True, check=False)

    def sums(self) -> dict[str, str]:
        text = (self.dest / "SHA256SUMS").read_text()
        return {line.split("  ")[1]: line.split("  ")[0] for line in text.splitlines()}

    def test_new_archive_is_verified_recorded_and_marked_ok(self) -> None:
        name = f"{stamp(1)}-nightly.tar.age"
        make_archive(self.source / name)
        result = self.pull()
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual(hashlib.sha256((self.dest / name).read_bytes()).hexdigest(), self.sums()[name])
        self.assertIn(f"OK {name}", (self.dest / "verify.log").read_text())
        self.assertTrue((self.dest / ".last-ok").is_file())
        self.assertEqual(0o700, self.dest.stat().st_mode & 0o777)
        self.assertEqual(0o600, (self.dest / name).stat().st_mode & 0o777)

    def test_ignore_existing_never_overwrites_a_local_copy(self) -> None:
        name = f"{stamp(1)}-nightly.tar.age"
        make_archive(self.source / name)
        self.assertEqual(0, self.pull().returncode)
        local = (self.dest / name).read_bytes()
        (self.source / name).write_bytes(b"server changed the bytes")
        again = self.pull()
        self.assertEqual(0, again.returncode, again.stderr)
        self.assertEqual(local, (self.dest / name).read_bytes())
        self.assertFalse((self.dest / "quarantine").exists())

    def test_tampered_and_truncated_archives_are_quarantined_not_deleted(self) -> None:
        good = f"{stamp(1)}-nightly.tar.age"
        make_archive(self.source / good)
        bad = {f"{stamp(3)}-nightly.tar.age": {"tamper": True}, f"{stamp(4)}-pre-deploy.tar.age": {"truncate": True}}
        for name, kwargs in bad.items():
            make_archive(self.source / name, **kwargs)
        result = self.pull()
        self.assertEqual(1, result.returncode, result.stderr)
        for name in bad:
            self.assertFalse((self.dest / name).exists())
            self.assertTrue((self.dest / "quarantine" / name).is_file(), name)
            self.assertNotIn(name, self.sums())
            self.assertIn(f"QUARANTINED {name}", (self.dest / "verify.log").read_text())
        self.assertIn(good, self.sums())
        self.assertFalse((self.dest / ".last-ok").exists())
        # a quarantined file is not fetched again on the next trigger
        (self.dest / "quarantine" / next(iter(bad))).stat()
        second = self.pull()
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertFalse(any((self.dest / name).exists() for name in bad))

    def test_staleness_exit_code(self) -> None:
        make_archive(self.source / f"{stamp(40)}-nightly.tar.age")
        stale = self.pull()
        self.assertEqual(3, stale.returncode, stale.stderr)
        self.assertIn("stale", stale.stderr)
        fresh = self.pull(None, "--max-age-hours", "48")
        self.assertEqual(0, fresh.returncode, fresh.stderr)

    def test_no_verified_archive_is_stale(self) -> None:
        self.assertEqual(3, self.pull().returncode)

    def test_unreachable_server_is_a_retry_not_a_failure(self) -> None:
        make_archive(self.source / f"{stamp(1)}-nightly.tar.age")
        self.assertEqual(0, self.pull().returncode)
        before = (self.dest / ".last-ok").read_text()
        result = self.pull("nobody@argus-unreachable.invalid:/var/backups/x/")
        self.assertEqual(75, result.returncode, result.stderr)
        self.assertIn("UNREACHABLE", (self.dest / "verify.log").read_text())
        self.assertEqual(before, (self.dest / ".last-ok").read_text())

    def test_retention_prunes_only_verified_nightlies_and_keeps_reason_named(self) -> None:
        self.dest.mkdir(parents=True, mode=0o700)
        names = [f"{stamp(100 - i)}-nightly.tar.age" for i in range(32)] + [f"{stamp(120)}-pre-deploy.tar.age"]
        for name in names:
            (self.dest / name).write_bytes(name.encode())
        unverified = f"{stamp(0.5)}-nightly.tar.age"
        (self.dest / unverified).write_bytes(b"not yet verified")
        (self.dest / "SHA256SUMS").write_text("".join(f"{'0' * 64}  {n}\n" for n in names))
        make_archive(self.source / names[0])  # server still holds the oldest nightly
        result = self.pull(None, "--max-age-hours", "10000")
        self.assertEqual(1, result.returncode)  # the unverified fake is quarantined, nothing else
        self.assertFalse((self.dest / names[0]).exists())
        self.assertFalse((self.dest / names[1]).exists())
        self.assertTrue((self.dest / names[2]).exists())
        self.assertTrue((self.dest / names[-1]).exists(), "reason-named archive must be kept")
        self.assertTrue((self.dest / "quarantine" / unverified).exists(), "unverified data is moved, not deleted")
        self.assertEqual({names[0], names[1]}, set((self.dest / "pruned.txt").read_text().split()))
        again = self.pull(None, "--max-age-hours", "10000")
        self.assertEqual(0, again.returncode, again.stderr)
        self.assertFalse((self.dest / names[0]).exists(), "pruned archive must not be pulled again")

    def test_missing_identity_fails_before_touching_anything(self) -> None:
        self.identity.unlink()
        result = self.pull()
        self.assertEqual(1, result.returncode)
        self.assertFalse(self.dest.exists())


class LaunchdPlistTests(unittest.TestCase):
    def load(self, name: str) -> dict:
        with (ROOT / "ops" / "launchd" / f"{name}.plist").open("rb") as handle:
            return plistlib.load(handle)

    def test_backup_pull_has_calendar_triggers_and_wake_catchup(self) -> None:
        plist = self.load("dev.argus.backup-pull")
        self.assertEqual({(3, 30), (13, 30)}, {(d["Hour"], d["Minute"]) for d in plist["StartCalendarInterval"]})
        self.assertEqual(21600, plist["StartInterval"])
        self.assertTrue(plist["StandardOutPath"].endswith("/Library/Logs/argus-backup-pull.log"))
        self.assertTrue(plist["ProgramArguments"][1].endswith("/scripts/argus-backup-pull"))

    def test_restore_drill_is_monthly(self) -> None:
        plist = self.load("dev.argus.restore-drill")
        self.assertEqual(1, plist["StartCalendarInterval"]["Day"])
        self.assertTrue(plist["ProgramArguments"][1].endswith("/scripts/argus-restore-drill"))


STUB_SERVER = """
import http.server, os, socketserver
class S(http.server.HTTPServer):
    def server_bind(self):  # HTTPServer.server_bind does a slow getfqdn() on CI macOS, as the real API avoids
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(401); self.end_headers()
    def log_message(self, *a): pass
S(("127.0.0.1", int(os.environ["ARGUS_API_PORT"])), H).serve_forever()
"""


class RestoreDrillTests(unittest.TestCase):
    """Orchestration against a stub repo (real m1/audit tools need real M1 state; the drill is also run by hand)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.archives, self.repo, bin_dir = base / "argus-snapshots", base / "repo", base / "bin"
        for directory in (self.archives, bin_dir, self.repo / "scripts", self.repo / "config", self.repo / "control-plane" / "api"):
            directory.mkdir(parents=True)
        (bin_dir / "age").write_text('#!/bin/sh\n[ "$1" = "-d" ] || exit 2\ncat "$4"\n')
        (bin_dir / "age").chmod(0o755)
        (self.repo / "scripts" / "argus-m1-verify").write_text("import sys; sys.exit(0)\n")
        self.checkpoint_script = self.repo / "scripts" / "argus-m1-audit-checkpoint"
        self.checkpoint_script.write_text("import sys; sys.exit(0)\n")
        (self.repo / "control-plane" / "api" / "server.py").write_text(STUB_SERVER)
        (self.repo / "config" / "workloads.json").write_text("{}")
        self.identity = base / "age.key"
        self.identity.write_text("AGE-SECRET-KEY-fake\n")
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def seed(self, archive_name: str, **kwargs) -> None:
        make_archive(self.archives / archive_name, **kwargs)
        digest = hashlib.sha256((self.archives / archive_name).read_bytes()).hexdigest()
        (self.archives / "SHA256SUMS").write_text(f"{digest}  {archive_name}\n")

    def drill(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "argus-restore-drill"), "--archive-dir", str(self.archives),
             "--identity", str(self.identity), "--repo", str(self.repo), "--no-notify"],
            env=self.env, text=True, capture_output=True, check=False)

    def assert_clean(self) -> None:
        self.assertEqual([], [p.name for p in self.archives.glob(".argus-drill-*")], "temp dir must always be deleted")

    def test_success_runs_every_step_logs_and_cleans_up(self) -> None:
        self.seed(f"{stamp(1)}-nightly.tar.age")
        result = self.drill()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        log = (self.archives / "drill.log").read_text()
        for step in ("decrypted", "argus-m1-verify ok", "audit-checkpoint --verify ok", "integrity_check ok",
                     "control API answered 401"):
            self.assertIn(step, log)
        self.assertIn("DRILL_OK", log)
        self.assert_clean()

    def test_failing_verifier_fails_the_drill_and_still_cleans_up(self) -> None:
        self.seed(f"{stamp(1)}-nightly.tar.age")
        self.checkpoint_script.write_text("import sys; print('checkpoint verification failed', file=sys.stderr); sys.exit(1)\n")
        result = self.drill()
        self.assertEqual(1, result.returncode)
        self.assertIn("DRILL_FAIL audit-checkpoint --verify failed", (self.archives / "drill.log").read_text())
        self.assert_clean()

    def test_truncated_archive_fails(self) -> None:
        self.seed(f"{stamp(1)}-nightly.tar.age", truncate=True)
        self.assertEqual(1, self.drill().returncode)
        self.assert_clean()

    def test_without_a_verified_archive_the_drill_fails(self) -> None:
        result = self.drill()
        self.assertEqual(1, result.returncode)
        self.assertIn("no verified archive", (self.archives / "drill.log").read_text())


if __name__ == "__main__":
    unittest.main()
