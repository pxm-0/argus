from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimePermissionContractTests(unittest.TestCase):
    def test_reconciler_is_narrow_and_secret_safe(self) -> None:
        script = (ROOT / "scripts" / "argus-m5-runtime-permissions").read_text()
        self.assertIn("operations.sqlite3 sessions.sqlite3", script)
        self.assertIn("chmod 0660", script)
        self.assertIn('CONTROL_GROUP="argus-control"', script)
        self.assertNotIn("cat ", script)
        self.assertNotIn("control-token", script)
        self.assertNotIn("domain-keys", script)


if __name__ == "__main__":
    unittest.main()
