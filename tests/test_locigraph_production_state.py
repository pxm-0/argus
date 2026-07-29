from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LociGraphProductionStateTests(unittest.TestCase):
    def test_inventory_records_tailnet_only_sandbox_publication(self) -> None:
        workloads = json.loads((ROOT / "config" / "workloads.json").read_text())["workloads"]
        locigraph = next(item for item in workloads if item["id"] == "locigraph")
        self.assertEqual([], locigraph["network"]["observedBindings"])
        self.assertEqual("https://oreochiserver.tail0a3a58.ts.net/", locigraph["health"]["url"])
        self.assertEqual("migrated", locigraph["migration"]["status"])
        self.assertFalse(locigraph["actions"]["restart"])

    def test_manifest_records_restore_evidence_but_keeps_generic_actions_disabled(self) -> None:
        manifest = json.loads((ROOT / "workloads" / "locigraph" / "manifest.json").read_text())
        self.assertEqual("migrated", manifest["migration"]["status"])
        self.assertEqual("personal-sandbox", manifest["migration"]["targetTrustDomain"])
        self.assertEqual("ok", manifest["backup"]["status"])
        self.assertTrue(manifest["backup"]["restoreTested"])
        self.assertFalse(manifest["backup"]["backupAllowed"])
        self.assertFalse(manifest["operations"]["restartAllowed"])
        self.assertFalse(manifest["operations"]["backupAllowed"])
        notes = " ".join(manifest["security"]["notes"])
        self.assertIn("no host-published ports", notes)


if __name__ == "__main__":
    unittest.main()
