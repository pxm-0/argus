from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkloadDispositionTests(unittest.TestCase):
    def test_retired_workloads_are_absent_from_active_state(self) -> None:
        retired = {"uptime-kuma", "dozzle", "review-ui", "publication-archive-live"}
        workloads = {
            item["id"]
            for item in json.loads((ROOT / "config" / "workloads.json").read_text())["workloads"]
        }
        access = set(json.loads((ROOT / "config" / "access.json").read_text())["workloads"])
        privacy = set(json.loads((ROOT / "config" / "privacy.json").read_text())["workloads"])
        routes = set(json.loads((ROOT / "config" / "routes.json").read_text())["workloadRoutes"])
        legacy = set(
            json.loads(
                (ROOT / "config" / "argus" / "legacy-classification.json").read_text()
            )["workloads"]
        )
        manifests = {path.parent.name for path in (ROOT / "workloads").glob("*/manifest.json")}

        for active_set in (workloads, access, privacy, routes, legacy, manifests):
            self.assertFalse(retired & active_set)

    def test_retained_workloads_have_fail_closed_destination_plans(self) -> None:
        destinations = {
            "hastur": "personal-sandbox",
            "kadath": "personal-sandbox",
            "nodens": "personal-sandbox",
            "locigraph": "personal-sandbox",
            "intake-os": "work-sandbox",
        }
        expected_projects = {
            "hastur": "hastur",
            "kadath": "kadath-live",
            "nodens": "nodens",
            "locigraph": "locigraph",
            "intake-os": "intake-os",
        }
        admitted = json.loads(
            (ROOT / "config" / "argus" / "workload-classification.json").read_text()
        )["workloads"]
        inventory = {
            item["id"]: item
            for item in json.loads((ROOT / "config" / "workloads.json").read_text())[
                "workloads"
            ]
        }
        for workload_id, destination in destinations.items():
            manifest = json.loads(
                (ROOT / "workloads" / workload_id / "manifest.json").read_text()
            )
            self.assertEqual(destination, manifest["migration"]["targetTrustDomain"])
            self.assertEqual(
                expected_projects[workload_id],
                manifest["runtime"]["composeProject"],
            )
            self.assertEqual(
                expected_projects[workload_id],
                inventory[workload_id]["runtime"]["composeProject"],
            )
            self.assertEqual("planned", inventory[workload_id]["migration"]["status"])
            self.assertNotIn(workload_id, admitted)


if __name__ == "__main__":
    unittest.main()
