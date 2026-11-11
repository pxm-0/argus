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
