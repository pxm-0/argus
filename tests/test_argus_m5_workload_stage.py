import importlib.machinery
import importlib.util
import os
from pathlib import Path
import signal
import sys
import tarfile
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-m5-workload-stage"
loader = importlib.machinery.SourceFileLoader("argus_m5_workload_stage", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class WorkloadStageTests(unittest.TestCase):
    def test_reviewed_domain_mapping_and_secret_exclusions(self) -> None:
        self.assertEqual("personal-sandbox", module.SPECS["hastur"]["domain"])
        self.assertEqual("work-sandbox", module.SPECS["intake-os"]["domain"])
        self.assertIn("auth", module.SPECS["hastur"]["exclude"])
        self.assertIn(".env", module.SPECS["nodens"]["exclude"])
        self.assertIn(".env.server", module.SPECS["intake-os"]["exclude"])

    def test_source_archive_excludes_secret_and_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input"
            source.mkdir()
            (source / "keep.txt").write_text("keep")
            (source / ".env").write_text("secret")
            (source / ".env.local").write_text("secret")
            (source / "auth").mkdir()
            (source / "auth" / "token").write_text("secret")
            archive = root / "source.tar.gz"
            module.archive_source(source, archive, (".env", "auth"))
            with tarfile.open(archive) as handle:
                names = handle.getnames()
            self.assertIn("source/keep.txt", names)
            self.assertNotIn("source/.env", names)
            self.assertNotIn("source/.env.local", names)
            self.assertNotIn("source/auth/token", names)

    def test_tar_manifest_covers_metadata_links_empty_dirs_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "empty").mkdir()
            (source / "file").write_text("payload")
            (source / "link").symlink_to("file")
            archive = root / "state.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(source, arcname=".")
            records = module.tar_manifest(archive)
            self.assertTrue(any(record["name"].endswith("empty") for record in records))
            self.assertTrue(any(record["linkname"] == "file" for record in records))
            self.assertTrue(any("sha256" in record for record in records))

    def test_sanitized_compose_is_internal_and_immutable(self) -> None:
        rendered = {
            "services": {
                "web": {
                    "build": {"context": "."},
                    "ports": ["8080:80"],
                    "environment": {"TOKEN": "secret"},
                    "volumes": [
                        {
                            "type": "bind",
                            "source": "/home/oreo/nodens/site",
                            "target": "/site",
                        }
                    ],
                }
            },
            "networks": {"default": {}},
        }
        inventory = [
            {
                "composeService": "web",
                "imageId": "sha256:abc",
                "mounts": [
                    {
                        "type": "bind",
                        "name": "",
                        "source": "/home/oreo/nodens/site",
                        "destination": "/site",
                    }
                ],
            }
        ]
        sanitized, blockers = module.sanitize_compose(
            rendered,
            inventory,
            Path("/var/lib/argus/migration-staging/personal-sandbox/nodens/id"),
            module.SPECS["nodens"],
        )
        service = sanitized["services"]["web"]
        self.assertEqual("sha256:abc", service["image"])
        self.assertNotIn("ports", service)
        self.assertNotIn("environment", service)
        self.assertNotIn("build", service)
        self.assertTrue(sanitized["networks"]["default"]["internal"])
        self.assertEqual(["service:web:runtime-environment"], blockers)

    def test_declared_egress_workload_gets_a_routable_network(self) -> None:
        """cutover declares an egress policy for hastur (DNS + tcp/443), but
        marking the target network internal removes its default route
        regardless of any nft/masquerade allow rule -- confirmed live
        2026-07-31, where the bridge and nft rules were both correct and
        egress still failed with ENETUNREACH. A workload with has_egress
        must not get internal=True, or the allow rule is unreachable."""
        rendered = {"services": {"hastur": {}}, "networks": {"default": {}}}
        inventory = [{"composeService": "hastur", "imageId": "sha256:abc", "mounts": []}]
        spec = {**module.SPECS["hastur"], "offline_command_overrides": {}}
        sanitized, _blockers = module.sanitize_compose(
            rendered, inventory,
            Path("/var/lib/argus/migration-staging/personal-sandbox/hastur/id"),
            spec,
        )
        self.assertFalse(sanitized["networks"]["default"]["internal"])

    def test_sealed_workload_without_egress_stays_internal(self) -> None:
        rendered = {"services": {"web": {}}, "networks": {"default": {}}}
        inventory = [{"composeService": "web", "imageId": "sha256:abc", "mounts": []}]
        sanitized, _blockers = module.sanitize_compose(
            rendered, inventory, Path("/var/lib/argus/migration-staging/personal-sandbox/nodens/id"),
            module.SPECS["nodens"],
        )
        self.assertTrue(sanitized["networks"]["default"]["internal"])

    def test_sanitized_compose_uses_verified_rootless_image_map(self) -> None:
        rendered = {"services": {"web": {}}, "networks": {"default": {}}}
        inventory = [
            {
                "composeService": "web",
                "imageId": "sha256:source",
                "mounts": [],
            }
        ]
        sanitized, _blockers = module.sanitize_compose(
            rendered,
            inventory,
            Path("/var/lib/argus/migration-staging/personal-sandbox/nodens/id"),
            module.SPECS["nodens"],
            target_image_map={"sha256:source": "sha256:flattened"},
            target_runtime_config_map={
                "sha256:source": {
                    "command": ["server"],
                    "healthcheck": {
                        "test": ["CMD", "true"],
                        "interval": "30000000000ns",
                    },
                }
            },
        )
        self.assertEqual(
            "sha256:flattened", sanitized["services"]["web"]["image"]
        )
        self.assertEqual(["server"], sanitized["services"]["web"]["command"])
        self.assertEqual(
            {
                "test": ["CMD", "true"],
                "interval": "30000000000ns",
            },
            sanitized["services"]["web"]["healthcheck"],
        )

    def test_image_runtime_config_is_rendered_for_compose(self) -> None:
        original_image_config = module.image_config
        module.image_config = lambda _image_id: {
            "Cmd": ["server"],
            "Entrypoint": ["/entrypoint"],
            "Env": ["SECRET=image-default"],
            "WorkingDir": "/app",
            "User": "1000",
            "StopSignal": "SIGQUIT",
            "ExposedPorts": {"8080/tcp": {}},
            "Labels": {"example": "value"},
            "Healthcheck": {
                "Test": ["CMD-SHELL", "wget -qO- localhost/healthz"],
                "Interval": 30_000_000_000,
                "Timeout": 3_000_000_000,
                "StartPeriod": 5_000_000_000,
                "Retries": 3,
            },
        }
        try:
            self.assertEqual(
                {
                    "command": ["server"],
                    "entrypoint": ["/entrypoint"],
                    "working_dir": "/app",
                    "user": "1000",
                    "stop_signal": "SIGQUIT",
                    "expose": ["8080/tcp"],
                    "labels": {"example": "value"},
                    "healthcheck": {
                        "test": ["CMD-SHELL", "wget -qO- localhost/healthz"],
                        "interval": "30000000000ns",
                        "timeout": "3000000000ns",
                        "start_period": "5000000000ns",
                        "retries": 3,
                    },
                },
                module.image_runtime_config_for_compose("sha256:source"),
            )
        finally:
            module.image_config = original_image_config

    def test_flatten_import_never_places_image_environment_in_argv(self) -> None:
        script = SCRIPT.read_text()
        self.assertNotIn('changes.append(f"ENV {entry}")', script)
        self.assertIn(
            'command = [*target, "import", "--platform", "linux/amd64", "-"]',
            script,
        )

    def test_postgres_bootstrap_identity_stays_out_of_argv(self) -> None:
        original_text = module.text
        module.text = lambda _command: (
            '["POSTGRES_USER=kadath","POSTGRES_PASSWORD=private-value",'
            '"POSTGRES_DB=kadath","PGDATA=/var/lib/postgresql/data"]'
        )
        try:
            environment, role, database = module.source_database_environment(
                "source-postgres"
            )
        finally:
            module.text = original_text
        self.assertEqual("kadath", role)
        self.assertEqual("kadath", database)
        self.assertEqual("private-value", environment["POSTGRES_PASSWORD"])
        script = SCRIPT.read_text()
        self.assertIn('database_command.extend(["-e", key])', script)
        self.assertNotIn('"POSTGRES_HOST_AUTH_METHOD=trust"', script)

    def test_postgres_default_identity_is_resolved(self) -> None:
        original_text = module.text
        module.text = lambda _command: '["POSTGRES_PASSWORD=private-value"]'
        try:
            environment, role, database = module.source_database_environment(
                "source-postgres"
            )
        finally:
            module.text = original_text
        self.assertEqual("postgres", role)
        self.assertEqual("postgres", database)
        self.assertEqual("postgres", environment["POSTGRES_USER"])
        self.assertEqual("postgres", environment["POSTGRES_DB"])
        script = SCRIPT.read_text()
        self.assertNotIn("$POSTGRES_USER", script)
        self.assertNotIn("$POSTGRES_DB", script)

    def test_postgres_tcp_password_is_environment_only(self) -> None:
        original_run = module.run
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs.get("env", {})))
            return type(
                "Completed",
                (),
                {"returncode": 0 if len(calls) == 1 else 1},
            )()

        module.run = fake_run
        try:
            result = module.database_tcp_authentication(
                ["docker"],
                "postgres-container",
                "postgres",
                "postgres",
                "private-value",
            )
        finally:
            module.run = original_run
        self.assertTrue(result["capturedIdentityAccepted"])
        self.assertTrue(result["incorrectPasswordRejected"])
        for command, environment in calls:
            self.assertIn("-e", command)
            self.assertIn("PGPASSWORD", command)
            self.assertNotIn("private-value", command)
            self.assertIn("PGPASSWORD", environment)

    def test_hastur_package_manager_is_not_needed_at_runtime(self) -> None:
        override = module.SPECS["hastur"]["offline_command_overrides"][
            "hastur"
        ]
        self.assertEqual("start", override["packageScript"])
        self.assertEqual("node src/server.mjs", override["expectedScript"])
        self.assertEqual(["node", "src/server.mjs"], override["command"])
        script = SCRIPT.read_text()
        self.assertIn("offline command package script changed", script)
        self.assertIn('"offlineCommandOverrides"', script)

    def test_postgres_readiness_waits_for_final_pid_one(self) -> None:
        original_run = module.run
        original_sleep = module.time.sleep
        responses = [
            (0, b"bash\n"),
            (0, b""),
            (0, b"postgres\n"),
            (0, b""),
        ]

        def fake_run(_command, **_kwargs):
            returncode, stdout = responses.pop(0)
            return type(
                "Completed",
                (),
                {"returncode": returncode, "stdout": stdout},
            )()

        module.run = fake_run
        module.time.sleep = lambda _seconds: None
        try:
            module.wait_target_database_ready(
                ["docker"], "postgres", "app", "app", timeout=1
            )
        finally:
            module.run = original_run
            module.time.sleep = original_sleep
        self.assertEqual([], responses)

    def test_cleanup_resources_require_random_ownership_label(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("com.argus.m5-stage-id", script)
        self.assertIn("verify_owned_volume", script)
        self.assertIn("random stage container unexpectedly exists", script)
        self.assertIn("migration-staging", script)
        self.assertIn("named volume lacks a verified staged restore", script)
        self.assertIn("cross-container or host network modes are forbidden", script)
        self.assertIn("os.O_NOFOLLOW", script)
        self.assertIn("staged volume consumption does not match restore inventory", script)
        self.assertIn("hashtextextended", script)
        self.assertIn("rollback-summary.json.sha256", script)
        self.assertIn("quiesced_archive_state", script)
        self.assertIn("compare_restored_state", script)
        self.assertIn("gnuTarContentMetadataCompare", script)
        self.assertIn("source container unpause failed", script)
        self.assertIn("sourceWasPristineImageContainer", script)
        self.assertIn("rootlessCompatibilityImages", script)
        self.assertIn("docker\", \"export\", source_container", script)
        self.assertIn("--acknowledge-m5-workload-stage-rollback", script)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "requires Linux fork and pthread signal semantics",
    )
    def test_parent_only_signal_interrupts_archive_child(self) -> None:
        pid = os.fork()
        if pid == 0:
            previous_mask = signal.pthread_sigmask(
                signal.SIG_BLOCK, module.HANDLED_SIGNALS
            )
            try:
                module.run(
                    ["sleep", "30"],
                    child_signal_mask=previous_mask,
                )
            except InterruptedError:
                os._exit(0)
            except BaseException:
                os._exit(2)
            os._exit(3)
        try:
            time.sleep(0.5)
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                waited_pid, status = os.waitpid(pid, os.WNOHANG)
                if waited_pid == pid:
                    self.assertEqual(0, os.waitstatus_to_exitcode(status))
                    return
                time.sleep(0.1)
            self.fail("parent-only SIGTERM did not interrupt archive child")
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass


if __name__ == "__main__":
    unittest.main()
