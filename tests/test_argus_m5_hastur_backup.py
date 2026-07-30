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
    def test_hastur_backs_up_both_data_and_auth(self) -> None:
        self.assertEqual(
            {"data": Path("/home/oreo/hastur/data"), "auth": Path("/home/oreo/hastur/auth")},
            module.SPECS["hastur"],
        )

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
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=argus-hastur-backup.service", timer)


if __name__ == "__main__":
    unittest.main()
