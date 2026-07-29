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
        self.assertIn("ARGUS_ISSUER_PUBLIC_KEY=/etc/argus/domains/%i/issuer.pub", unit)
        self.assertIn("RuntimeDirectory=argus/domains/%i", unit)
        self.assertNotIn("ARGUS_CAPABILITY_KEY_FILE", unit)

    def test_issuer_is_separate_read_only_and_has_no_runtime_socket(self) -> None:
        unit = (ROOT / "systemd" / "argus-capability-issuer.service").read_text()
        self.assertIn("User=argus-issuer", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("ReadOnlyPaths=/var/lib/argus/control", unit)
        self.assertIn("InaccessiblePaths=-/var/run/docker.sock -/run/docker.sock", unit)
        self.assertNotIn("DOCKER_HOST", unit)
        self.assertIn("/etc/argus/domains/work-sandbox/issuer.pub", unit)


if __name__ == "__main__":
    unittest.main()
