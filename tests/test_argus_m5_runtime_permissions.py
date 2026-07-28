from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimePermissionContractTests(unittest.TestCase):
    def test_reconciler_is_narrow_and_secret_safe(self) -> None:
        script = (ROOT / "scripts" / "argus-m5-runtime-permissions").read_text()
        self.assertIn("operations.sqlite3", script)
        self.assertIn('CONTROL_STATE="/var/lib/argus/control"', script)
        self.assertIn("session.sqlite3", script)
        self.assertIn('M1_RUNTIME="$ROOT/runtime/argus/m1"', script)
        self.assertIn('ACCESS_CONFIG="$CONFIG_DIR/access.json"', script)
        self.assertIn('AUDIT_DATABASE="$ROOT/runtime/argus/audit.sqlite3"', script)
        self.assertIn('DASHBOARD_PUBLIC="$ROOT/control-plane/dashboard/public"', script)
        self.assertIn('WORKER_USER="argus-worker"', script)
        self.assertIn('$CONTROL_STATE/operations.sqlite3', script)
        self.assertIn("install -d -m 2770", script)
        self.assertIn("install -d -m 2775", script)
        self.assertIn("chmod 0660", script)
        self.assertIn("chmod 0664", script)
        self.assertIn("chmod 0600", script)
        self.assertIn('CONTROL_GROUP="argus-control"', script)
        self.assertNotIn("cat ", script)
        self.assertNotIn("control-token", script)
        self.assertNotIn("domain-keys", script)


if __name__ == "__main__":
    unittest.main()
