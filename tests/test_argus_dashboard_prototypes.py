from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "control-plane" / "dashboard"


class DashboardPrototypeTests(unittest.TestCase):
    def test_fixture_covers_required_surfaces_states_and_widths_without_schema_claim(self) -> None:
        fixture = json.loads((DASHBOARD / "prototypes" / "states.json").read_text())
        self.assertIn("not an API or repository schema", fixture["notice"])
        self.assertEqual(
            {"loading", "empty", "error", "partial", "stale", "conflict", "success"},
            {state["id"] for state in fixture["states"]},
        )
        self.assertEqual(
            {"overview", "workload-detail", "estate-coverage"},
            {surface["id"] for surface in fixture["surfaces"]},
        )
        self.assertEqual([320, 375, 768, 1024, 1440], fixture["viewports"])
        for state in fixture["states"]:
            self.assertTrue(state["headline"])
            self.assertTrue(state["detail"])
            self.assertTrue(state["action"])

    def test_routine_dashboard_has_one_primary_action_and_route_backed_detail(self) -> None:
        source = (DASHBOARD / "generate_dashboard.py").read_text()
        css = (DASHBOARD / "m5_style.py").read_text()
        self.assertEqual(1, source.count('class="primary-action"'))
        self.assertIn("Refresh estate", source)
        self.assertIn('href="#/workloads/${encodeURIComponent(id)}"', source)
        self.assertIn('window.addEventListener("hashchange", syncWorkloadRoute)', source)
        self.assertIn('routeSummary.textContent = "Invalid workload route"', source)
        self.assertIn("More operations", source)
        self.assertLess(source.index("id=\"workloads-heading\""), source.index("id=\"estate-coverage\""))
        self.assertIn("button,.action { min-height:44px", css)
        self.assertIn(".matrix-stage{display:none}", css)
        self.assertNotIn("CSS = r", source)


if __name__ == "__main__":
    unittest.main()
