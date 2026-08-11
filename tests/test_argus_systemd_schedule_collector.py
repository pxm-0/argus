from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_collectors import collection_request  # noqa: E402
from argus_observations import load_registry  # noqa: E402
from argus_systemd_schedule_collector import collect_records  # noqa: E402


class FixtureRunner:
    def __init__(self, *, services: list[dict[str, object]], timers: list[dict[str, str]], crontab: str):
        self.services = services
        self.timers = timers
        self.crontab = crontab

    def __call__(self, argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "list-unit-files" in argv:
            output = "\n".join(
                f"{item['unit']} {'enabled' if item['enabled'] else 'disabled'} static"
                for item in self.services
            ) + "\n"
            return subprocess.CompletedProcess(argv, 0, output.encode(), b"")
        if "list-units" in argv:
            output = "\n".join(
                f"{item['unit']} loaded {item['active']} {item['sub']} fixture"
                for item in self.services
            ) + "\n"
            return subprocess.CompletedProcess(argv, 0, output.encode(), b"")
        if "list-timers" in argv:
            output = "\n".join(
                f"n/a n/a n/a n/a {item['unit']} {item['activates']}"
                for item in self.timers
            ) + "\n"
            return subprocess.CompletedProcess(argv, 0, output.encode(), b"")
        if argv == ["crontab", "-l"]:
            if not self.crontab:
                return subprocess.CompletedProcess(argv, 1, b"", b"no crontab for fixture\n")
            return subprocess.CompletedProcess(argv, 0, self.crontab.encode(), b"")
        raise AssertionError(argv)


class SystemdScheduleCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry(ROOT / "config/argus/observation-sources.json", ROOT)

    def test_fixture_acceptance_is_three_run_and_secret_free(self) -> None:
        result = subprocess.run(
            [
                str(ROOT / "scripts/argus-d3-systemd-schedule-acceptance"),
                "--root", str(ROOT),
                "--source-revision", "c9f12d8",
                "--captured-at", "2026-08-11T00:00:00Z",
                "--target", "local-ci",
            ],
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")},
        )
        payload = json.loads(result.stdout)
        self.assertEqual(3, payload["expectedRuns"])
        self.assertEqual(["pass", "pass", "pass"], [item["result"] for item in payload["runs"]])
        self.assertNotIn("docker-compose", result.stdout + result.stderr)

    def test_system_and_user_records_expose_state_not_payload(self) -> None:
        source = self.registry.sources["oreochiserver.user-schedules-personal-sandbox"]
        request = collection_request(
            source,
            refresh_id="d3-test",
            run_id="d3-test-user",
            explicit_clock="2026-08-11T00:00:00Z",
        )
        records = collect_records(
            source,
            request,
            runner=FixtureRunner(
                services=[{
                    "unit": "argus-personal-sandbox-rootless-docker.service",
                    "active": "active",
                    "sub": "running",
                    "enabled": True,
                }],
                timers=[],
                crontab="@reboot docker compose -p legacy start\n",
            ),
        )
        encoded = json.dumps(records, sort_keys=True)
        self.assertIn("legacyReference", encoded)
        self.assertNotIn("docker compose", encoded)
        self.assertNotIn("@reboot", encoded)
        self.assertEqual(1, sum(item["resourceKind"] == "cron-entry" for item in records))

    def test_system_cron_directories_are_metadata_only(self) -> None:
        source = self.registry.sources["oreochiserver.system-schedules"]
        request = collection_request(
            source,
            refresh_id="d3-test-system",
            run_id="d3-test-system",
            explicit_clock="2026-08-11T00:00:00Z",
        )
        with tempfile.TemporaryDirectory(prefix="argus-d3-test-") as directory:
            root = Path(directory)
            cron_dir = root / "etc" / "cron.d"
            cron_dir.mkdir(parents=True)
            (cron_dir / "legacy-job").write_text("@reboot docker-compose start\n", encoding="utf-8")
            records = collect_records(
                source,
                request,
                runner=FixtureRunner(services=[], timers=[], crontab=""),
                root=root,
            )
        file_record = next(item for item in records if item["resourceKind"] == "cron-directory")
        self.assertTrue(file_record["attributes"]["legacyReference"])
        self.assertNotIn("docker-compose", json.dumps(records, sort_keys=True))

    def test_sources_pin_distinct_execution_and_socket_identities(self) -> None:
        d3_source_ids = (
            "oreochiserver.system-schedules",
            "oreochiserver.user-schedules-oreo",
            "oreochiserver.user-schedules-personal-sandbox",
            "oreochiserver.user-schedules-work-sandbox",
        )
        sources = [self.registry.sources[source_id] for source_id in d3_source_ids]
        self.assertEqual([(1000, 981), (1000, 981), (1002, 981), (1003, 981)], [
            (source.execution_identity["uid"], source.execution_identity["gid"])
            for source in sources
        ])
        self.assertEqual(4, len({source.transport["socketPath"] for source in sources}))

    def test_units_keep_read_only_private_network_boundary(self) -> None:
        for name in (
            "systemd/argus-system-schedules-collector.service",
            "systemd/argus-user-schedules-collector@.service",
        ):
            unit = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("PrivateNetwork=true", unit)
            self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
            self.assertIn("NoNewPrivileges=true", unit)
            self.assertNotIn("ReadOnlyPaths=/var/run/docker.sock", unit)


if __name__ == "__main__":
    unittest.main()
