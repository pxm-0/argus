import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-m5-workload-db-backup"
loader = importlib.machinery.SourceFileLoader("argus_m5_db_backup", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class DatabaseBackupTest(unittest.TestCase):
    def test_dump_runs_inside_the_sandbox_not_on_the_host(self) -> None:
        command = module.target_command("personal-sandbox", "ps")
        self.assertEqual(
            [
                "runuser",
                "-u",
                "argus-personal-sandbox",
                "--",
                "env",
                "HOME=/home/argus-personal-sandbox",
                "docker",
                "--host",
                "unix:///var/lib/argus/personal-sandbox/docker.sock",
                "ps",
            ],
            command,
        )
        # The failure in #266 was a host-side compose call, which cannot
        # reach a sealed sandbox. Check the code, not the prose.
        script = SCRIPT.read_text()
        code = script.split('"""', 2)[-1]
        self.assertNotIn('"compose"', code)
        self.assertNotIn("/home/oreo", code)

    def test_every_database_workload_is_mapped_to_its_domain(self) -> None:
        self.assertEqual(
            {"kadath": "personal-sandbox", "locigraph": "personal-sandbox", "intake-os": "work-sandbox"},
            {name: spec["domain"] for name, spec in module.SPECS.items()},
        )

    def test_credentials_come_from_the_container_not_the_repo(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("printenv", script)
        self.assertNotIn("POSTGRES_PASSWORD=", script)

    def test_dump_is_verified_before_it_counts(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("pg_restore", script)
        self.assertIn("--list", script)
        self.assertIn("partial", script)

    def test_pruning_keeps_the_newest_copies_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [f"kadath-2026073{index}T023500Z.dump" for index in range(5)]
            for name in names:
                (root / name).write_text("x")
            (root / "notes.txt").write_text("keep me")
            removed = module.prune(root, 2)
            self.assertEqual(sorted(names[:3]), sorted(removed))
            self.assertTrue((root / names[4]).exists())
            self.assertTrue((root / "notes.txt").exists())

    def test_units_are_root_and_instanced_per_workload(self) -> None:
        service = (ROOT / "templates" / "systemd" / "argus-workload-db-backup@.service").read_text()
        timer = (ROOT / "templates" / "systemd" / "argus-workload-db-backup@.timer").read_text()
        self.assertIn("User=root", service)
        self.assertIn("--workload %i", service)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=argus-workload-db-backup@%i.service", timer)


if __name__ == "__main__":
    unittest.main()
