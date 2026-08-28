from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_collector_deploy as deploy  # noqa: E402


class CollectorDeploymentPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = deploy.validate_registry(ROOT)

    def test_plan_covers_every_reviewed_source_once(self) -> None:
        self.assertEqual(deploy.expected_source_ids(), set(self.registry.sources))
        files = deploy.expected_files(ROOT, self.registry, live_bindings=False)
        projections = [
            item for item in files if item.path.suffix == ".json" and "collectors" in str(item.path)
        ]
        self.assertEqual(11, len(projections))
        projected_ids = set()
        for item in projections:
            payload = json.loads(item.content)
            self.assertEqual(1, len(payload["hostSources"]))
            self.assertEqual(payload["hostSources"], [payload["sources"][0]["sourceId"]])
            projected_ids.add(payload["hostSources"][0])
            self.assertEqual(0o640, item.mode)
            self.assertEqual(0, item.uid)
            self.assertEqual(deploy.CONTROL_GID, item.gid)
        self.assertEqual(deploy.expected_source_ids(), projected_ids)

    def test_rootless_environment_is_minimized_and_bound_to_the_source_identity(self) -> None:
        source = self.registry.sources["oreochiserver.personal-managed.rootless-docker"]
        environment = deploy.rootless_environment(source, socket_gid=1234, daemon_gid=1004).decode("ascii")
        self.assertEqual(
            "ARGUS_DOCKER_SOCKET_UID=1004\n"
            "ARGUS_DOCKER_SOCKET_GID=1234\n"
            "ARGUS_DOCKER_SOCKET_MODE=0660\n"
            "ARGUS_DOCKER_DAEMON_UID=1004\n"
            "ARGUS_DOCKER_DAEMON_GID=1004\n",
            environment,
        )
        self.assertNotIn("DOCKER_HOST", environment)
        self.assertNotIn("TOKEN", environment)

    def test_concrete_user_schedule_units_bind_the_real_user_accounts(self) -> None:
        expected = {
            "oreo": ("oreo", "1000"),
            "personal-sandbox": ("argus-personal-sandbox", "1002"),
            "work-sandbox": ("argus-work-sandbox", "1003"),
        }
        for name, (account, uid) in expected.items():
            content = (ROOT / "systemd" / f"argus-user-schedules-collector-{name}.service").read_text()
            self.assertIn(f"User={account}", content)
            self.assertIn(f"Environment=XDG_RUNTIME_DIR=/run/user/{uid}", content)
            self.assertIn(f"ARGUS_SOURCE_ID=oreochiserver.user-schedules-{name}", content)
            self.assertNotIn("User=%i", content)


if __name__ == "__main__":
    unittest.main()
