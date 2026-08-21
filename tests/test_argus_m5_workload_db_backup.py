import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
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
            {"kadath": "personal-sandbox", "intake-os": "work-sandbox"},
            {name: spec["domain"] for name, spec in module.SPECS.items()},
        )

    def test_credentials_come_from_the_container_not_the_repo(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("{{json .Config.Env}}", script)
        self.assertNotIn('\"printenv\"', script)
        self.assertNotIn("POSTGRES_PASSWORD=", script)

    def test_database_lookup_includes_an_exited_container(self) -> None:
        calls = []
        original = module.text
        module.text = lambda command, *_args: calls.append(command) or "postgres-1\n"
        try:
            self.assertEqual(
                "postgres-1", module.container_name(module.SPECS["kadath"])
            )
        finally:
            module.text = original
        self.assertIn("--all", calls[0])

    def test_postgres_identity_comes_from_the_exact_networkless_image(self) -> None:
        calls = []
        image = "sha256:" + "a" * 64

        def fake_text(command, *_args):
            calls.append(command)
            return image + "\n" if "inspect" in command else "70\n70\n"

        original = module.text
        module.text = fake_text
        try:
            self.assertEqual(
                (70, 70),
                module.postgres_container_ids(
                    module.SPECS["intake-os"], "intake-os-postgres-1"
                ),
            )
        finally:
            module.text = original
        probe = calls[1]
        self.assertIn("--network", probe)
        self.assertEqual("none", probe[probe.index("--network") + 1])
        self.assertIn("--read-only", probe)
        self.assertIn(image, probe)
        self.assertNotIn("POSTGRES_PASSWORD", " ".join(probe))

    def test_dump_is_verified_before_it_counts(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("pg_restore", script)
        self.assertIn("--list", script)
        self.assertIn("partial", script)

    def test_backup_refuses_a_volume_with_wrong_ownership(self) -> None:
        original = module.ownership_status
        module.ownership_status = lambda *_args: {
            "ok": False,
            "nonPostgresOwnedEntries": 1,
        }
        try:
            with self.assertRaises(module.BackupError):
                module.require_owned_volume("kadath", "kadath-live-postgres-1")
        finally:
            module.ownership_status = original

    def test_repair_requires_exact_workload_confirmation(self) -> None:
        with self.assertRaises(module.BackupError):
            module.repair_ownership("kadath", "locigraph")

    def test_rootless_mapping_uses_the_container_id_offset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "subuid"
            mapping.write_text("argus-personal-sandbox:231072:65536\n")
            self.assertEqual(
                232070,
                module.rootless_host_id(
                    "argus-personal-sandbox", mapping, 999
                ),
            )

    def test_database_readiness_requires_a_real_query(self) -> None:
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=1 if "psql" in command else 0)

        original = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            ready = module.database_ready(
                module.SPECS["kadath"],
                "kadath-live-postgres-1",
                "kadath",
                "kadath",
            )
        finally:
            module.subprocess.run = original

        self.assertFalse(ready)
        self.assertEqual(2, len(calls))
        self.assertIn("pg_isready", calls[0])
        self.assertIn("psql", calls[1])
        self.assertIn("SELECT 1", calls[1])
        self.assertNotIn("POSTGRES_PASSWORD", " ".join(calls[1]))

    def test_snapshot_is_fully_readable_and_private(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "PG_VERSION").write_text("18\n")
            destination = root / "snapshot.tar.gz"

            module.snapshot_volume(source, destination)

            self.assertEqual(0o600, destination.stat().st_mode & 0o777)
            with module.tarfile.open(destination, "r:gz") as archive:
                self.assertIn("./PG_VERSION", archive.getnames())

    def test_failed_repair_restores_snapshot_before_restart(self) -> None:
        events = []
        states = iter(("running", "exited", "exited"))
        ownership = iter(
            (
                {"ok": False, "nonPostgresOwnedEntries": 2},
                {"ok": False, "nonPostgresOwnedEntries": 1},
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "volume" / "_data"
            source.mkdir(parents=True)
            originals = (
                module.BACKUP_ROOT,
                module.os.geteuid,
                module.container_name,
                module.credentials,
                module.ownership_status,
                module.volume_source,
                module.directory_identity,
                module.container_state,
                module.ensure_root_directory,
                module.stop_database,
                module.snapshot_volume,
                module.repair_volume_ownership,
                module.restore_volume,
                module.start_database,
            )
            module.BACKUP_ROOT = root / "backups"
            module.os.geteuid = lambda: 0
            module.container_name = lambda _spec: "kadath-live-postgres-1"
            module.credentials = lambda _spec, _container: ("kadath", "kadath")
            module.ownership_status = lambda *_args: next(ownership)
            module.volume_source = lambda *_args: source
            module.directory_identity = lambda _path: (1, 2)
            module.container_state = lambda *_args: next(states)
            module.ensure_root_directory = lambda path: path.mkdir(
                parents=True, exist_ok=True
            )
            module.stop_database = lambda *_args: events.append("stop")

            def snapshot(_source, destination):
                events.append("snapshot")
                destination.write_bytes(b"snapshot")

            module.snapshot_volume = snapshot
            module.repair_volume_ownership = lambda *_args: events.append("repair")
            module.restore_volume = lambda *_args: events.append("restore")
            module.start_database = lambda *_args: events.append("start")
            try:
                with self.assertRaises(module.BackupError):
                    module.repair_ownership("kadath", "kadath")
            finally:
                (
                    module.BACKUP_ROOT,
                    module.os.geteuid,
                    module.container_name,
                    module.credentials,
                    module.ownership_status,
                    module.volume_source,
                    module.directory_identity,
                    module.container_state,
                    module.ensure_root_directory,
                    module.stop_database,
                    module.snapshot_volume,
                    module.repair_volume_ownership,
                    module.restore_volume,
                    module.start_database,
                ) = originals

        self.assertEqual(
            ["stop", "snapshot", "repair", "restore", "start"],
            events,
        )

    def test_repair_can_recover_an_exited_database(self) -> None:
        events = []
        ownership = iter(
            (
                {"ok": False, "nonPostgresOwnedEntries": 2},
                {"ok": True, "nonPostgresOwnedEntries": 0},
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "volume" / "_data"
            source.mkdir(parents=True)
            originals = (
                module.BACKUP_ROOT,
                module.os.geteuid,
                module.container_name,
                module.credentials,
                module.ownership_status,
                module.volume_source,
                module.directory_identity,
                module.container_state,
                module.ensure_root_directory,
                module.stop_database,
                module.snapshot_volume,
                module.repair_volume_ownership,
                module.start_database,
                module.wait_for_database,
            )
            module.BACKUP_ROOT = root / "backups"
            module.os.geteuid = lambda: 0
            module.container_name = lambda _spec: "kadath-live-postgres-1"
            module.credentials = lambda *_args: ("kadath", "kadath")
            module.ownership_status = lambda *_args: next(ownership)
            module.volume_source = lambda *_args: source
            module.directory_identity = lambda _path: (1, 2)
            module.container_state = lambda *_args: "exited"
            module.ensure_root_directory = lambda path: path.mkdir(
                parents=True, exist_ok=True
            )
            module.stop_database = lambda *_args: events.append("stop")

            def snapshot(_source, destination):
                events.append("snapshot")
                destination.write_bytes(b"snapshot")

            module.snapshot_volume = snapshot
            module.repair_volume_ownership = lambda *_args: events.append("repair")
            module.start_database = lambda *_args: events.append("start")
            module.wait_for_database = lambda *_args: events.append("query")
            try:
                result = module.repair_ownership("kadath", "kadath")
            finally:
                (
                    module.BACKUP_ROOT,
                    module.os.geteuid,
                    module.container_name,
                    module.credentials,
                    module.ownership_status,
                    module.volume_source,
                    module.directory_identity,
                    module.container_state,
                    module.ensure_root_directory,
                    module.stop_database,
                    module.snapshot_volume,
                    module.repair_volume_ownership,
                    module.start_database,
                    module.wait_for_database,
                ) = originals

        self.assertTrue(result["verified"])
        self.assertEqual(["snapshot", "repair", "start", "query"], events)

    def test_database_operations_use_a_nonblocking_workload_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            originals = (
                module.LOCK_ROOT,
                module.ensure_root_directory,
                module.os.fstat,
            )
            module.LOCK_ROOT = Path(directory) / "locks"
            module.ensure_root_directory = lambda path: path.mkdir(
                parents=True, exist_ok=True
            )
            module.os.fstat = lambda _descriptor: SimpleNamespace(
                st_uid=0,
                st_mode=module.stat.S_IFREG | 0o600,
            )
            first = None
            try:
                first = module.acquire_workload_lock("kadath")
                with self.assertRaisesRegex(
                    module.BackupError,
                    "another kadath database operation is active",
                ):
                    module.acquire_workload_lock("kadath")
            finally:
                if first is not None:
                    first.close()
                (
                    module.LOCK_ROOT,
                    module.ensure_root_directory,
                    module.os.fstat,
                ) = originals

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

    def test_exec_flags_match_plain_docker_and_pipe_the_dump_back_in(self) -> None:
        """Pins both #266 follow-ups: -T is not a docker exec flag, and the
        verify step gets /dev/null on stdin unless -i is passed."""
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if "pg_dump" in command:
                kwargs["stdout"].write(b"PGDMP-fake")
            return None

        with tempfile.TemporaryDirectory() as directory:
            originals = (
                module.BACKUP_ROOT,
                module.subprocess.run,
                module.os.geteuid,
                module.ensure_root_directory,
                module.container_name,
                module.credentials,
                module.require_owned_volume,
            )
            module.BACKUP_ROOT = Path(directory)
            module.subprocess.run = fake_run
            module.os.geteuid = lambda: 0
            module.ensure_root_directory = lambda path: path.mkdir(
                parents=True, exist_ok=True
            )
            module.container_name = lambda _spec: "kadath-live-postgres-1"
            module.credentials = lambda _spec, _container: ("kadath", "kadath")
            module.require_owned_volume = lambda _workload, _container: {
                "ok": True
            }
            try:
                result = module.backup("kadath")
            finally:
                (
                    module.BACKUP_ROOT,
                    module.subprocess.run,
                    module.os.geteuid,
                    module.ensure_root_directory,
                    module.container_name,
                    module.credentials,
                    module.require_owned_volume,
                ) = originals

        dump, verify = calls
        # docker exec has no -T (that is docker compose exec); passing it made
        # the dump exit 125 on the host's Docker 29.5.3.
        self.assertNotIn("-T", dump)
        self.assertNotIn("-T", verify)
        # The dump writes to a file handle and needs no stdin.
        self.assertNotIn("-i", dump)
        # The verify reads the artifact on stdin, so -i is mandatory.
        self.assertIn("-i", verify)
        self.assertEqual("-i", verify[verify.index("exec") + 1])
        self.assertTrue(result["verified"])
        self.assertEqual(len(b"PGDMP-fake"), result["artifactBytes"])

    def test_units_are_root_and_instanced_per_workload(self) -> None:
        service = (ROOT / "templates" / "systemd" / "argus-workload-db-backup@.service").read_text()
        timer = (ROOT / "templates" / "systemd" / "argus-workload-db-backup@.timer").read_text()
        self.assertIn("User=root", service)
        self.assertIn("--workload %i", service)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=argus-workload-db-backup@%i.service", timer)


if __name__ == "__main__":
    unittest.main()
