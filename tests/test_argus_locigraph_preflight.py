from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_locigraph_preflight import build_report  # noqa: E402


class LociGraphPreflightTests(unittest.TestCase):
    def test_report_redacts_values_and_blocks_current_legacy_shape(self) -> None:
        compose = {
            "name": "locigraph",
            "services": {
                "backend": {
                    "restart": "no",
                    "ports": [{"target": 8000, "published": "8000", "host_ip": "0.0.0.0", "protocol": "tcp"}],
                    "environment": {"OPENAI_API_KEY": "must-not-appear", "JWT_SECRET": "also-secret"},
                },
                "postgres": {
                    "ports": [{"target": 5432, "published": "15432", "protocol": "tcp"}],
                    "volumes": [{"type": "volume", "source": "locigraph_postgres_data", "target": "/var/lib/postgresql/data"}],
                },
            },
        }
        manifest = {"operations": {"restartAllowed": False}, "backup": {"backupAllowed": False, "restoreTested": False}}
        report = build_report(compose=compose, containers=[], manifest=manifest)
        serialized = str(report)
        self.assertNotIn("must-not-appear", serialized)
        self.assertNotIn("also-secret", serialized)
        self.assertEqual(["JWT_SECRET", "OPENAI_API_KEY"], report["services"][0]["environmentKeys"])
        self.assertFalse(report["safeForMigrationApply"])
        self.assertIn("wildcard-published-ports", report["findings"])
        self.assertIn("database-or-cache-host-published", report["findings"])

    def test_private_backed_up_persistent_shape_passes(self) -> None:
        compose = {
            "name": "locigraph",
            "services": {
                "frontend": {
                    "restart": "unless-stopped",
                    "ports": [{"target": 80, "published": 8090, "host_ip": "127.0.0.1"}],
                    "environment": {},
                },
                "postgres": {"restart": "unless-stopped", "ports": [], "environment": {}},
            },
        }
        manifest = {"operations": {"restartAllowed": True}, "backup": {"backupAllowed": True, "restoreTested": True}}
        report = build_report(compose=compose, containers=[], manifest=manifest)
        self.assertTrue(report["safeForMigrationApply"])
        self.assertEqual([], report["findings"])

    def test_running_source_blocks_apply(self) -> None:
        compose = {"services": {"frontend": {"restart": "unless-stopped", "ports": [], "environment": {}}}}
        manifest = {"operations": {"restartAllowed": True}, "backup": {"backupAllowed": True, "restoreTested": True}}
        report = build_report(compose=compose, containers=[{"service": "frontend", "running": True}], manifest=manifest)
        self.assertIn("source-not-stopped", report["findings"])


if __name__ == "__main__":
    unittest.main()
