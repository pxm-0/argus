from __future__ import annotations

import json
import shutil
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
        self.assertIn('apiPost("/api/estate/refresh", {})', JS)
        self.assertIn("pollEstateRefresh", JS)
        self.assertIn("/api/estate/refresh/${encodeURIComponent(runId)}", JS)
        for marker in (
            "/migration/preview",
            "data-migration-create",
            "migrationStatus",
            "pollMigration",
            "/api/workloads/${encodeURIComponent(workload)}/migrations",
            "/api/migrations/${encodeURIComponent(created.payload.migrationId)}/approve",
        ):
            self.assertIn(marker, JS)
        self.assertEqual(1, html.count('class="primary-action"'))
        self.assertIn('href="#estate-coverage"', JS)
        self.assertIn("source ${safeEvidenceToken", JS)
        self.assertIn("workload ${safeEvidenceToken", JS)
        self.assertNotIn('href="/public', html)
        self.assertIn("button,.action { min-height:44px", M5_CSS)
        self.assertIn(".evidence-state-body", M5_CSS)
        self.assertIn("@media(max-width:760px)", M5_CSS)

    def test_lifecycle_row_is_gated_and_actions_are_table_driven(self) -> None:
        for marker in (
            'data-operation="deploy-apply"',
            'data-operation="start-apply"',
            'data-operation="stop-apply"',
            "data-target-revision=",
            "deployAllowed && deployPin && agentAvailable",
            "startAllowed && agentAvailable",
            "stopAllowed && agentAvailable",
            "Deploy: no immutable image pin",
            "resolveOperation(action)",
        ):
            self.assertIn(marker, JS)
        self.assertNotIn('action.startsWith("restart")', JS)

    @unittest.skipUnless(shutil.which("node"), "requires node")
    def test_runtime_operation_sequence_and_unknown_action(self) -> None:
        harness = r"""
        const calls = [];
        const results = [];
        let confirmPhrase = "deploy demo sha256:" + "a".repeat(64);
        async function apiPost(url, body) {
          calls.push(["post", url, body]);
          if (url.endsWith("/operations/preview")) return { ok: true, payload: { allowed: true, previewDigest: "d", expectedRevision: "r", policyVersion: "p", confirmationPhrase: confirmPhrase } };
          if (url.endsWith("/operations")) return { ok: true, payload: { operation_id: "op1" } };
          return { ok: true, payload: { state: "queued" } };
        }
        async function ensureStepUp() { calls.push(["stepup"]); return true; }
        function pollOperation(id, workload) { calls.push(["poll", id, workload]); }
        function showCommandResult(title, payload) { results.push([title, payload]); }
        __OPS__
        (async () => {
          const deploy = resolveOperation("deploy-apply");
          const parameters = deploy.parameters({ targetRevision: "sha256:" + "a".repeat(64) });
          const base = { workload: "demo", operationType: deploy.operationType, parameters, stepUp: true };
          const first = await runOperation({ ...base, confirm: "" });
          const afterFirst = calls.map((c) => c[0] + ":" + (c[1] || ""));
          const second = await runOperation({ ...base, confirm: confirmPhrase });
          let unknown = "";
          try { resolveOperation("restore-apply"); } catch (error) { unknown = error.message; }
          let proto = "";
          try { resolveOperation("constructor"); } catch (error) { proto = error.message; }
          console.log(JSON.stringify({ first: first.stage, second: second.stage, afterFirst, calls, unknown, proto,
            pin: composePinDigest({ image: "repo/x@sha256:" + "b".repeat(64) }), noPin: composePinDigest({}),
            stop: resolveOperation("stop-apply").operationType, start: resolveOperation("start-apply").operationType, deployType: deploy.operationType }));
        })();
        """
        ops = (ROOT / "control-plane" / "dashboard" / "assets" / "operations.js").read_text()
        completed = subprocess.run(
            ["node", "-e", harness.replace("__OPS__", ops)],
            text=True, capture_output=True, check=True,
        )
        out = json.loads(completed.stdout)
        self.assertEqual("confirm", out["first"])
        self.assertEqual(["post:/api/workloads/demo/operations/preview"], out["afterFirst"])
        self.assertEqual("approved", out["second"])
        sequence = [c[0] if c[0] != "post" else c[1].rsplit("/", 1)[-1] for c in out["calls"]]
        self.assertEqual(["preview", "preview", "stepup", "operations", "approve", "poll"], sequence)
        created = out["calls"][3][2]
        self.assertEqual({"targetRevision": "sha256:" + "a" * 64}, created["parameters"])
        self.assertEqual(("workload.deploy", "d", "r", "p"), (created["operationType"], created["previewDigest"], created["expectedRevision"], created["policyVersion"]))
        self.assertEqual({"confirmation": "deploy demo sha256:" + "a" * 64}, out["calls"][4][2])
        self.assertIn("Unknown operation action", out["unknown"])
        self.assertIn("Unknown operation action", out["proto"])
        self.assertEqual("sha256:" + "b" * 64, out["pin"])
        self.assertEqual("", out["noPin"])
        self.assertEqual(("workload.stop", "workload.start"), (out["stop"], out["start"]))

    def test_stages_activity_banner_and_stage_actions_are_present(self) -> None:
        html = render_html()
        for marker in ('id="stages"', 'id="activity"', 'id="active-operation" class="active-banner" role="status"', '<ol id="events"'):
            self.assertIn(marker, html)
        self.assertLess(html.index('id="stages"'), html.index('id="workloads"'))
        self.assertNotIn('<pre id="events"', html)
        for marker in (
            "<table", 'scope="col"', 'scope="row"', "out of sync", "/api/operations?limit=25",
            "updateActiveOperation(operation, workload)",
            'data-stage-action="promote"', 'data-stage-action="rollback"',
            "/migration/preview", "/migrations`", "/rollback`", "data-view-operation", "pinnedImageDelta",
        ):
            self.assertIn(marker, JS + html)
        self.assertNotIn("personal-sandbox", JS)

    def test_migration_preflight_click_passes_declared_trust_domain(self) -> None:
        self.assertIn("targetTrustDomain: declaredTrustDomain(workload)", JS)
        operations = (DASHBOARD / "assets" / "operations.js").read_text()
        self.assertIn("targetTrustDomain: context.targetTrustDomain", operations)

    @unittest.skipUnless(shutil.which("node"), "requires node")
    def test_migration_preflight_parameters_resolve_declared_domain(self) -> None:
        stages = (DASHBOARD / "assets" / "stages.js").read_text()
        operations = (DASHBOARD / "assets" / "operations.js").read_text()
        helper = stages[stages.index("function declaredTrustDomain"):stages.index("// One family per staging")]
        ops = operations[operations.index("const NO_PARAMETERS"):operations.index("const OPERATIONS")]
        table = operations[operations.index("const OPERATIONS"):]
        table = table[:table.index("\n};") + 3]
        script = (
            'const state = {topology: {nodes: [{id: "a-managed", trustDomain: "personal-managed"}, {id: "old", trustDomain: "legacy-rootful"}]}};\n'
            + helper + ops + table + "\n"
            "const p = OPERATIONS['migration-preflight'].parameters;\n"
            "console.log(JSON.stringify(['a-managed', 'old', 'missing'].map((w) => p({ targetTrustDomain: declaredTrustDomain(w) }))));"
        )
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(
            json.loads(out),
            [{"targetTrustDomain": "personal-managed"}, {"targetTrustDomain": "legacy-rootful"}, {"targetTrustDomain": ""}],
        )

    @unittest.skipUnless(shutil.which("node"), "requires node")
    def test_stage_families_pair_by_promotes_to_then_name(self) -> None:
        stages = (ROOT / "control-plane" / "dashboard" / "assets" / "stages.js").read_text()
        harness = "const state = null; const escapeHtml = String; " + stages.replace("const TERMINAL_STATES", "var TERMINAL_STATES") + r"""
        const w = [{ id: "a-staging" }, { id: "a-production" }, { id: "b-stage", promotesTo: "b-live" }, { id: "b-live" }, { id: "c-staging" }, { id: "other" }];
        console.log(JSON.stringify(stageFamilies(w).map((f) => [f.name, f.staging.id, f.production && f.production.id])));
        """
        out = subprocess.run(["node", "-e", harness], text=True, capture_output=True, check=True).stdout
        self.assertEqual(
            [["a", "a-staging", "a-production"], ["b-stage", "b-stage", "b-live"], ["c", "c-staging", None]],
            json.loads(out),
        )

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
