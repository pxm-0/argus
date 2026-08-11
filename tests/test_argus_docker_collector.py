from __future__ import annotations

import copy
import json
import os
import random
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_collectors import PageValidator, collection_request  # noqa: E402
from argus_docker_collector import (  # noqa: E402
    DOCKER_API_VERSION,
    DockerApiClient,
    DockerCollectorError,
    RootfulDockerCollectorServer,
    build_pages,
    collect_docker_records,
    load_runtime_source,
)
from argus_ipc import MAX_FRAME_BYTES, encode_frame, receive_frame, send_frame  # noqa: E402
from argus_observations import canonical_bytes, digest, load_registry  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "docker" / "rootful-api-v1.40.json"


class FixtureClient:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.paths: list[str] = []
        self.verified = False

    def get(self, path: str):
        self.paths.append(path)
        if path not in self.responses:
            raise DockerCollectorError("docker-api-request-failed")
        return copy.deepcopy(self.responses[path])

    def verify_unchanged(self) -> None:
        self.verified = True


def fixture_responses() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["responses"]


class UnixHttpFixture:
    def __init__(self, root: Path, responses: dict[str, object]):
        self.path = root / "docker.sock"
        self.responses = responses
        self.requests: list[tuple[str, str]] = []
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.path))
        os.chmod(self.path, 0o660)
        self.listener.listen(4)
        self.listener.settimeout(0.1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                connection, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                payload = b""
                while b"\r\n\r\n" not in payload:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    payload += chunk
                first = payload.split(b"\r\n", 1)[0].decode("ascii")
                method, path, _version = first.split(" ", 2)
                self.requests.append((method, path))
                body_value = self.responses.get(path)
                status = b"200 OK" if path in self.responses else b"404 Not Found"
                body = json.dumps(body_value, sort_keys=True, separators=(",", ":")).encode()
                connection.sendall(
                    b"HTTP/1.1 " + status + b"\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"Connection: close\r\n\r\n" + body
                )

    def close(self) -> None:
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=2)
        self.path.unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class DockerCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry(
            ROOT / "config" / "argus" / "observation-sources.json",
            ROOT,
        )
        self.source = self.registry.sources["oreochiserver.rootful-docker"]
        self.request = collection_request(
            self.source,
            refresh_id="docker-fixture",
            run_id="docker-fixture-run",
            explicit_clock="2026-08-05T00:00:00Z",
        )

    def collect(self, responses: dict[str, object] | None = None):
        client = FixtureClient(responses or fixture_responses())
        return collect_docker_records(self.source, self.request, client), client

    def test_happy_fixture_reports_running_stopped_and_named_resources(self) -> None:
        records, client = self.collect()
        self.assertTrue(client.verified)
        self.assertEqual(
            {"container": 2, "image": 2, "network": 1, "volume": 1},
            {
                kind: sum(record["resourceKind"] == kind for record in records)
                for kind in ("container", "image", "network", "volume")
            },
        )
        containers = [record for record in records if record["resourceKind"] == "container"]
        self.assertEqual(["running", "exited"], [record["attributes"]["lifecycle"] for record in containers])
        encoded = canonical_bytes(records).decode()
        for forbidden in (
            "FIXTURE_PRIVATE",
            "must-not-export",
            "private-health-output",
            "/srv/private/app",
            "/var/lib/docker/volumes/private",
            "registry.invalid/private",
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertIn('"addressScope":"loopback"', encoded)
        self.assertIn('"sourceRef":"sha256:', encoded)

    def test_shuffled_fixture_is_byte_identical_one_hundred_times(self) -> None:
        expected, _client = self.collect()
        expected_bytes = canonical_bytes(expected)
        expected_digest = digest(expected)
        for seed in range(100):
            responses = fixture_responses()
            randomizer = random.Random(seed)
            for path in (
                f"/v{DOCKER_API_VERSION}/containers/json?all=1&size=0",
                f"/v{DOCKER_API_VERSION}/images/json?all=1&digests=1",
                f"/v{DOCKER_API_VERSION}/networks",
            ):
                randomizer.shuffle(responses[path])
            randomizer.shuffle(responses[f"/v{DOCKER_API_VERSION}/volumes"]["Volumes"])
            actual, _client = self.collect(responses)
            self.assertEqual(expected_bytes, canonical_bytes(actual))
            self.assertEqual(expected_digest, digest(actual))

    def test_empty_source_completes_with_one_terminal_page(self) -> None:
        responses = fixture_responses()
        responses[f"/v{DOCKER_API_VERSION}/containers/json?all=1&size=0"] = []
        responses[f"/v{DOCKER_API_VERSION}/images/json?all=1&digests=1"] = []
        responses[f"/v{DOCKER_API_VERSION}/networks"] = []
        responses[f"/v{DOCKER_API_VERSION}/volumes"] = {"Volumes": None, "Warnings": None}
        records, _client = self.collect(responses)
        pages = build_pages(self.source, self.request, records)
        self.assertEqual([], records)
        self.assertEqual(1, len(pages))
        self.assertTrue(pages[0]["terminal"])
        self.assertEqual("completed", pages[0]["terminalState"])

    def test_duplicate_mismatched_and_invalid_resource_ids_fail_closed(self) -> None:
        duplicate = fixture_responses()
        duplicate[f"/v{DOCKER_API_VERSION}/containers/json?all=1&size=0"].append(
            copy.deepcopy(duplicate[f"/v{DOCKER_API_VERSION}/containers/json?all=1&size=0"][0])
        )
        with self.assertRaisesRegex(DockerCollectorError, "resource-id-duplicate"):
            self.collect(duplicate)

        mismatched = fixture_responses()
        detail_path = f"/v{DOCKER_API_VERSION}/containers/{'1' * 64}/json?size=0"
        mismatched[detail_path]["Id"] = "3" * 64
        with self.assertRaisesRegex(DockerCollectorError, "container-detail-mismatch"):
            self.collect(mismatched)

        invalid = fixture_responses()
        invalid[f"/v{DOCKER_API_VERSION}/networks"][0]["Id"] = "not-an-id"
        with self.assertRaisesRegex(DockerCollectorError, "resource-id-invalid"):
            self.collect(invalid)

    def test_version_shape_bounds_and_secret_hostility_fail_closed(self) -> None:
        unsupported = fixture_responses()
        unsupported["/version"]["MinAPIVersion"] = "1.41"
        with self.assertRaisesRegex(DockerCollectorError, "version-unsupported"):
            self.collect(unsupported)

        future = fixture_responses()
        future["/version"]["ApiVersion"] = "future"
        with self.assertRaisesRegex(DockerCollectorError, "version-invalid"):
            self.collect(future)

        hostile = fixture_responses()
        detail_path = f"/v{DOCKER_API_VERSION}/containers/{'1' * 64}/json?size=0"
        hostile[detail_path]["Config"]["Labels"]["com.docker.compose.project"] = "token=fixture"
        with self.assertRaisesRegex(Exception, "secret marker"):
            self.collect(hostile)

    def test_pages_are_bounded_and_validate_as_one_deterministic_stream(self) -> None:
        records, _client = self.collect()
        pages = build_pages(self.source, self.request, records)
        validator = PageValidator(self.source, self.request)
        result = None
        for page in pages:
            self.assertLessEqual(len(encode_frame(page)) - 4, MAX_FRAME_BYTES)
            result = validator.accept(page) or result
        validator.finish()
        self.assertIsNotNone(result)
        self.assertEqual(records, result.records)

    def test_http_client_allows_only_pinned_get_routes_and_bounds_raw_json(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory).resolve()
            with UnixHttpFixture(root, {"/version": fixture_responses()["/version"]}) as server:
                metadata = os.lstat(server.path)
                client = DockerApiClient(
                    str(server.path),
                    deadline=time.monotonic() + 2,
                    socket_uid=metadata.st_uid,
                    socket_gid=metadata.st_gid,
                    daemon_uid=os.getuid(),
                    daemon_gid=os.getgid(),
                    response_ceiling=1024,
                    total_ceiling=2048,
                )
                self.assertEqual("1.54", client.get("/version")["ApiVersion"])
                self.assertEqual([("GET", "/version")], server.requests)
                with self.assertRaisesRegex(DockerCollectorError, "route-denied"):
                    client.get("/containers/create")

            with UnixHttpFixture(root, {"/version": {"payload": "x" * 2048}}) as oversized:
                metadata = os.lstat(oversized.path)
                client = DockerApiClient(
                    str(oversized.path),
                    deadline=time.monotonic() + 2,
                    socket_uid=metadata.st_uid,
                    socket_gid=metadata.st_gid,
                    daemon_uid=os.getuid(),
                    daemon_gid=os.getgid(),
                    response_ceiling=128,
                    total_ceiling=256,
                )
                with self.assertRaisesRegex(DockerCollectorError, "response-oversize"):
                    client.get("/version")

    def test_server_authenticates_client_and_emits_current_protocol_pages(self) -> None:
        fixture = fixture_responses()

        def factory(*_args, **_kwargs):
            return FixtureClient(fixture)

        server = RootfulDockerCollectorServer(
            self.source,
            client_uid=123,
            client_gid=456,
            docker_socket_gid=0,
            client_factory=factory,
        )
        client_socket, server_socket = socket.socketpair()
        thread_errors: list[Exception] = []

        def handle() -> None:
            try:
                with server_socket:
                    server._handle(server_socket)
            except Exception as exc:
                thread_errors.append(exc)

        with mock.patch("argus_docker_collector.peer_credentials", return_value=(123, 456)):
            thread = threading.Thread(target=handle)
            thread.start()
            with client_socket:
                send_frame(client_socket, self.request)
                validator = PageValidator(self.source, self.request)
                result = None
                while result is None:
                    result = validator.accept(receive_frame(client_socket))
            thread.join(timeout=2)
        self.assertEqual([], thread_errors)
        self.assertEqual("completed", result.state)

        client_socket, server_socket = socket.socketpair()
        try:
            with mock.patch("argus_docker_collector.peer_credentials", return_value=(999, 999)):
                with self.assertRaisesRegex(DockerCollectorError, "client-peer-mismatch"):
                    server._handle(server_socket)
        finally:
            client_socket.close()
            server_socket.close()

    def test_runtime_source_is_single_source_regular_and_identity_pinned(self) -> None:
        payload = json.loads(
            (ROOT / "config/argus/observation-sources.json").read_text(encoding="utf-8")
        )
        projected = {
            "schemaVersion": payload["schemaVersion"],
            "hostSources": ["oreochiserver.rootful-docker"],
            "sources": [next(item for item in payload["sources"] if item["sourceId"] == "oreochiserver.rootful-docker")],
        }
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory).resolve() / "source.json"
            source_path.write_text(json.dumps(projected), encoding="utf-8")
            os.chown(source_path, os.getuid(), os.getgid())
            source_path.chmod(0o640)
            source = load_runtime_source(
                source_path,
                uid=os.getuid(),
                gid=os.getgid(),
            )
            self.assertEqual("oreochiserver.rootful-docker", source.source_id)
            source_path.chmod(0o644)
            with self.assertRaisesRegex(DockerCollectorError, "binding-mismatch"):
                load_runtime_source(source_path, uid=os.getuid(), gid=os.getgid())

    def test_local_acceptance_and_install_contract_are_complete(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/argus-d2a-rootful-docker-acceptance"),
                "--root", str(ROOT),
                "--source-revision", "c9f12d8",
                "--captured-at", "2026-08-05T00:00:00Z",
                "--target", "local-ci",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        summary = json.loads(completed.stdout)
        self.assertEqual(309, summary["issueId"])
        self.assertEqual(3, len(summary["runs"]))
        self.assertIn('"stopped":1', completed.stderr)

        installer_path = ROOT / "scripts/argus-d2a-rootful-docker-collector"
        subprocess.run(["bash", "-n", str(installer_path)], check=True)
        installer = installer_path.read_text(encoding="utf-8")
        self.assertIn("--acknowledge-d2a-rootful-docker-collector", installer)
        self.assertLess(installer.index("backup_unit\n"), installer.index("install_user\n"))
        apply_body = installer.split("apply() {", 1)[1].split("remove_collector() {", 1)[0]
        self.assertLess(
            apply_body.index("systemd-analyze verify \"$INSTALLED_UNIT\""),
            apply_body.index("systemctl daemon-reload"),
        )
        self.assertIn("socket:0:0:0", installer)
        self.assertIn("control-api-docker-socket-connectable", installer)
        self.assertIn("for docker_path in /run/docker.sock /var/run/docker.sock", installer)
        for forbidden in ("docker stop", "docker restart", "docker rm", "caddy", "tailscale", "cloudflared"):
            self.assertNotIn(forbidden, installer.casefold())

    def test_registry_unit_and_module_preserve_read_write_separation(self) -> None:
        source = self.source
        self.assertEqual({"container", "image", "network", "volume"}, set(source.minimization["resourceKinds"]))
        self.assertEqual([], source.allowlist["commands"])
        self.assertTrue(all(":GET:" in api for api in source.allowlist["apis"]))
        self.assertEqual({"peerUid": 950, "peerGid": 981}, {
            key: source.transport[key] for key in ("peerUid", "peerGid")
        })

        unit = (ROOT / "systemd" / "argus-rootful-docker-collector.service").read_text(encoding="utf-8")
        self.assertIn("User=argus-collector-rootful", unit)
        self.assertIn("SupplementaryGroups=docker", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("PrivateNetwork=true", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("/etc/argus/collectors/rootful-docker-source.json", unit)
        self.assertIn("InaccessiblePaths=", unit)
        api_unit = (ROOT / "systemd" / "argus-control-api.service").read_text(encoding="utf-8")
        self.assertIn("InaccessiblePaths=-/var/run/docker.sock -/run/docker.sock", api_unit)

        module = (ROOT / "scripts" / "argus_docker_collector.py").read_text(encoding="utf-8").casefold()
        for forbidden in (
            "containers/create", "containers/prune", "containers/stop", "containers/restart",
            "operationledger", "capability", "issuer", "openai", "anthropic", "subprocess", "shell=true",
        ):
            self.assertNotIn(forbidden, module)


if __name__ == "__main__":
    unittest.main()
