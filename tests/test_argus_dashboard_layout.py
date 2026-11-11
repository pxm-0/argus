from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "control-plane" / "dashboard"
sys.path.insert(0, str(DASHBOARD))

import generate_dashboard  # noqa: E402
from generate_dashboard import JS, render_html  # noqa: E402
from m5_style import M5_CSS  # noqa: E402


def js_block(start: str, end: str) -> str:
    return JS[JS.index(start):JS.index(end)]


def run_node(script: str) -> object:
    completed = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
    return json.loads(completed.stdout)


class DashboardLayoutTests(unittest.TestCase):
    def test_evidence_gate_body_carries_its_layout_class(self) -> None:
        self.assertIn('<div id="evidence-state-body" class="evidence-state-body">', render_html())

    def test_inspector_opens_the_workload_route_not_the_first_data_workload_match(self) -> None:
        handler = js_block('const focus = event.target.closest("[data-focus-workload]");', "const resumeApproval")
        self.assertIn("location.hash = `#/workloads/${encodeURIComponent(selectedTopologyId)}`", handler)
        self.assertNotIn('querySelector(`[data-workload=', handler)
        self.assertIn('.workload[data-workload="${CSS.escape(selectedTopologyId)}"]', handler)

    def test_sticky_topbar_offsets_anchor_targets_and_the_operation_banner(self) -> None:
        self.assertIn("scroll-margin-top:calc(var(--topbar-h,72px) + 12px)", M5_CSS)
        self.assertIn(".active-banner { position:sticky; top:var(--topbar-h,72px);", M5_CSS)
        self.assertIn('setProperty("--topbar-h"', JS)

    def test_coverage_matrix_stacks_its_inspector_below_wide_desktop(self) -> None:
        self.assertNotIn("minmax(600px,1fr) 320px", M5_CSS)
        self.assertIn("@media(max-width:1380px){.workloads{grid-template-columns:1fr}.topology{grid-template-columns:minmax(0,1fr)}", M5_CSS)

    def test_session_explanation_wraps_instead_of_truncating(self) -> None:
        rule = re.search(r"\.session-copy small \{[^}]*\}", M5_CSS).group(0)
        self.assertNotIn("ellipsis", rule)
        self.assertNotIn("nowrap", rule)
        self.assertIn("white-space:nowrap", re.search(r"\.session-copy strong \{[^}]*\}", M5_CSS).group(0))

    def test_disabled_buttons_are_visibly_distinct_and_ignore_hover(self) -> None:
        self.assertIn("button:disabled,.action.disabled { color:var(--muted); border-style:dashed;", M5_CSS)
        self.assertIn("button:disabled:hover", M5_CSS)

    def test_missing_reconciliation_badge_keeps_pill_size(self) -> None:
        self.assertIn(".workload-reconciliation>.state-badge { justify-self:start; align-self:start; }", M5_CSS)

    def test_navigation_credential_and_text_size_accessibility(self) -> None:
        html = render_html()
        self.assertRegex(html, r'<input id="admin-token"[^>]*aria-label="Bootstrap credential"')
        self.assertIn("function syncNavCurrent()", JS)
        self.assertIn('link.setAttribute("aria-current", "page")', JS)
        self.assertIn('window.addEventListener("scroll", ', JS)
        small = [int(size) for size in re.findall(r"font(?:-size)?:(\d+)px", M5_CSS) if int(size) < 12]
        self.assertEqual([], small)

    @unittest.skipUnless(shutil.which("node"), "requires node")
    def test_loading_reconciliation_renders_loading_and_actions_follow_prototypes(self) -> None:
        script = (
            js_block("const EVIDENCE_PRESENTATIONS", "function safeEvidenceToken")
            + js_block("function reconciliationState", "function renderEvidenceState")
            + "console.log(JSON.stringify({ loading: reconciliationState({ status: 'loading', coverage: { status: 'not-configured' } }),"
            " empty: reconciliationState({ status: 'empty' }), actions: Object.fromEntries(Object.entries(EVIDENCE_PRESENTATIONS).map(([k, v]) => [k, v.action])) }));"
        )
        out = run_node(script)
        self.assertEqual("loading", out["loading"])
        self.assertEqual("empty", out["empty"])
        prototypes = json.loads((DASHBOARD / "prototypes" / "states.json").read_text())["states"]
        expected = {("complete" if s["id"] == "success" else s["id"]): s["action"] for s in prototypes}
        expected["loading"] = None  # prototype: "No action yet"
        self.assertEqual(expected, out["actions"])
        self.assertIn("data-evidence-refresh", JS)
        self.assertIn("workloadDiscoverButton.click()", JS)

    @unittest.skipUnless(shutil.which("node"), "requires node")
    def test_stage_actions_are_disabled_with_a_reason_without_session_or_pin(self) -> None:
        stages = (DASHBOARD / "assets" / "stages.js").read_text()
        pin = "sha256:" + "a" * 64
        harness = r"""
        const target = { innerHTML: "" };
        const document = { getElementById: () => target };
        const escapeHtml = String; const operationTime = String; const composePinDigest = () => "";
        let csrfToken = ""; let state = null;
        """ + stages + r"""
        const render = (token, stagingPin, prodPin) => {
          csrfToken = token;
          state = { workloads: [{ id: "a-staging", runtime: { pinnedImage: stagingPin } }, { id: "a-production", runtime: { pinnedImage: prodPin } }] };
          renderStages();
          const html = target.innerHTML;
          return { promote: /data-stage-action="promote"[^>]*disabled/.test(html), rollback: /data-stage-action="rollback"[^>]*disabled/.test(html), input: /data-stage-confirm="a"[^>]*disabled/.test(html), html };
        };
        console.log(JSON.stringify({ anon: render("", "PIN", "PIN"), nopin: render("t", "", ""), ok: render("t", "PIN", "PIN"),
          prodOnly: render("t", "", "PIN"), stagingOnly: render("t", "PIN", "") }));
        """.replace("PIN", pin)
        out = run_node(harness)
        self.assertTrue(out["anon"]["promote"] and out["anon"]["rollback"])
        self.assertIn("Sign in to promote or roll back", out["anon"]["html"])
        self.assertTrue(out["nopin"]["promote"] and out["nopin"]["rollback"])
        self.assertIn("No pinned image", out["nopin"]["html"])
        self.assertFalse(out["ok"]["promote"] or out["ok"]["rollback"])
        self.assertIn("aria-describedby=", out["anon"]["html"])
        self.assertTrue(out["nopin"]["input"])
        # Rollback acts on production only, so an unpinned staging must not block it (and vice versa).
        self.assertEqual((True, False, False), (out["prodOnly"]["promote"], out["prodOnly"]["rollback"], out["prodOnly"]["input"]))
        self.assertIn("No pinned staging image to promote", out["prodOnly"]["html"])
        self.assertEqual((False, True, False), (out["stagingOnly"]["promote"], out["stagingOnly"]["rollback"], out["stagingOnly"]["input"]))
        self.assertIn("No pinned production image to roll back", out["stagingOnly"]["html"])


    def test_include_splice_fails_loudly_when_a_marker_is_missing(self) -> None:
        self.assertNotIn("// @include", JS)
        with self.assertRaisesRegex(RuntimeError, "operations.js"):
            generate_dashboard.splice_include("no marker here\n", "operations.js")

    def test_terminal_states_are_declared_once(self) -> None:
        literal = '"succeeded", "failed", "denied", "expired", "indeterminate", "rolled-back"'
        self.assertEqual(1, JS.count(literal))
        self.assertGreaterEqual(JS.count("TERMINAL_STATES.includes("), 4)


if __name__ == "__main__":
    unittest.main()
