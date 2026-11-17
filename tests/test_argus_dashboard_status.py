from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "control-plane" / "dashboard"
sys.path.insert(0, str(DASHBOARD))
sys.path.insert(0, str(ROOT / "scripts"))

from generate_dashboard import JS, render_html  # noqa: E402
from m5_style import M5_CSS  # noqa: E402

STATUS = (DASHBOARD / "assets" / "status.js").read_text()


def run_status(expression: str) -> object:
    script = STATUS + f"\nconsole.log(JSON.stringify({expression}));"
    return json.loads(subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True).stdout)


def js_function(name: str) -> str:
    start = JS.index(f"function {name}(")
    return JS[start:JS.index("\n}\n", start) + 3]


def run_js(script: str) -> object:
    return json.loads(subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "requires node")
class StatusPresentationTests(unittest.TestCase):
    def test_exceptions_count_paging_alerts_down_workloads_missing_agents_and_bad_evidence(self) -> None:
        state = {
            "alerts": {"available": True, "alerts": [
                {"severity": "page", "id": "disk"}, {"severity": "critical", "id": "x"}, {"severity": "warn", "id": "backup"},
            ]},
            "workloads": [{"id": "a", "health": {"ok": False}}, {"id": "b", "health": {"ok": True}}, {"id": "c", "health": {}}],
            "topology": {"summary": {"accessDrift": 1, "unresolvedClassifications": 0, "domainAgentsAvailable": 0}},
        }
        reasons = run_status(f"exceptionReasons({json.dumps(state)}, 'conflict')")
        self.assertEqual(
            ["2 paging alerts", "1 workload down", "1 access drift", "1 no domain agent available", "1 evidence conflict"],
            [item["text"] for item in reasons],
        )
        self.assertEqual(6, sum(item["count"] for item in reasons))
        for evidence in ("empty", "error"):
            self.assertEqual(1, len(run_status(f"exceptionReasons({{workloads: []}}, '{evidence}')")))

    def test_clean_estate_has_no_exceptions(self) -> None:
        state = {"alerts": {"alerts": [{"severity": "warn"}]}, "workloads": [{"health": {"ok": True}}],
                 "topology": {"summary": {"domainAgentsAvailable": 1}}}
        self.assertEqual([], run_status(f"exceptionReasons({json.dumps(state)}, 'complete')"))
        self.assertEqual([], run_status("exceptionReasons(null, 'loading')"))

    def test_health_labels_follow_design_contract_with_distinct_tones(self) -> None:
        out = run_status("[{ok: true}, {ok: false}, {enabled: true}, {}].map((h) => healthPresentation(h))")
        self.assertEqual(["Healthy", "Down", "Unknown", "Unknown"], [item["label"] for item in out])
        self.assertEqual(["good", "bad", "warn", "warn"], [item["tone"] for item in out])
        self.assertEqual("Check configured, not yet observed", out[2]["detail"])
        self.assertGreater(out[1]["rank"], out[2]["rank"])
        design = (DASHBOARD / "DESIGN.md").read_text()
        self.assertIn("| Health | Healthy, Degraded, Down, Unknown |", design)

    def test_freshness_labels_age_and_stale_threshold(self) -> None:
        now = "Date.parse('2026-11-11T12:00:00Z')"
        out = run_status(
            f"[freshnessPresentation('2026-11-11T11:50:00Z', HEALTH_STALE_SECONDS, {now}),"
            f" freshnessPresentation('2026-11-11T11:40:00Z', HEALTH_STALE_SECONDS, {now}),"
            f" freshnessPresentation('2026-07-30T12:00:00Z', HEALTH_STALE_SECONDS, {now}),"
            f" freshnessPresentation('', HEALTH_STALE_SECONDS, {now}),"
            f" freshnessPresentation('2026-11-11T11:58:00Z', STATE_STALE_SECONDS, {now})]"
        )
        self.assertEqual(["Fresh", "Stale", "Stale", "Never observed", "Stale"], [item["label"] for item in out])
        self.assertEqual(["10m old", "20m old", "104d old"], [item["age"] for item in out[:3]])
        self.assertEqual(["good", "warn", "warn", "warn", "warn"], [item["tone"] for item in out])
        self.assertEqual([30, 90, 900], run_status("[STATE_POLL_SECONDS, STATE_STALE_SECONDS, HEALTH_STALE_SECONDS]"))


