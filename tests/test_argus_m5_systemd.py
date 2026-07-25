from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhaseOneSystemdTests(unittest.TestCase):
    def test_control_api_uses_only_declared_runtime_group(self) -> None:
        unit = (ROOT / "systemd" / "argus-control-api.service").read_text()
        self.assertIn("User=oreo", unit)
        self.assertIn("Group=argus-control", unit)
        self.assertNotIn("SupplementaryGroups=argus", unit)

    def test_nonlegacy_agent_has_accessible_domain_local_cli_home(self) -> None:
        unit = (ROOT / "systemd" / "argus-domain-agent@.service").read_text()
        self.assertIn("Environment=HOME=/var/lib/argus/%i", unit)
        self.assertIn("ProtectHome=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("InaccessiblePaths=-/var/run/docker.sock -/run/docker.sock", unit)
        self.assertNotIn("ReadWritePaths=/var/lib/argus", unit)


if __name__ == "__main__":
    unittest.main()
