// "What is broken" presentation: exception counts, health verdicts, and freshness labels.
// Concatenated into app.js by generate_dashboard.py; pure functions over the dashboard state.
const STATE_POLL_SECONDS = 30;
// Three missed state polls before the dashboard calls its own data stale.
const STATE_STALE_SECONDS = 3 * STATE_POLL_SECONDS;
// Three missed runs of argus-typed-health.timer (every 5 minutes).
const HEALTH_STALE_SECONDS = 15 * 60;

function ageText(seconds) {
  if (seconds < 60) return "less than 1m old";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m old`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h old`;
  return `${Math.floor(seconds / 86400)}d old`;
}

// DESIGN.md freshness labels: Fresh, Stale, Never observed.
function freshnessPresentation(value, maxAgeSeconds, now = Date.now()) {
  const instant = Date.parse(value || "");
  if (!value || !Number.isFinite(instant)) return { label: "Never observed", tone: "warn", age: value ? String(value) : "no evidence recorded" };
  const seconds = Math.max(0, Math.floor((now - instant) / 1000));
  return seconds > maxAgeSeconds
    ? { label: "Stale", tone: "warn", age: ageText(seconds) }
    : { label: "Fresh", tone: "good", age: ageText(seconds) };
}

// DESIGN.md health labels: Healthy, Degraded, Down, Unknown. No health source reports Degraded yet.
function healthPresentation(health = {}) {
  if (health.ok === true) return { label: "Healthy", tone: "good", rank: 0, detail: "Last check passed" };
  if (health.ok === false) return { label: "Down", tone: "bad", rank: 2, detail: "Last check failed" };
  return { label: "Unknown", tone: "warn", rank: 1, detail: health.enabled ? "Check configured, not yet observed" : "No health check configured" };
}

function exceptionReasons(dashboardState, evidenceStateId) {
  const workloads = dashboardState?.workloads || [];
  const topologySummary = dashboardState?.topology?.summary || {};
  const openAlerts = dashboardState?.alerts?.alerts || [];
  const reasons = [];
  const add = (count, singular, plural) => { if (count > 0) reasons.push({ count, text: `${count} ${count === 1 ? singular : plural}` }); };
  add(openAlerts.filter((item) => ["page", "critical"].includes(String(item?.severity || "").toLowerCase())).length, "paging alert", "paging alerts");
  add(workloads.filter((item) => item?.health?.ok === false).length, "workload down", "workloads down");
  add(Number(topologySummary.accessDrift || 0), "access drift", "access drifts");
  add(Number(topologySummary.unresolvedClassifications || 0), "unclassified workload", "unclassified workloads");
  if (workloads.length && !Number(topologySummary.domainAgentsAvailable || 0)) add(1, "no domain agent available", "");
  if (["empty", "conflict", "error"].includes(evidenceStateId)) add(1, `evidence ${evidenceStateId}`, "");
  return reasons;
}

// One "Needs attention" list: every exception (tone bad) plus warnings, each with its next step.
// `evidence` is the presentation for the current estate-evidence state; `now` is injectable for tests.
function attentionItems(dashboardState, evidenceStateId, evidence, now = Date.now()) {
  const workloads = dashboardState?.workloads || [];
  const nodes = (dashboardState?.topology?.nodes || []).filter((node) => node?.kind === "workload");
  const topologySummary = dashboardState?.topology?.summary || {};
  const alerts = dashboardState?.alerts;
  const providers = dashboardState?.exposure?.providers || {};
  const nameOf = (id) => workloads.find((item) => item?.id === id)?.name || id;
  const inspect = (id) => ({ label: "Inspect", href: `#/workloads/${encodeURIComponent(id)}` });
  const items = [];
  if (!alerts || alerts.available === false) {
    items.push({ tone: "warn", title: "Alert evaluator has not reported", detail: "argus-alert has not written state yet, so open alerts cannot be shown." });
  } else {
    (alerts.alerts || []).forEach((item) => {
      const paging = ["page", "critical"].includes(String(item?.severity || "").toLowerCase());
      items.push({ tone: paging ? "bad" : "warn", title: `${item?.severity || "alert"}: ${item?.id || "unnamed"}`, detail: String(item?.detail || "") });
    });
  }
  workloads.filter((item) => item?.health?.ok === false).forEach((item) => {
    items.push({ tone: "bad", title: `${nameOf(item.id)} is down`, detail: "Its last health check failed.", action: inspect(item.id) });
  });
  nodes.filter((node) => node.drift).forEach((node) => {
    items.push({ tone: "bad", title: `${nameOf(node.id)}: access drift`, detail: `Declared ${node.declaredAccess || "none"}, effective ${node.effectiveAccess || "none"}.`, action: inspect(node.id) });
  });
  const unclassified = Number(topologySummary.unresolvedClassifications || 0);
  if (unclassified > 0) items.push({ tone: "bad", title: `${unclassified} unclassified ${unclassified === 1 ? "workload" : "workloads"}`, detail: "Classify each workload before Argus can place or operate it." });
  if (workloads.length && !Number(topologySummary.domainAgentsAvailable || 0)) {
    items.push({ tone: "bad", title: "No trust-domain agent available", detail: "Workload actions stay blocked until an agent reports in." });
  }
  if (evidence && evidenceStateId !== "loading" && evidenceStateId !== "complete") {
    items.push({ tone: evidence.tone === "bad" || ["empty", "conflict", "error"].includes(evidenceStateId) ? "bad" : "warn", title: evidence.headline, detail: evidence.detail, action: evidence.refresh ? { label: evidence.action, refresh: true } : { label: "View evidence", href: "#evidence-state" } });
  }
  if (providers.tailscale?.funnel?.observedEnabled) {
    items.push({ tone: "bad", title: "Tailscale Funnel is on", detail: "Funnel must stay off. Turn it off on the server.", action: { label: "View exposure", href: "#system" } });
  }
  if (providers.cloudflare?.enabled) {
    items.push({ tone: "warn", title: "Cloudflare provider enabled", detail: "Public routes are allowed by policy. Check each workload's effective access.", action: { label: "View exposure", href: "#system" } });
  }
  const staleHealth = workloads.filter((item) => {
    const at = item?.health?.lastObservedAt || item?.migration?.lastHealthCheck || "";
    return freshnessPresentation(at, HEALTH_STALE_SECONDS, now).label !== "Fresh";
  }).length;
  if (staleHealth) {
    items.push({ tone: "warn", title: `Health evidence stale for ${staleHealth} of ${workloads.length} ${workloads.length === 1 ? "workload" : "workloads"}`, detail: "Run Refresh health on a workload, or check argus-typed-health.timer.", action: { label: "View workloads", href: "#workloads-heading" } });
  }
  // Exceptions first; the sort is stable, so each group keeps the order above.
  return items.sort((a, b) => (a.tone === "bad" ? 0 : 1) - (b.tone === "bad" ? 0 : 1));
}
