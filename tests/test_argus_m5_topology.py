from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m5_topology import build_topology  # noqa: E402


class M5TopologyTest(unittest.TestCase):
    def test_topology_keeps_legacy_visible_and_target_controls_closed(self) -> None:
        workloads = [
            {"id": "legacy-app", "name": "Legacy", "access": {"desired": "tailnet", "effective": "local"}, "routes": {}},
            {"id": "pilot", "name": "Pilot", "access": {"desired": "none", "effective": "none"}, "routes": {}},
        ]
        legacy = {"default": {"trustDomain": "legacy-rootful", "status": "legacy-unclassified", "admission": "denied"}, "workloads": {}}
        classified = {"workloads": {"pilot": {"trustDomain": "personal-sandbox", "realm": "personal", "zone": "sandbox", "stage": "none", "status": "classified", "admission": "allowed"}}}

        result = build_topology(workloads=workloads, legacy=legacy, classified=classified)
        nodes = {item["id"]: item for item in result["nodes"]}
        self.assertEqual("legacy-rootful", nodes["legacy-app"]["trustDomain"])
        self.assertTrue(nodes["legacy-app"]["drift"])
        self.assertEqual("domain-agent-required", nodes["pilot"]["controlMode"])
        self.assertTrue(result["readOnly"])
        self.assertEqual(1, result["summary"]["unresolvedClassifications"])

    def test_edges_have_explicit_allowlisted_meanings(self) -> None:
        result = build_topology(workloads=[], legacy={}, classified={})
        self.assertTrue(result["edges"])
        self.assertTrue(all(edge["meaning"] in result["edgeMeanings"] for edge in result["edges"]))


if __name__ == "__main__":
    unittest.main()
