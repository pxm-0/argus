from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_script(name: str):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(ROOT / "scripts" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


sandbox = load_script("argus-dev-sandbox")
wrapper = load_script("argus-dev")
import argus_sandbox_firewall as firewall  # noqa: E402

IMAGE_ID = "sha256:" + "c" * 64
RUN_ID = "kadath-20261121t100000z-a1b2c3"


def test_request(**overrides):
    payload = {"project": "kadath", "image": "argus-dev/kadath:20261121t100000z", "command": ["pnpm", "test"]}
    payload.update(overrides)
    return payload


def archive(manifest, **members) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    with tarfile.open(fileobj=handle, mode="w") as tar:
        for name, value in {"manifest.json": manifest, **members}.items():
            data = json.dumps(value).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    handle.close()
    return Path(handle.name)


class RequestValidationTests(unittest.TestCase):
    def test_accepts_a_test_request_with_a_postgres_service(self) -> None:
        request = sandbox.validate_request(test_request(
            env={"CI": "1"}, tmpfs=["/tmp"], timeoutSeconds=600,
            services=[{"name": "postgres", "image": IMAGE_ID, "user": "postgres", "env": {"POSTGRES_PASSWORD": "dev-only"}}],
        ), "test")
        self.assertEqual(600, request["timeoutSeconds"])
        self.assertEqual("postgres", request["services"][0]["name"])

    def test_refuses_fields_that_would_widen_the_container(self) -> None:
        for field in ("privileged", "network", "volumes", "mounts", "capAdd", "ports", "pid"):
            with self.subTest(field=field), self.assertRaises(sandbox.Refusal):
                sandbox.validate_request(test_request(**{field: True}), "test")
        with self.assertRaises(sandbox.Refusal):
            sandbox.validate_request(test_request(services=[{"name": "db", "image": IMAGE_ID, "network": "host"}]), "test")

    def test_refuses_images_outside_the_project_namespace(self) -> None:
        for image in ("argus-dev/other:1", "ghcr.io/pxm-0/kadath:1", "argus-dev/kadath:", "argus-dev/kadath:../x", IMAGE_ID):
            with self.subTest(image=image), self.assertRaises(sandbox.Refusal):
                sandbox.validate_request(test_request(image=image), "test")
        with self.assertRaises(sandbox.Refusal):
            sandbox.validate_request(test_request(services=[{"name": "db", "image": "postgres:17"}]), "test")

    def test_refuses_bad_names_paths_env_and_bounds(self) -> None:
        bad = (
            {"project": "Kadath"},
            {"tmpfs": ["relative"]},
            {"tmpfs": ["/a/../etc"]},
            {"env": {"BAD-KEY": "x"}},
            {"user": "root;id"},
            {"command": "pnpm test"},
            {"timeoutSeconds": 0},
            {"timeoutSeconds": True},
            {"services": [{"name": "main", "image": IMAGE_ID}]},
            {"services": [{"name": "db", "image": IMAGE_ID}, {"name": "db", "image": IMAGE_ID}]},
        )
        for overrides in bad:
            with self.subTest(overrides=overrides), self.assertRaises(sandbox.Refusal):
                sandbox.validate_request(test_request(**overrides), "test")

    def test_preview_needs_a_port_and_a_known_slot(self) -> None:
        self.assertEqual(2, sandbox.validate_request(test_request(port=3000, slot=2), "preview")["slot"])
        for overrides in ({}, {"port": 0}, {"port": 3000, "slot": 3}, {"port": 3000, "slot": True}, {"port": 3000, "timeoutSeconds": 5}):
            with self.subTest(overrides=overrides), self.assertRaises(sandbox.Refusal):
                sandbox.validate_request(test_request(**overrides), "preview")

    def test_run_selectors_take_only_a_well_formed_run_id(self) -> None:
        self.assertEqual(RUN_ID, sandbox.run_selector({"run": RUN_ID}, "logs"))
        for payload in ({"run": "nodens-staging-nodens-1"}, {"run": RUN_ID, "x": 1}, [], {"run": RUN_ID + "0"}):
            with self.subTest(payload=payload), self.assertRaises(sandbox.Refusal):
                sandbox.run_selector(payload, "logs")


class ArchiveTests(unittest.TestCase):
    def test_reads_the_single_dev_reference(self) -> None:
        path = archive([{"RepoTags": ["argus-dev/kadath:t1"]}], **{
            "index.json": {"manifests": [{"annotations": {"io.containerd.image.name": "docker.io/argus-dev/kadath:t1"}}]},
            "repositories": {"argus-dev/kadath": {"t1": "x"}},
        })
        self.assertEqual("argus-dev/kadath:t1", sandbox.archive_reference(path))

    def test_refuses_archives_that_name_anything_else(self) -> None:
        cases = (
            [[{"RepoTags": ["argus-dev/kadath:t1"]}, {"RepoTags": ["argus-dev/kadath:t2"]}], {}],
            [[{"RepoTags": ["ghcr.io/pxm-0/nodens:t1"]}], {}],
            [[{"RepoTags": ["argus-dev/kadath:t1", "argus-dev/kadath:t2"]}], {}],
            [[{"RepoTags": ["argus-dev/kadath:t1"]}], {"index.json": {"manifests": [{"annotations": {"io.containerd.image.name": "ghcr.io/pxm-0/nodens:x"}}]}}],
            [[{"RepoTags": ["argus-dev/kadath:t1"]}], {"index.json": {"manifests": [{}, {}]}}],
            [[{"RepoTags": ["argus-dev/kadath:t1"]}], {"repositories": {"ghcr.io/pxm-0/nodens": {"x": "y"}}}],
            [None, {}],
        )
        for manifest, members in cases:
            with self.subTest(manifest=manifest, members=list(members)), self.assertRaises(sandbox.Refusal):
                sandbox.archive_reference(archive(manifest, **members) if manifest is not None else archive({}, **members))

    def test_load_refuses_when_docker_loads_a_different_name(self) -> None:
        path = archive([{"RepoTags": ["argus-dev/kadath:t1"]}])
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[-1] == "load":
                return subprocess.CompletedProcess(command, 0, "Loaded image: argus-dev/kadath:t1\nLoaded image: ghcr.io/pxm-0/nodens:x\n", "")
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(sandbox, "SPOOL_DIR", tempfile.gettempdir()), \
             mock.patch.object(sandbox, "archive_reference", return_value="argus-dev/kadath:t1"), \
             mock.patch.object(sandbox.shutil, "disk_usage", return_value=mock.Mock(free=1 << 50)), \
             mock.patch.object(sandbox.subprocess, "run", side_effect=fake_run), \
             self.assertRaises(sandbox.Refusal) as caught:
            sandbox.load(io.BytesIO(path.read_bytes()))
        self.assertEqual("dev-load-mismatch", caught.exception.code)
        self.assertIn(["image", "rm", "argus-dev/kadath:t1"], [c[c.index("--host") + 2:] for c in calls])

    def test_forbidden_labels_catch_identity_forgery(self) -> None:
        labels = {"com.docker.compose.project": "nodens-staging", "argus.dev.slot": "1", "org.opencontainers.image.title": "ok"}
        self.assertEqual(["argus.dev.slot", "com.docker.compose.project"], sandbox.forbidden_labels(labels))
        self.assertEqual([], sandbox.forbidden_labels(None))


class ContainerArgumentTests(unittest.TestCase):
    def test_every_container_is_sealed_and_labelled(self) -> None:
        options = sandbox.validate_request(test_request(env={"CI": "1"}, tmpfs=["/tmp"]), "test")
        args = sandbox.run_args(RUN_ID, "kadath", "main", "none", options)
        joined = " ".join(args)
        for needle in ("--network none", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit 1024", "--memory 4g",
                       "--label argus.dev=1", f"--label argus.dev.run={RUN_ID}", "--label argus.dev.role=main", "--tmpfs /tmp", "--env CI=1"):
            self.assertIn(needle, joined)
        for forbidden in ("--privileged", "--volume", "-v", "--mount", "--publish", "-p", "--cap-add", "--pid", "--userns"):
            self.assertNotIn(forbidden, args)

    def test_ingress_adds_only_its_bind_capability_and_slot_socket(self) -> None:
        args = sandbox.ingress_args(RUN_ID, "kadath", "f" * 64, Path("/var/lib/argus/sandbox-ingress/dev-1"), 3000, {})
        self.assertEqual(["NET_BIND_SERVICE"], [args[i + 1] for i, a in enumerate(args) if a == "--cap-add"])
        self.assertEqual(["type=bind,source=/var/lib/argus/sandbox-ingress/dev-1,target=/run/argus-ingress"],
                         [args[i + 1] for i, a in enumerate(args) if a == "--mount"])
        self.assertIn(f"container:{'f' * 64}", args)
        self.assertIn("--read-only", args)
        self.assertIn('"dial":"127.0.0.1:3000"', sandbox.ingress_config(3000))

    def test_docker_always_runs_as_the_sandbox_user_on_its_socket(self) -> None:
        self.assertEqual(["runuser", "-u", "argus-personal-sandbox", "--", "docker", "--host",
                          "unix:///var/lib/argus/personal-sandbox/docker.sock", "ps"], sandbox.docker("ps"))

    def test_results_and_logs_only_reach_labelled_dev_containers(self) -> None:
        with mock.patch.object(sandbox, "dev_containers", return_value=[]), self.assertRaises(sandbox.Refusal):
            sandbox.run_main(RUN_ID)
        with mock.patch.object(sandbox, "dev_containers", return_value=[{"ID": "nodens-staging-nodens-1"}]), self.assertRaises(sandbox.Refusal):
            sandbox.run_main(RUN_ID)
        with mock.patch.object(sandbox, "dev_containers", return_value=[{"ID": "d" * 64}]) as listed:
            self.assertEqual("d" * 64, sandbox.run_main(RUN_ID)["ID"])
        self.assertIn(f"label=argus.dev.run={RUN_ID}", listed.call_args.args)

    def test_remove_uses_full_ids_only(self) -> None:
        with mock.patch.object(sandbox, "run_docker") as run:
            self.assertEqual(1, sandbox.remove([{"ID": "e" * 64}, {"ID": "abc"}, {}]))
        run.assert_called_once_with("rm", "--force", "--volumes", "e" * 64)

    def test_expiry(self) -> None:
        now = time.time()
        old = time.strftime("%Y-%m-%d %H:%M:%S +0000 UTC", time.gmtime(now - 2 * 86400))
        new = time.strftime("%Y-%m-%d %H:%M:%S +0000 UTC", time.gmtime(now - 60))
        self.assertTrue(sandbox.expired({"Labels": f"argus.dev.expires={int(now) - 1}", "State": "running", "CreatedAt": new}, now))
        self.assertFalse(sandbox.expired({"Labels": f"argus.dev.expires={int(now) + 99}", "State": "running", "CreatedAt": old}, now))
        self.assertTrue(sandbox.expired({"Labels": "argus.dev=1", "State": "exited", "CreatedAt": old}, now))
        self.assertFalse(sandbox.expired({"Labels": "argus.dev=1", "State": "exited", "CreatedAt": new}, now))
        self.assertFalse(sandbox.expired({"Labels": "argus.dev=1", "State": "running", "CreatedAt": old}, now))

    def test_main_refuses_without_root_and_unknown_verbs(self) -> None:
        self.assertEqual(2, sandbox.main(["shell"]))
        self.assertEqual(2, sandbox.main(["test", "extra"]))
        with mock.patch.object(sandbox.os, "geteuid", return_value=1000), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(3, sandbox.main(["status"]))
        self.assertIn("dev-refused", err.getvalue())


def inspected(cid: str, *, labels=None, mode="none", networks=None, **host) -> dict:
    return {
        "Id": cid,
        "Config": {"Labels": {"argus.dev": "1"} if labels is None else labels},
        "HostConfig": {"NetworkMode": mode, "Privileged": False, **host},
        "NetworkSettings": {"Networks": {"none": {"IPAddress": ""}} if networks is None else networks},
    }


class FirewallCarveOutTests(unittest.TestCase):
    def check(self, container, *others) -> bool:
        running = {item["Id"]: item for item in (container, *others)}
        return firewall._loopback_only_dev(container, running)

    def test_skips_only_loopback_only_dev_containers(self) -> None:
        owner = inspected("a" * 64)
        self.assertTrue(self.check(owner))
        self.assertTrue(self.check(inspected("b" * 64, mode=f"container:{'a' * 64}", networks={}), owner))
        self.assertTrue(self.check(inspected("b" * 64, mode=f"container:{'a' * 64}", networks={}, CapAdd=["NET_BIND_SERVICE"]), owner))

    def test_everything_else_still_needs_compose_identity(self) -> None:
        owner = inspected("a" * 64)
        staging = inspected("s" * 64, labels={"com.docker.compose.project": "nodens-staging"}, mode="argus-ndns-stg",
                            networks={"nodens-staging_internal": {"IPAddress": "10.0.0.2"}})
        cases = {
            "no dev label": inspected("b" * 64, labels={}),
            "forged compose label": inspected("b" * 64, labels={"argus.dev": "1", "com.docker.compose.project": "nodens-staging"}),
            "bridge network": inspected("b" * 64, mode="bridge", networks={"bridge": {"IPAddress": "172.17.0.2"}}),
            "privileged": inspected("b" * 64, Privileged=True),
            "host pid": inspected("b" * 64, PidMode="host"),
            "extra capability": inspected("b" * 64, CapAdd=["NET_ADMIN"]),
            "joins a staging container": inspected("b" * 64, mode=f"container:{'s' * 64}", networks={}),
            "joins a missing container": inspected("b" * 64, mode=f"container:{'9' * 64}", networks={}),
            "chained twice": inspected("c" * 64, mode=f"container:{'b' * 64}", networks={}),
        }
        middle = inspected("b" * 64, mode=f"container:{'a' * 64}", networks={})
        for name, container in cases.items():
            with self.subTest(name=name):
                self.assertFalse(self.check(container, owner, staging, middle))

    def test_discovery_ignores_dev_containers_only_in_personal_sandbox(self) -> None:
        source = (ROOT / "scripts" / "argus_sandbox_firewall.py").read_text()
        self.assertIn("if domain == DEV_DOMAIN and _loopback_only_dev(container, running_by_id):", source)
        self.assertEqual("personal-sandbox", firewall.DEV_DOMAIN)


class WrapperTests(unittest.TestCase):
    SPEC = {
        "project": "kadath",
        "build": {"dockerfile": "Dockerfile.dev", "target": "dev"},
        "test": {"command": ["pnpm", "test"], "env": {"CI": "1"}, "timeoutSeconds": 900},
        "preview": {"command": ["pnpm", "dev"], "port": 3000},
        "services": [{"name": "postgres", "image": IMAGE_ID, "user": "postgres"}],
    }

    def test_requests_validate_on_the_server_side(self) -> None:
        test = wrapper.request(self.SPEC, "test", "t1", ["pnpm", "vitest"])
        self.assertEqual(["pnpm", "vitest"], test["command"])
        self.assertEqual("argus-dev/kadath:t1", sandbox.validate_request(test, "test")["image"])
        preview = wrapper.request(self.SPEC, "preview", "t1", slot=2)
        self.assertEqual(2, sandbox.validate_request(preview, "preview")["slot"])

    def test_remote_calls_one_exact_sudo_word(self) -> None:
        with mock.patch.dict(wrapper.os.environ, {"ARGUS_SSH_HOST": "oreochiserver", "ARGUS_REMOTE_REPO": "/opt/argus/current"}):
            self.assertEqual(["ssh", "-o", "BatchMode=yes", "oreochiserver", "sudo", "-n",
                              "/opt/argus/current/scripts/argus-dev-sandbox", "test"], wrapper.remote("test"))

    def test_project_file_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "argus-dev.json").write_text(json.dumps({"project": "Bad Name"}))
            with self.assertRaises(wrapper.DevError):
                wrapper.load_project(Path(directory))
            Path(directory, "argus-dev.json").write_text(json.dumps(self.SPEC))
            self.assertEqual("kadath", wrapper.load_project(Path(directory))["project"])


if __name__ == "__main__":
    unittest.main()
