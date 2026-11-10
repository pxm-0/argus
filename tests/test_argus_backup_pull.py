from __future__ import annotations

import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PULL = ROOT / "scripts" / "argus-backup-pull"


def stamp(hours_ago: float) -> str:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
    return when.strftime("%Y%m%dT%H%M%SZ")


def load_script(name: str):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(ROOT / "scripts" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def make_hastur(path: Path) -> None:
    with tarfile.open(path, "w:gz") as tar:
        data = b"hastur state"
        info = tarfile.TarInfo("srv/hastur/state.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def make_dump(path: Path) -> None:
    path.write_bytes(b"PGDMP" + b"\x01" * 64)


def make_archive(path: Path, tamper: bool = False, truncate: bool = False, rows: int = 1) -> None:
    """A real snapshot-shaped tar (manifest + sqlite db + file), 'encrypted' by the fake age stub (identity)."""
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "m1.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("create table t (v text)")
        connection.executemany("insert into t values (?)", [("x" * 100,)] * rows)
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


class PullFixture(unittest.TestCase):
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


class BackupPullTests(PullFixture):
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


class AuxCopyTests(PullFixture):
    """hastur `<name>-<stamp>.tar.gz.age` and kadath `<workload>-<stamp>.dump.age`, as PR3 publishes them."""

    def setUp(self) -> None:
        super().setUp()
        make_archive(self.source / f"{stamp(1)}-nightly.tar.age")

    def test_hastur_and_kadath_copies_are_pulled_verified_and_recorded(self) -> None:
        hastur, dump = f"hastur-data-{stamp(2)}.tar.gz.age", f"kadath-{stamp(3)}.dump.age"
        make_hastur(self.source / hastur)
        make_dump(self.source / dump)
        result = self.pull()
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertLessEqual({hastur, dump}, set(self.sums()))
        self.assertEqual(0o600, (self.dest / dump).stat().st_mode & 0o777)

    def test_corrupt_copies_are_quarantined(self) -> None:
        bad_dump, bad_tar = f"kadath-{stamp(3)}.dump.age", f"hastur-data-{stamp(2)}.tar.gz.age"
        (self.source / bad_dump).write_bytes(b"not a pg dump")
        (self.source / bad_tar).write_bytes(b"not a gzip tar")
        result = self.pull()
        self.assertEqual(1, result.returncode, result.stderr)
        for name in (bad_dump, bad_tar):
            self.assertTrue((self.dest / "quarantine" / name).is_file(), name)
            self.assertNotIn(name, self.sums())

    def test_retention_keeps_14_dumps_per_workload_and_one_hastur_copy_per_name(self) -> None:
        dumps = [f"kadath-{stamp(2 + 24 * i)}.dump.age" for i in range(16)]
        other = f"dupe-{stamp(5)}.dump.age"
        hasturs = [f"hastur-data-{stamp(40)}.tar.gz.age", f"hastur-data-{stamp(10)}.tar.gz.age"]
        for name in dumps + [other]:
            make_dump(self.source / name)
        for name in hasturs:
            make_hastur(self.source / name)
        self.assertEqual(0, self.pull(None, "--max-age-hours", "10000").returncode)
        kept = set(self.sums())
        self.assertEqual(set(dumps[:14]) | {other, hasturs[1]}, {n for n in kept if "nightly" not in n})
        self.assertFalse((self.dest / dumps[15]).exists())
        self.assertFalse((self.dest / hasturs[0]).exists())
        self.assertEqual(0, self.pull(None, "--max-age-hours", "10000").returncode)
        self.assertFalse((self.dest / hasturs[0]).exists(), "pruned copy must not be pulled again")

    def test_stale_kadath_dump_is_an_alarm_even_when_snapshots_are_fresh(self) -> None:
        make_dump(self.source / f"kadath-{stamp(60)}.dump.age")
        result = self.pull()
        self.assertEqual(3, result.returncode, result.stderr)
        self.assertIn("kadath", result.stderr)

    def test_hostile_server_names_are_ignored_not_executed(self) -> None:
        evil = '20260101T000000Z-x" & (do shell script "touch pwned") & ".tar.age'
        make_archive(self.source / evil)
        result = self.pull()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("pwned", (self.dest / "verify.log").read_text())
        self.assertNotIn(evil, self.sums())
        self.assertFalse((self.dest / "quarantine").exists())


class NotifyAndEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.calls = self.base / "calls.txt"
        for tool in ("osascript", "ssh"):
            (self.bin / tool).write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$@" >> {self.calls}\nexit ${{STUB_EXIT:-0}}\n')
            (self.bin / tool).chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}:{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        self.pull = load_script("argus-backup-pull")

    def test_notification_text_never_reaches_the_applescript_source(self) -> None:
        hostile = 'x" & (do shell script "touch pwned") & "'
        self.pull.notify(hostile, True)
        lines = self.calls.read_text().splitlines()
        self.assertEqual(hostile, lines[-1])
        self.assertNotIn("pwned", "".join(lines[:-1]))
        self.assertIn("item 1 of argv", "".join(lines))

    def test_server_evidence_touched_over_ssh_for_remote_sources_only(self) -> None:
        self.pull.touch_server_evidence("/local/dir/", ["ssh"])
        self.assertFalse(self.calls.exists())
        self.pull.touch_server_evidence("oreochiserver:/var/backups/argus-snapshots-pull/", ["ssh"])
        lines = self.calls.read_text().splitlines()
        self.assertIn("oreochiserver", lines)
        self.assertIn("touch ~/argus-pull-ok", lines)

    def test_evidence_touch_failure_is_reported_not_fatal(self) -> None:
        os.environ["STUB_EXIT"] = "1"
        self.addCleanup(os.environ.pop, "STUB_EXIT", None)
        self.pull.touch_server_evidence("oreochiserver:/x/", ["ssh"])  # must not raise

    def test_last_ok_and_evidence_skipped_when_a_local_pull_has_no_server(self) -> None:
        source, dest = self.base / "src", self.base / "dest"
        source.mkdir()
        make_archive(source / f"{stamp(1)}-nightly.tar.age")
        (self.bin / "age").write_text('#!/bin/sh\ncat "$4"\n')
        (self.bin / "age").chmod(0o755)
        identity = self.base / "k"
        identity.write_text("x\n")
        done = subprocess.run([sys.executable, str(PULL), "--source", f"{source}/", "--dest", str(dest),
                               "--identity", str(identity), "--no-notify"], text=True, capture_output=True, check=False)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertTrue((dest / ".last-ok").is_file())
        self.assertFalse(self.calls.exists(), "no ssh for a local source")


@unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "real age not installed")
class RealAgeTests(unittest.TestCase):
    """Real encryption: a wrong key and a truncated .age must behave as they will on the Mac."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.source, self.dest = base / "src", base / "dest"
        self.source.mkdir()
        self.identity, self.other = base / "id.key", base / "other.key"
        for key in (self.identity, self.other):
            subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
        self.recipient = subprocess.run(["age-keygen", "-y", str(self.identity)], check=True, capture_output=True,
                                        text=True).stdout.strip()

    def encrypt(self, plain: Path, name: str) -> Path:
        out = self.source / name
        subprocess.run(["age", "-r", self.recipient, "-o", str(out), str(plain)], check=True, capture_output=True)
        return out

    def pull(self, identity: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(PULL), "--source", f"{self.source}/", "--dest", str(self.dest),
                               "--identity", str(identity or self.identity), "--no-notify"],
                              text=True, capture_output=True, check=False)

    def seed_all(self) -> tuple[str, str, str]:
        names = (f"{stamp(1)}-nightly.tar.age", f"hastur-data-{stamp(2)}.tar.gz.age", f"kadath-{stamp(3)}.dump.age")
        plain = Path(self._tmp.name) / "plain"
        make_archive(plain)
        self.encrypt(plain, names[0])
        make_hastur(plain)
        self.encrypt(plain, names[1])
        make_dump(plain)
        self.encrypt(plain, names[2])
        return names

    def test_real_encrypted_copies_verify(self) -> None:
        names = self.seed_all()
        result = self.pull()
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual(set(names), set((self.dest / "SHA256SUMS").read_text().split()[1::2]))

    def test_truncated_real_age_is_quarantined(self) -> None:
        names = self.seed_all()
        self.assertEqual(0, self.pull().returncode)
        plain = Path(self._tmp.name) / "plain"
        make_dump(plain)
        cut = self.encrypt(plain, f"kadath-{stamp(0.5)}.dump.age")
        cut.write_bytes(cut.read_bytes()[:-10])
        result = self.pull()
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertTrue((self.dest / "quarantine" / cut.name).is_file())
        self.assertTrue(all((self.dest / n).is_file() for n in names), "verified copies untouched")

    def test_wrong_key_is_transient_and_quarantines_nothing(self) -> None:
        names = self.seed_all()
        self.assertEqual(0, self.pull().returncode)
        plain = Path(self._tmp.name) / "plain"
        make_dump(plain)
        fresh = self.encrypt(plain, f"kadath-{stamp(0.5)}.dump.age")
        result = self.pull(self.other)  # the identity the Mac holds no longer matches the recipient
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse((self.dest / "quarantine").exists())
        self.assertTrue((self.dest / fresh.name).is_file(), "kept for the next run")
        self.assertIn(f"RETRY {fresh.name}", (self.dest / "verify.log").read_text())
        self.assertNotIn(fresh.name, (self.dest / "SHA256SUMS").read_text())
        self.assertEqual(0, self.pull().returncode, "right key again: it verifies on the next run")
        self.assertIn(fresh.name, (self.dest / "SHA256SUMS").read_text())
        self.assertTrue(all(n in (self.dest / "SHA256SUMS").read_text() for n in names))

    def test_missing_age_on_path_fails_before_verifying_anything(self) -> None:
        self.seed_all()
        env = {**os.environ, "PATH": "/nonexistent"}
        result = subprocess.run([sys.executable, str(PULL), "--source", f"{self.source}/", "--dest", str(self.dest),
                                 "--identity", str(self.identity), "--no-notify"], env=env, text=True,
                                capture_output=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("age not found", result.stderr)
        self.assertFalse(self.dest.exists())

    @unittest.skipUnless("--no-compare" in subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "argus-backup-snapshot"), "--help"],
        capture_output=True, text=True, check=False).stdout, "verifier predates --no-compare (PR3)")
    def test_legitimate_shrink_against_the_previous_snapshot_is_not_quarantined(self) -> None:
        plain = Path(self._tmp.name) / "plain"
        make_archive(plain, rows=2000)
        self.encrypt(plain, f"{stamp(30)}-nightly.tar.age")
        make_archive(plain, rows=1)
        self.encrypt(plain, f"{stamp(1)}-nightly.tar.age")
        result = self.pull()
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertFalse((self.dest / "quarantine").exists())


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


class RestoreDrillUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.drill = load_script("argus-restore-drill")
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        (bin_dir / "age").write_text('#!/bin/sh\ncat "$4"\n')
        (bin_dir / "age").chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)

    def tar_with(self, name: str) -> Path:
        path = self.base / "evil.tar"
        with tarfile.open(path, "w") as tar:
            info = tarfile.TarInfo(name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        return path

    def test_extract_writes_regular_members_and_rejects_path_escapes(self) -> None:
        good, target = self.base / "good.tar", self.base / "out"
        make_archive(good)
        target.mkdir()
        self.drill.extract(good, self.base / "k", target)
        self.assertTrue((target / "db" / "m1-state.sqlite3").is_file())
        for name in ("../escape", "/abs/escape"):
            with self.assertRaises(self.drill.DrillError):
                self.drill.extract(self.tar_with(name), self.base / "k", self.base / "out2")
        self.assertFalse((self.base / "escape").exists())

    def test_extract_reports_a_failed_decrypt(self) -> None:
        (self.base / "bin" / "age").write_text("#!/bin/sh\nexit 1\n")
        with self.assertRaises(self.drill.DrillError):
            self.drill.extract(self.base / "nothing.tar", self.base / "k", self.base)

    def test_build_root_lays_out_runtime_and_falls_back_to_working_tree_config(self) -> None:
        extracted, root, repo = self.base / "x", self.base / "root", self.base / "repo"
        for directory in (extracted / "db", extracted / "m1", repo / "scripts", repo / "control-plane", repo / "config", root):
            directory.mkdir(parents=True)
        (extracted / "db" / "m1-state.sqlite3").write_bytes(b"m1")
        (extracted / "db" / "session.sqlite3").write_bytes(b"sess")
        (extracted / "m1" / "events.jsonl").write_text("{}\n")
        (repo / "config" / "workloads.json").write_text("{}")
        note = self.drill.build_root(extracted, root, repo)
        self.assertIn("working tree", note)
        self.assertEqual(b"m1", (root / "runtime" / "argus" / "m1" / "state.sqlite3").read_bytes())
        self.assertEqual(b"sess", (root / "runtime" / "m5" / "sessions.sqlite3").read_bytes())
        self.assertTrue((root / "runtime" / "argus" / "m1" / "events.jsonl").is_file())
        self.assertTrue((root / "scripts").is_symlink())
        self.assertTrue((root / "config" / "workloads.json").is_file())

    def test_newest_verified_ignores_hastur_and_kadath_copies(self) -> None:
        directory = self.base / "arch"
        directory.mkdir()
        names = [f"{stamp(5)}-nightly.tar.age", f"kadath-{stamp(1)}.dump.age", f"hastur-data-{stamp(2)}.tar.gz.age"]
        for name in names:
            (directory / name).write_bytes(b"x")
        (directory / "SHA256SUMS").write_text("".join(f"{'0' * 64}  {n}\n" for n in names))
        self.assertEqual(names[0], self.drill.newest_verified(directory).name)


if __name__ == "__main__":
    unittest.main()
