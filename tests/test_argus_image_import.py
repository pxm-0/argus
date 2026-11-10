from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("argus_image_import", str(ROOT / "scripts" / "argus-image-import"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)

DIGEST = "sha256:" + "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
NODENS = f"ghcr.io/pxm-0/nodens@{DIGEST}"
CADDY = f"docker.io/library/caddy@{DIGEST}"


class FakeSave:
    def __init__(self, returncode: int = 0) -> None:
        self.stdout = io.BytesIO(b"tar")
        self.stderr = io.BytesIO(b"save broke" if returncode else b"")
        self.returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int:
        return self.returncode

    def kill(self) -> None:
        raise AssertionError("save should already have exited")


def completed(command: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class ImageImportTests(unittest.TestCase):
    def test_repo_registry_lists_the_rootless_domains(self) -> None:
        domains = module.rootless_domains()
        self.assertIn("personal-managed", domains)
        self.assertNotIn("legacy-rootful", domains)

    def test_allowlist_accepts_only_digest_pinned_references(self) -> None:
        domains = {"personal-managed"}
        module.validate("personal-managed", NODENS, domains)
        module.validate("personal-managed", CADDY, domains)
        for image in (
            "ghcr.io/pxm-0/nodens:latest",
            f"ghcr.io/other/nodens@{DIGEST}",
            f"docker.io/library/nginx@{DIGEST}",
            f"caddy@{DIGEST}",
            f"ghcr.io/pxm-0/Nodens@{DIGEST}",
            f"ghcr.io/pxm-0/nodens@sha256:{'a' * 63}",
            f"{NODENS} --privileged",
        ):
            with self.subTest(image=image), self.assertRaisesRegex(ValueError, "allowlisted"):
                module.validate("personal-managed", image, domains)
        with self.assertRaisesRegex(ValueError, "unknown rootless trust domain"):
            module.validate("legacy-rootful", NODENS, domains)

    def test_malformed_registry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(module.ImportFailure):
                module.rootless_domains(path)

    def test_import_pulls_saves_loads_and_reports_domain_image_id(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if command[-1] == "load":
                return completed(command, stdout=f"Loaded image ID: {IMAGE_ID}\n")
            if "inspect" in command:
                return completed(command, stdout=IMAGE_ID + "\n")
            return completed(command)

        with patch.object(module.subprocess, "run", side_effect=run), patch.object(
            module.subprocess, "Popen", return_value=FakeSave()
        ) as popen:
            self.assertEqual(IMAGE_ID, module.import_image("personal-managed", NODENS))
        popen.assert_called_once()
        self.assertEqual(["docker", "save", NODENS], popen.call_args.args[0])
        domain = ["runuser", "-u", "argus-personal-managed", "--", "docker", "--host",
                  "unix:///var/lib/argus/personal-managed/docker.sock"]
        self.assertEqual(
            [["docker", "pull", NODENS], [*domain, "load"],
             [*domain, "image", "inspect", "--format", "{{.Id}}", IMAGE_ID]],
            calls,
        )

    def test_save_failure_fails_closed(self) -> None:
        with patch.object(module.subprocess, "run", return_value=completed([], stdout="")), patch.object(
            module.subprocess, "Popen", return_value=FakeSave(returncode=1)
        ), self.assertRaisesRegex(module.ImportFailure, "docker save failed"):
            module.import_image("personal-managed", NODENS)

    def test_pull_failure_stops_before_save(self) -> None:
        with patch.object(module.subprocess, "run", return_value=completed([], 1, stderr="denied")), patch.object(
            module.subprocess, "Popen"
        ) as popen, self.assertRaisesRegex(module.ImportFailure, "pull failed"):
            module.import_image("personal-managed", NODENS)
        popen.assert_not_called()

    def test_ambiguous_load_output_fails_closed(self) -> None:
        with self.assertRaises(module.ImportFailure):
            module.loaded_reference("Loaded image: a\nLoaded image: b\n")
        self.assertEqual("ghcr.io/pxm-0/nodens:1", module.loaded_reference("Loaded image: ghcr.io/pxm-0/nodens:1\n"))

    def test_main_rejects_invalid_reference_before_privilege_checks(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            status = module.main(["--domain", "personal-managed", "--image", "ghcr.io/pxm-0/nodens:latest"])
        self.assertEqual(2, status)
        self.assertEqual("image-import-invalid", json.loads(stdout.getvalue())["error"]["code"])

    def test_main_requires_root(self) -> None:
        with patch.object(module.os, "geteuid", return_value=1000), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            status = module.main(["--domain", "personal-managed", "--image", NODENS])
        self.assertEqual(3, status)
        self.assertEqual("image-import-refused", json.loads(stdout.getvalue())["error"]["code"])


class RegistryConfigTests(unittest.TestCase):
    def test_dedicated_docker_config_is_selected_only_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotEqual(tmp, module.registry_env(Path(tmp)).get("DOCKER_CONFIG"))
            (Path(tmp) / "config.json").write_text("{}")
            self.assertEqual(tmp, module.registry_env(Path(tmp))["DOCKER_CONFIG"])

    def test_host_pull_uses_registry_env_and_save_load_do_not_need_it(self) -> None:
        env = {"DOCKER_CONFIG": "/etc/argus/registry/.docker"}
        calls: list[dict] = []

        def fake_run(command, **kwargs):  # noqa: ANN001
            calls.append({"command": command, "env": kwargs.get("env")})
            return subprocess.CompletedProcess(command, 1, "", "denied")

        with patch.object(module, "registry_env", return_value=env), patch.object(module.subprocess, "run", fake_run):
            with self.assertRaises(module.ImportFailure):
                module.import_image("personal-managed", NODENS)
        self.assertEqual(["docker", "pull", NODENS], calls[0]["command"])
        self.assertEqual(env, calls[0]["env"])

    def test_abbreviated_flags_are_rejected(self) -> None:
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            module.main(["--dom", "personal-managed", "--image", NODENS])


if __name__ == "__main__":
    unittest.main()
