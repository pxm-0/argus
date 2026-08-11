from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "control-plane" / "dashboard"
sys.path.insert(0, str(DASHBOARD))
sys.path.insert(0, str(ROOT / "scripts"))

from argus_acceptance import validate  # noqa: E402
from generate_dashboard import JS, render_html  # noqa: E402
from m5_style import M5_CSS  # noqa: E402


class D6DashboardCompletenessTests(unittest.TestCase):
    def test_fixture_covers_exact_sanitized_evidence_states(self) -> None:
        fixture = json.loads((ROOT / "tests/fixtures/dashboard/d6-reconciliation.json").read_text())
        self.assertEqual(
            {"loading", "empty", "error", "partial", "stale", "conflict", "complete"},
            {state["id"] for state in fixture["states"]},
        )
        serialized = json.dumps(fixture).lower()
        for marker in ("/srv/", "/home/", "docker compose", "token=", "https://", "attributes"):
            self.assertNotIn(marker, serialized)
        for state in fixture["states"]:
            summary = state["summary"]
            self.assertEqual("none", summary["mutationAuthority"])
            self.assertIn("safeToMoveWorkloads", summary)

    def test_dashboard_renders_explicit_states_and_read_only_coverage(self) -> None:
        html = render_html()
        for marker in ('id="evidence-state"', 'id="evidence-state-label"', 'id="evidence-state-body"'):
            self.assertIn(marker, html)
        for label in ("Loading", "Empty", "Error", "Partial", "Stale", "Conflict", "Complete"):
            self.assertIn(f'label: "{label}"', JS)
        for marker in ("reconciliationState", "renderEvidenceState", "renderWorkloadReconciliation", "reconciliationBlockerLabel", "Mutation authority", "Review coverage", "escapeHtml"):
            self.assertIn(marker, JS)
        self.assertEqual(1, html.count('class="primary-action"'))
        self.assertIn('href="#estate-coverage"', JS)
        self.assertIn("source ${safeEvidenceToken", JS)
        self.assertIn("workload ${safeEvidenceToken", JS)
        self.assertNotIn('href="/public', html)
        self.assertIn("button,.action { min-height:44px", M5_CSS)
        self.assertIn(".evidence-state-body", M5_CSS)
        self.assertIn("@media(max-width:760px)", M5_CSS)

    def test_acceptance_emits_the_allowlisted_three_run_summary(self) -> None:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
        completed = subprocess.run(
            [str(ROOT / "scripts/argus-d6-dashboard-acceptance"), "--root", str(ROOT), "--source-revision", revision, "--captured-at", "2026-08-11T03:45:00Z", "--target", "local-ci"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        summary = validate(json.loads(completed.stdout))
        self.assertEqual("pass", summary["result"])
        self.assertEqual(3, len(summary["runs"]))


if __name__ == "__main__":
    unittest.main()
