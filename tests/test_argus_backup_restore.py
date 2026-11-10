from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class BackupRestoreTests(unittest.TestCase):
    def artifact(self, root: Path, workload: str = "demo", artifact_id: str = "run-1") -> Path:
        artifact = root / workload / artifact_id
        artifact.mkdir(parents=True)
        with tarfile.open(artifact / "files.tar.gz", "w:gz") as bundle:
            content = b"restored\n"
            member = tarfile.TarInfo("data/value.txt")
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
        (artifact / "backup-summary.json").write_text(json.dumps({"workloadId": workload}))
        rows = []
        for name in ("files.tar.gz", "backup-summary.json"):
            rows.append(f"{hashlib.sha256((artifact / name).read_bytes()).hexdigest()}  {name}")
        (artifact / "checksums.sha256").write_text("\n".join(rows) + "\n")
        return artifact

    def test_restore_is_checksum_verified_isolated_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact = self.artifact(base / "backups")
            state = base / "state"
            script = (ROOT / "scripts" / "argus-backup-restore").read_text()
            relocated = base / "restore"
            relocated.write_text(script.replace("/srv/argus/runtime/backups", str(base / "backups")))
            relocated.chmod(0o755)
            env = {**os.environ, "ARGUS_RESTORE_STATE": str(state)}
            command = [str(relocated), "--workload", "demo", "--artifact-id", artifact.name, "--acknowledge-isolated-restore"]
            first = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
            second = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            payload = json.loads(first.stdout)
            self.assertTrue(payload["verified"])
            self.assertFalse(payload["liveStateChanged"])
            self.assertEqual("restored\n", (state / "run-1" / "candidate" / "data" / "value.txt").read_text())

    def test_checksum_mismatch_fails_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact = self.artifact(base / "backups")
            (artifact / "files.tar.gz").write_bytes(b"tampered")
            script = (ROOT / "scripts" / "argus-backup-restore").read_text()
            relocated = base / "restore"
            relocated.write_text(script.replace("/srv/argus/runtime/backups", str(base / "backups")))
            relocated.chmod(0o755)
            state = base / "state"
            result = subprocess.run(
                [str(relocated), "--workload", "demo", "--artifact-id", "run-1", "--acknowledge-isolated-restore"],
                env={**os.environ, "ARGUS_RESTORE_STATE": str(state)}, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((state / "run-1" / "candidate").exists())


def load(name: str):
    path = ROOT / "scripts" / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class EncryptedDumpFlowTests(unittest.TestCase):
    """Dumps are verified in the root-only tree, then encrypted, then atomically published to the pull dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        bindir = self.base / "bin"
        bindir.mkdir()
        # fake age: -R recipients -o OUT IN  ->  OUT = "AGE:" + IN
        (bindir / "age").write_text('#!/bin/sh\n{ printf AGE:; cat "$5"; } > "$4"\n')
        (bindir / "age").chmod(0o755)
        self.recipients = self.base / "recipients.txt"
        self.recipients.write_text("age1" + "q" * 58 + "\n")
        self.pull = self.base / "pull"
        patches = [mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}),
                   mock.patch("os.chown"), mock.patch("os.geteuid", return_value=0),
                   mock.patch("pwd.getpwnam", return_value=mock.Mock(pw_uid=1000, pw_gid=1000))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_hastur_publishes_one_encrypted_copy_per_archive(self) -> None:
        module = load("argus-m5-hastur-backup")
        data, auth = self.base / "data", self.base / "auth"
        for source, name in ((data, "posts.json"), (auth, "threads.json")):
            source.mkdir()
            (source / name).write_text("{}")
        with mock.patch.object(module, "PULL_DIR", self.pull), mock.patch.object(module, "BACKUP_ROOT", self.base / "b"), \
                mock.patch.object(module, "SPECS", {"hastur": {"data": data, "auth": auth}}), \
                mock.patch.object(module, "ensure_root_directory", lambda p: p.mkdir(parents=True, exist_ok=True)):
            first = module.backup("hastur", self.recipients)
            time.sleep(1.1)
            second = module.backup("hastur", self.recipients)
        names = sorted(p.name for p in self.pull.iterdir())
        self.assertEqual(len(names), 2, names)  # exactly one copy each of data and auth
        for item in second["artifacts"]:
            copy = Path(item["encryptedCopy"]["path"])
            self.assertTrue(copy.read_bytes().startswith(b"AGE:"))
            self.assertEqual(copy.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.pull.stat().st_mode & 0o777, 0o750)
        self.assertNotEqual(first["artifacts"][0]["artifactPath"], second["artifacts"][0]["artifactPath"])

    def test_hastur_without_recipient_file_publishes_nothing(self) -> None:
        module = load("argus-m5-hastur-backup")
        data = self.base / "data"
        data.mkdir()
        (data / "x").write_text("x")
        with mock.patch.object(module, "PULL_DIR", self.pull), mock.patch.object(module, "BACKUP_ROOT", self.base / "b"), \
                mock.patch.object(module, "SPECS", {"hastur": {"data": data}}), \
                mock.patch.object(module, "ensure_root_directory", lambda p: p.mkdir(parents=True, exist_ok=True)):
            module.backup("hastur")
        self.assertFalse(self.pull.exists())

    def test_failed_encryption_leaves_no_partial_and_raises(self) -> None:
        module = load("argus-m5-workload-db-backup")
        (self.base / "bin" / "age").write_text("#!/bin/sh\nexit 1\n")
        artifact = self.base / "kadath-20260101T000000Z.dump"
        artifact.write_bytes(b"dump")
        with self.assertRaises(module.BackupError):
            module.publish_encrypted(artifact, self.recipients, self.pull, "kadath", 14)
        self.assertEqual(list(self.pull.iterdir()), [])

    def test_private_key_recipient_file_is_refused(self) -> None:
        module = load("argus-m5-workload-db-backup")
        self.recipients.write_text("AGE-SECRET-KEY-1ABC\n")
        artifact = self.base / "kadath-1.dump"
        artifact.write_bytes(b"dump")
        with self.assertRaises(module.BackupError):
            module.publish_encrypted(artifact, self.recipients, self.pull, "kadath", 14)

    def test_kadath_copies_are_pruned_to_retention_and_ignore_other_files(self) -> None:
        module = load("argus-m5-workload-db-backup")
        self.pull.mkdir()
        (self.pull / "20260101T000000Z-nightly.tar.age").write_bytes(b"snapshot")
        for day in range(1, 5):
            (self.pull / f"kadath-2026010{day}T000000Z.dump.age").write_bytes(b"old")
        artifact = self.base / "kadath-20260110T000000Z.dump"
        artifact.write_bytes(b"dump")
        result = module.publish_encrypted(artifact, self.recipients, self.pull, "kadath", 2)
        kadath = sorted(p.name for p in self.pull.glob("kadath-*.age"))
        self.assertEqual(kadath, ["kadath-20260104T000000Z.dump.age", "kadath-20260110T000000Z.dump.age"])
        self.assertEqual(len(result["pruned"]), 3)
        self.assertTrue((self.pull / "20260101T000000Z-nightly.tar.age").exists())

    def test_dump_unit_requests_the_encrypted_copy(self) -> None:
        service = (ROOT / "templates" / "systemd" / "argus-workload-db-backup@.service").read_text()
        self.assertIn("--age-recipient-file /etc/argus/snapshot-recipients.txt", service)


class SnapshotUnitTests(unittest.TestCase):
    def test_timer_runs_before_workload_dumps_and_catches_up(self) -> None:
        timer = (ROOT / "systemd" / "argus-backup-snapshot.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 02:10:00 UTC", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("RandomizedDelaySec=5m", timer)
        service = (ROOT / "systemd" / "argus-backup-snapshot.service").read_text()
        self.assertIn("OnFailure=argus-backup-snapshot-failure.service", service)
        self.assertIn("--pull-dir /var/backups/argus-snapshots-pull", service)
        self.assertTrue((ROOT / "systemd" / "argus-backup-snapshot-failure.service").is_file())


if __name__ == "__main__":
    unittest.main()
