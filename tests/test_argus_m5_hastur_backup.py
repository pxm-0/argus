import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-m5-hastur-backup"
loader = importlib.machinery.SourceFileLoader("argus_m5_hastur_backup", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class HasturBackupTest(unittest.TestCase):
    def test_publish_never_follows_a_planted_partial_symlink(self) -> None:
        import os
        import tempfile
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pull, victim = root / "pull", root / "victim"
            pull.mkdir()
            victim.write_text("keep")
            artifact = root / "data-20260101T000000Z.tar.gz"
            artifact.write_bytes(b"plain")
            recipients = root / "r.txt"
            recipients.write_text("age1" + "q" * 58 + "\n")
            (pull / f".{artifact.name}.age.partial").symlink_to(victim)

            def fake_age(argv, **_kw):
                Path(argv[argv.index("-o") + 1]).write_bytes(b"cipher")
                return mock.Mock(returncode=0)

            me = os.getenv("USER") or "root"
            with mock.patch.object(module, "PULL_OWNER", me), \
                 mock.patch.object(module.subprocess, "run", fake_age), \
                 mock.patch.object(module.os, "chown"), mock.patch.object(module.os, "fchown"):
                module.publish_encrypted(artifact, recipients, pull, "data", 14)
            self.assertEqual(victim.read_text(), "keep")
            final = pull / f"{artifact.name}.age"
            self.assertFalse(final.is_symlink())
            self.assertEqual(final.read_bytes(), b"cipher")

    def test_hastur_backs_up_live_volume_data_and_sealed_auth(self) -> None:
        # D030 phase 5: the data lives in the prod cell's volume, not the legacy home directory.
        self.assertEqual(
            {
                "data": {"domain": "personal-managed", "project": "hastur", "service": "hastur", "path": "/app/data"},
                "auth": Path("/etc/argus/workload-credentials/hastur"),
            },
            module.SPECS["hastur"],
        )

    def test_container_archive_streams_from_the_one_running_container(self) -> None:
        import io
        import tarfile as tarlib
        import unittest.mock as mock
        payload = io.BytesIO()
        with tarlib.open(fileobj=payload, mode="w:gz") as tar:
            info = tarlib.TarInfo("./index.sqlite")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"db"))
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            if "ps" in argv:
                return mock.Mock(returncode=0, stdout="a1b2c3d4e5f6\n")
            kwargs["stdout"].write(payload.getvalue())
            return mock.Mock(returncode=0, stderr=b"")

        source = module.SPECS["hastur"]["data"]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(module.subprocess, "run", fake_run):
            result = module.archive_container(source, Path(directory), "data", "20261125T000000Z")
            self.assertTrue(Path(result["artifactPath"]).exists())
        self.assertIn("unix:///var/lib/argus/personal-managed/docker.sock", calls[1])
        self.assertEqual(["exec", "a1b2c3d4e5f6", "tar", "-C", "/app/data", "-czf", "-", "."], calls[1][-8:])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module.subprocess, "run", lambda argv, **kw: mock.Mock(returncode=0, stdout="")):
            with self.assertRaises(module.BackupError):
                module.archive_container(source, Path(directory), "data", "20261125T000000Z")
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_pruning_keeps_the_newest_copies_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [f"data-2026073{index}T023500Z.tar.gz" for index in range(5)]
            for name in names:
                (root / name).write_text("x")
            (root / "notes.txt").write_text("keep me")
            removed = module.prune(root, 2)
            self.assertEqual(sorted(names[:3]), sorted(removed))
            self.assertTrue((root / names[4]).exists())
            self.assertTrue((root / "notes.txt").exists())

    def test_archive_is_verified_before_it_counts(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("getmembers", script)
        self.assertIn("partial", script)

    def test_missing_source_path_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(module.BackupError):
                module.archive_one(Path(directory) / "missing", Path(directory), "data", "stamp")

    def test_backup_writes_both_archives_and_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_source = root / "source-data"
            auth_source = root / "source-auth"
            data_source.mkdir()
            auth_source.mkdir()
            (data_source / "posts.json").write_text("[]")
            (auth_source / "threads-storage.json").write_text("{}")

            originals = (
                module.BACKUP_ROOT,
                module.os.geteuid,
                module.SPECS,
                module.ensure_root_directory,
            )
            module.BACKUP_ROOT = root / "backups"
            module.os.geteuid = lambda: 0
            module.SPECS = {"hastur": {"data": data_source, "auth": auth_source}}
            module.ensure_root_directory = lambda path: path.mkdir(parents=True, exist_ok=True)
            try:
                result = module.backup("hastur")
            finally:
                (
                    module.BACKUP_ROOT,
                    module.os.geteuid,
                    module.SPECS,
                    module.ensure_root_directory,
                ) = originals

            self.assertTrue(result["verified"])
            self.assertEqual({"data", "auth"}, {a["name"] for a in result["artifacts"]})
            for artifact in result["artifacts"]:
                self.assertTrue(Path(artifact["artifactPath"]).exists())

    def test_units_are_root_owned_and_paired(self) -> None:
        service = (ROOT / "templates" / "systemd" / "argus-hastur-backup.service").read_text()
        timer = (ROOT / "templates" / "systemd" / "argus-hastur-backup.timer").read_text()
        self.assertIn("User=root", service)
        self.assertIn("--workload hastur", service)
        self.assertIn("ExecStart=/opt/argus/current/scripts/argus-m5-hastur-backup", service)
        self.assertIn("--age-recipient-file /etc/argus/snapshot-recipients.txt", service)
        self.assertIn("OnFailure=argus-alert-unit@%n.service", service)
        self.assertNotIn("/srv/argus", service)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=argus-hastur-backup.service", timer)


if __name__ == "__main__":
    unittest.main()
