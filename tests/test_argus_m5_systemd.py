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


if __name__ == "__main__":
    unittest.main()
