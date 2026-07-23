from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LociGraphProductionStateTests(unittest.TestCase):
    def test_inventory_records_only_loopback_caddy_publication(self) -> None:
        workloads = json.loads((ROOT / "config" / "workloads.json").read_text())["workloads"]
        locigraph = next(item for item in workloads if item["id"] == "locigraph")
        self.assertEqual(["127.0.0.1:8090->80/tcp"], locigraph["network"]["observedBindings"])
        self.assertEqual("planned", locigraph["migration"]["status"])
        self.assertFalse(locigraph["actions"]["restart"])

    def test_manifest_records_restore_evidence_but_keeps_generic_actions_disabled(self) -> None:
        manifest = json.loads((ROOT / "workloads" / "locigraph" / "manifest.json").read_text())
        self.assertEqual("external", manifest["migration"]["status"])
        self.assertEqual("ok", manifest["backup"]["status"])
        self.assertTrue(manifest["backup"]["restoreTested"])
        self.assertFalse(manifest["backup"]["backupAllowed"])
        self.assertFalse(manifest["operations"]["restartAllowed"])
        self.assertFalse(manifest["operations"]["backupAllowed"])
        notes = " ".join(manifest["security"]["notes"])
        self.assertIn("127.0.0.1:8090", notes)
        self.assertIn("no host-published ports", notes)


if __name__ == "__main__":
    unittest.main()
