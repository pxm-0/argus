import importlib.machinery
import importlib.util
import os
from pathlib import Path
import signal
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
        self.assertIn("--acknowledge-m5-workload-stage-rollback", script)

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