@unittest.skipUnless(shutil.which("node"), "requires node")
class StateRefreshBehaviourTests(unittest.TestCase):
    def test_focus_or_open_details_inside_main_pauses_refresh(self) -> None:
        script = """
let adminEnabled = false;
const location = { hash: "" };
const main = {};
const button = { closest: (selector) => selector === "main" ? main : null };
const body = { closest: () => null };
let openDetails = null;
const document = { activeElement: button, body, querySelectorAll: () => [], querySelector: (selector) => selector === "main details[open]" ? openDetails : null };
""" + js_function("stateRefreshPaused") + """
const out = [stateRefreshPaused()];
document.activeElement = body;
out.push(stateRefreshPaused());
openDetails = {};
out.push(stateRefreshPaused());
console.log(JSON.stringify(out));
"""
        self.assertEqual([True, False, True], run_js(script))

    def test_unchanged_alert_banner_is_not_rewritten(self) -> None:
        script = """
let writes = 0;
let html = "";
const alertBanner = { dataset: {}, set innerHTML(value) { writes += 1; html = value; }, get innerHTML() { return html; } };
let state = { alerts: { available: true, alerts: [{ severity: "page", id: "disk", detail: "full" }] } };
const liveRegionMarkup = new WeakMap();
""" + js_function("escapeHtml") + js_function("setLiveRegionHTML") + js_function("renderAlertBanner") + """
renderAlertBanner();
renderAlertBanner();
const unchanged = writes;
state = { alerts: { available: true, alerts: [] } };
renderAlertBanner();
console.log(JSON.stringify([unchanged, writes]));
"""
        self.assertEqual([1, 2], run_js(script))
        self.assertNotIn("alertBanner.innerHTML =", JS)
        self.assertNotIn("evidenceStateBodyEl.innerHTML =", JS)
        self.assertIn("setLiveRegionHTML(evidenceStateBodyEl,", JS)


class GeneratedDashboardStatusTests(unittest.TestCase):
    def test_status_helpers_are_bundled_and_drive_summary_and_rows(self) -> None:
        self.assertIn("function exceptionReasons", JS)
        self.assertNotIn("@include status.js", JS)
        for marker in (
            "exceptionReasons(state, reconciliationState(state?.reconciliation))",
            "healthPresentation(health)",
            "freshnessPresentation(healthEvidenceAt, HEALTH_STALE_SECONDS)",
            'data-health="${escapeHtml(healthState.label.toLowerCase())}"',
        ):
            self.assertIn(marker, JS)
        self.assertNotIn('"Unhealthy"', JS)
        self.assertNotIn('"Configured"', JS)
        self.assertNotIn("const exceptions = Number(topologySummary.accessDrift", JS)

    def test_state_age_is_prominent_and_state_auto_refreshes(self) -> None:
        html = render_html()
        self.assertIn('id="state-age"', html)
        self.assertLess(html.index('id="state-age"'), html.index('id="route-summary"') + 200)
        self.assertIn("state?.generatedAt", JS)
        self.assertIn("freshnessPresentation(generatedAt, STATE_STALE_SECONDS)", JS)
        self.assertIn("async function pollDashboardState()", JS)
        self.assertIn("STATE_POLL_SECONDS * 1000", JS)
        self.assertIn("Auto-refresh paused", JS)
        self.assertIn("void pollDashboardState();", JS)

    def test_state_age_recomputes_without_a_finished_fetch(self) -> None:
        load = js_function("loadDashboardState")
        self.assertEqual(2, load.count("signal: AbortSignal.timeout(STATE_FETCH_TIMEOUT_MS)"))
        self.assertIn("setInterval(renderStateAge,", JS)
        self.assertIn('document.addEventListener("visibilitychange"', JS)

    def test_failed_state_load_is_explicit_and_retryable(self) -> None:
        html = render_html()
        self.assertRegex(html, r'id="state-alert"[^>]*role="alert"')
        self.assertIn('id="state-retry"', html)
        self.assertIn('stateRetry.addEventListener("click"', JS)
        self.assertIn("function renderStateUnavailable()", JS)
        catch_block = JS[JS.index("async function loadDashboardState"):JS.index("async function operationStatus")]
        self.assertNotIn("error.message", catch_block.split("catch (error)")[1])
        self.assertNotIn("`dashboard state ${response.status}`", JS)
        unavailable = JS[JS.index("function renderStateUnavailable"):JS.index("async function loadDashboardState")]
        for target in ("alertBanner", "exposureAlert", "#access-plan p", "#backup-plan p", "#cloudflare-plan p", "#system-plan p", "stages", "topologyEl", "workloadsEl", "summaryEl"):
            self.assertIn(target, unavailable)

    def test_empty_states_for_workloads_and_activity(self) -> None:
        self.assertIn("No workloads registered", JS)
        self.assertIn("Sign in to view recent operations.", JS)
        self.assertNotIn("Authenticate to load activity.", JS)

    def test_good_tone_uses_success_colour_everywhere(self) -> None:
        for selector in (".pill.good", ".history-state.good", ".result-badge.good", ".state-badge.good", ".tone-good"):
            match = re.search(re.escape(selector) + r"\s*\{\s*color:var\(--(\w+)\)", M5_CSS)
            self.assertIsNotNone(match, selector)
            self.assertEqual("green", match.group(1), selector)
        self.assertRegex(M5_CSS, r'\.workload\[data-health="down"\]')


class DashboardStateTimestampTests(unittest.TestCase):
    def test_dashboard_state_reports_generated_at(self) -> None:
        import argus_common

        with mock.patch.dict(os.environ, {"ARGUS_ROOT": str(ROOT)}), mock.patch.object(argus_common, "recent_events", return_value=[]):
            state = argus_common.dashboard_state()
        self.assertRegex(state["generatedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
