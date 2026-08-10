from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_collectors import PageValidator, collection_request  # noqa: E402
from argus_docker_collector import DockerCollectorError, build_pages, collect_docker_records  # noqa: E402
from argus_observations import load_registry  # noqa: E402
from argus_rootless_docker_collector import main  # noqa: E402


class FixtureClient:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses

    def get(self, path: str):
        if path not in self.responses:
            raise DockerCollectorError("fixture route is missing")
        return json.loads(json.dumps(self.responses[path]))

    def verify_unchanged(self) -> None:
        return


class RootlessDockerCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry(ROOT / "config/argus/observation-sources.json", ROOT)
        self.sources = [
            self.registry.sources["oreochiserver.personal-sandbox.rootless-docker"],
            self.registry.sources["oreochiserver.work-sandbox.rootless-docker"],
        ]
        fixture = ROOT / "tests/fixtures/docker/rootful-api-v1.40.json"
        self.responses = json.loads(fixture.read_text(encoding="utf-8"))["responses"]

    def test_personal_and_work_sources_pin_distinct_identities_and_sockets(self) -> None:
        self.assertEqual(
            [(1002, 981), (1003, 981)],
            [
                (source.execution_identity["uid"], source.execution_identity["gid"])
                for source in self.sources
            ],
        )
        self.assertNotEqual(
            self.sources[0].transport["socketPath"],
            self.sources[1].transport["socketPath"],
        )
        self.assertEqual([1002, 1003], [source.transport["socketUid"] for source in self.sources])
        self.assertEqual([1002, 1003], [source.transport["peerUid"] for source in self.sources])

    def test_each_source_preserves_bounded_running_and_stopped_records(self) -> None:
        for source in self.sources:
            request = collection_request(
                source,
                refresh_id="rootless-fixture",
                run_id=f"run-{source.trust_domain}",
                explicit_clock="2026-08-05T00:00:00Z",
            )
            records = collect_docker_records(source, request, FixtureClient(self.responses))
            self.assertEqual(2, sum(record["resourceKind"] == "container" for record in records))
            self.assertEqual(1, sum(
                record["resourceKind"] == "container" and record["attributes"]["lifecycle"] == "running"
                for record in records
            ))
            self.assertEqual(1, sum(
                record["resourceKind"] == "container" and record["attributes"]["lifecycle"] == "exited"
                for record in records
            ))
            pages = build_pages(source, request, records)
            validator = PageValidator(source, request)
            result = None
            for page in pages:
                result = validator.accept(page) or result
            validator.finish()
            self.assertIsNotNone(result)
            self.assertEqual("completed", result.state)

    def test_hostile_fixture_is_minimized_before_paging(self) -> None:
        source = self.sources[0]
        request = collection_request(
            source,
            refresh_id="rootless-hostile",
            run_id="rootless-hostile-run",
            explicit_clock="2026-08-05T00:00:00Z",
        )
        hostile = json.loads(json.dumps(self.responses))
        detail_path = next(path for path in hostile if "/containers/" in path and path.endswith("/json?size=0"))
        hostile[detail_path]["Config"]["Labels"]["secret"] = "must-not-export"
        records = collect_docker_records(source, request, FixtureClient(hostile))
        self.assertNotIn("must-not-export", json.dumps(records, sort_keys=True))

    def test_missing_daemon_is_a_source_specific_gap(self) -> None:
        source = self.sources[0]
        request = collection_request(
            source,
            refresh_id="rootless-gap",
            run_id="rootless-gap-run",
            explicit_clock="2026-08-05T00:00:00Z",
        )
        page = build_pages(source, request, [], state="failed", gap_code="docker-socket-unavailable")[0]
        validator = PageValidator(source, request)
        result = validator.accept(page)
        validator.finish()
        self.assertEqual("failed", result.state)
        self.assertEqual("docker-socket-unavailable", result.gap_code)

    def test_control_api_cannot_reach_either_workload_socket(self) -> None:
        unit = (ROOT / "systemd/argus-control-api.service").read_text(encoding="utf-8")
        self.assertIn("/var/lib/argus/personal-sandbox/docker.sock", unit)
        self.assertIn("/var/lib/argus/work-sandbox/docker.sock", unit)

    def test_installer_is_acknowledged_backed_up_and_workload_read_only(self) -> None:
        installer = (ROOT / "scripts/argus-d2b-rootless-docker-collector").read_text(encoding="utf-8")
        self.assertIn("--acknowledge-d2b-rootless-docker-collector", installer)
        self.assertIn("trap restore_on_failure EXIT", installer)
        for forbidden in ("docker stop", "docker restart", "docker rm", "docker compose", "cloudflared", "tailscale"):
            self.assertNotIn(forbidden, installer.casefold())

        unit = (ROOT / "systemd/argus-rootless-docker-collector@.service").read_text(encoding="utf-8")
        self.assertIn("User=argus-%i", unit)
        self.assertIn("Group=argus-control", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("PrivateNetwork=true", unit)
        self.assertIn("/var/run/docker.sock", unit)

    def test_collector_entrypoint_requires_source_specific_runtime_binding(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source = self.sources[0].as_registry_record()
            path = Path(directory) / "source.json"
            path.write_text(json.dumps({"schemaVersion": 2, "hostSources": [source["sourceId"]], "sources": [source]}))
            with mock.patch.dict(
                "os.environ",
                {
                    "ARGUS_SOURCE_ID": source["sourceId"],
                    "ARGUS_SOURCE_REGISTRY": str(path),
                    "ARGUS_SOURCE_CONFIG_GID": str(path.stat().st_gid),
                    "ARGUS_COLLECTOR_CLIENT_UID": "1000",
                    "ARGUS_COLLECTOR_CLIENT_GID": "981",
                    "ARGUS_DOCKER_SOCKET": "/missing/docker.sock",
                    "ARGUS_DOCKER_SOCKET_UID": "1002",
                    "ARGUS_DOCKER_SOCKET_GID": "232054",
                    "ARGUS_DOCKER_DAEMON_UID": "1002",
                    "ARGUS_DOCKER_DAEMON_GID": "1002",
                },
                clear=False,
            ), mock.patch("argus_rootless_docker_collector.signal.signal"), mock.patch(
                "argus_rootless_docker_collector.RootfulDockerCollectorServer.serve_forever",
                side_effect=DockerCollectorError("fixture-stop"),
            ):
                self.assertEqual(1, main())


if __name__ == "__main__":
    unittest.main()
