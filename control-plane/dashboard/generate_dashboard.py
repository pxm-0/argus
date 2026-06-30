#!/usr/bin/env python3
"""Generate the private Oreo Cloud dashboard static files."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "control-plane" / "dashboard" / "public"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(line.rstrip() for line in content.splitlines()) + "\n")


def render_html() -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Oreo Cloud Mission Control</title>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="./style.css">
  </head>
  <body>
    <header class="topbar">
      <div>
        <h1>Oreo Cloud Mission Control</h1>
        <p id="route-summary">loading dashboard state</p>
      </div>
      <div class="top-actions">
        <button id="monitor-toggle" type="button">Show Monitor</button>
        <button id="admin-toggle" type="button">Admin Mode</button>
      </div>
    </header>
    <main>
      <section class="summary" id="summary" aria-label="System summary"></section>
      <section class="alert" id="exposure-alert">
        <strong>Exposure control</strong>
        <span>loading exposure state</span>
      </section>
      <section class="monitor" id="monitor-panel" hidden>
        <div class="section-head">
          <h2>Monitor</h2>
          <span id="monitor-status">metrics idle</span>
        </div>
        <div id="metrics" class="metrics-grid"></div>
      </section>
      <section class="section-head">
        <h2>Workloads</h2>
        <span>Migration, backup, access, and operations</span>
      </section>
      <section class="workloads" id="workloads"></section>
      <section class="plan-grid">
        <article id="access-plan">
          <h2>Access Plan</h2>
          <p>loading access state</p>
          <code>-</code>
        </article>
        <article id="backup-plan">
          <h2>Backups</h2>
          <p>loading backup state</p>
          <code>/srv/oreo-cloud/runtime/backups</code>
        </article>
        <article id="cloudflare-plan">
          <h2>Cloudflare Plan</h2>
          <p>loading Cloudflare state</p>
          <code>-</code>
        </article>
        <article>
          <h2>Events</h2>
          <pre id="events">loading events</pre>
        </article>
        <article id="system-plan">
          <h2>System</h2>
          <p>loading system state</p>
          <code>-</code>
        </article>
      </section>
    </main>
    <script src="./app.js"></script>
  </body>
</html>
"""


CSS = r"""
:root {
  color-scheme: dark;
  --bg: oklch(0.145 0.018 215);
  --bg-2: oklch(0.18 0.019 215);
  --panel: oklch(0.205 0.018 215);
  --panel-2: oklch(0.245 0.018 215);
  --panel-3: oklch(0.285 0.018 215);
  --ink: oklch(0.9 0.018 215);
  --muted: oklch(0.71 0.024 205);
  --faint: oklch(0.56 0.023 205);
  --line: oklch(0.36 0.026 205);
  --line-strong: oklch(0.47 0.044 195);
  --cyan: oklch(0.82 0.16 195);
  --cyan-dim: oklch(0.45 0.11 195);
  --cyan-panel: oklch(0.235 0.04 195);
  --blue: oklch(0.73 0.15 245);
  --blue-panel: oklch(0.235 0.045 245);
  --green: oklch(0.75 0.15 155);
  --green-panel: oklch(0.225 0.045 155);
  --amber: oklch(0.82 0.14 75);
  --amber-panel: oklch(0.245 0.052 75);
  --red: oklch(0.72 0.18 28);
  --red-panel: oklch(0.235 0.06 28);
  --focus: 0 0 0 3px oklch(0.82 0.16 195 / 34%);
}
* { box-sizing: border-box; }
html { min-width: 320px; background: var(--bg); }
[hidden] { display: none !important; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at 18% -10%, oklch(0.26 0.06 195 / 38%), transparent 34rem),
    linear-gradient(180deg, var(--bg-2), var(--bg) 28rem);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
button, select { font: inherit; }
button, .action {
  min-height: 32px;
  padding: 6px 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel-2);
  color: var(--ink);
  cursor: pointer;
  text-decoration: none;
  font-weight: 750;
  font-size: 12px;
}
button:hover, .action:hover {
  border-color: var(--cyan);
  background: var(--cyan-panel);
  color: var(--cyan);
}
button:focus-visible, .action:focus-visible, select:focus-visible { outline: 0; box-shadow: var(--focus); }
select {
  min-height: 32px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--bg);
  color: var(--ink);
  padding: 6px 8px;
}
.action.disabled {
  color: var(--faint);
  cursor: default;
  background: var(--panel);
}
.action.disabled:hover { border-color: var(--line); color: var(--faint); background: var(--panel); }
#monitor-toggle { border-color: var(--blue); color: var(--blue); background: var(--blue-panel); }
#admin-toggle { border-color: var(--amber); color: var(--amber); background: var(--amber-panel); }
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
  background: oklch(0.16 0.018 215 / 96%);
  backdrop-filter: blur(12px);
}
h1, h2, p { margin: 0; }
h1 {
  color: var(--cyan);
  font-size: 18px;
  line-height: 1.05;
  letter-spacing: 0.01em;
  text-transform: uppercase;
}
h2 {
  font-size: 13px;
  line-height: 1.2;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.topbar p, .section-head span, .muted {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.top-actions { display: flex; gap: 8px; flex-wrap: wrap; }
main {
  width: min(1560px, 100%);
  margin: 0 auto;
  padding: 12px 14px 28px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(170px, 1fr));
  gap: 1px;
  margin-bottom: 12px;
  overflow: auto hidden;
  border: 1px solid var(--line);
  background: var(--line);
}
.summary div, .alert, .monitor, .workload, .plan-grid article {
  background: var(--panel);
  border: 1px solid var(--line);
}
.summary div {
  min-width: 0;
  padding: 12px 14px;
  border: 0;
  background: var(--panel);
}
.summary div:nth-child(1) { background: var(--green-panel); }
.summary div:nth-child(2) { background: var(--blue-panel); }
.summary div:nth-child(3) { background: var(--amber-panel); }
.summary div:nth-child(4) { background: var(--cyan-panel); }
.summary div:nth-child(5) { background: oklch(0.225 0.045 130); }
.summary strong {
  display: block;
  color: var(--ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 24px;
  line-height: 1;
  letter-spacing: 0;
}
.summary div:nth-child(1) strong { color: var(--green); }
.summary div:nth-child(2) strong { color: var(--blue); }
.summary div:nth-child(3) strong { color: var(--amber); }
.summary div:nth-child(4) strong { color: var(--cyan); }
.summary div:nth-child(5) strong { color: oklch(0.79 0.13 130); }
.summary span, dt {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 750;
}
.alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: var(--amber-panel);
  border-color: var(--amber);
  color: var(--amber);
}
.alert strong {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.alert span { color: oklch(0.91 0.09 75); }
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  margin: 12px 0 0;
  border: 1px solid var(--line);
  border-bottom: 0;
  background: var(--panel-2);
}
.section-head h2 {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--cyan);
}
.section-head h2::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 10px oklch(0.82 0.16 195 / 70%);
}
.workloads {
  display: grid;
  grid-template-columns: 1fr;
  border: 1px solid var(--line);
  background: var(--line);
  gap: 1px;
}
.workload {
  position: relative;
  border: 0;
  border-radius: 0;
  padding: 12px;
  background: var(--panel);
}
.workload:hover { background: var(--panel-2); }
.workload[data-privacy="unclassified"] { box-shadow: inset 0 0 0 1px oklch(0.75 0.15 155 / 34%); }
.workload[data-privacy="internal"] { box-shadow: inset 0 0 0 1px oklch(0.82 0.16 195 / 34%); }
.workload[data-privacy="sensitive"] { box-shadow: inset 0 0 0 1px oklch(0.82 0.14 75 / 42%); }
.workload[data-privacy="restricted"] { box-shadow: inset 0 0 0 1px oklch(0.72 0.18 28 / 46%); }
.workload::before {
  content: "";
  position: absolute;
  top: 17px;
  right: 14px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--blue);
  box-shadow: 0 0 9px oklch(0.73 0.15 245 / 65%);
}
.workload[data-access="local"]::before,
.workload[data-access="tailnet"]::before {
  background: var(--cyan);
  box-shadow: 0 0 9px oklch(0.82 0.16 195 / 65%);
}
.workload[data-privacy="sensitive"]::before { background: var(--amber); box-shadow: 0 0 9px oklch(0.82 0.14 75 / 65%); }
.workload[data-privacy="restricted"]::before { background: var(--red); box-shadow: 0 0 9px oklch(0.72 0.18 28 / 65%); }
.workload-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 0 18px 10px 0;
  border-bottom: 1px solid var(--line);
}
.workload-head h2 {
  color: var(--ink);
  letter-spacing: 0;
  text-transform: none;
  font-size: 16px;
}
.workload[data-migration="migrated"] .workload-head h2 { color: var(--green); }
.workload-head p {
  color: var(--muted);
  margin-top: 4px;
  max-width: 78ch;
  text-wrap: pretty;
}
code {
  padding: 3px 6px;
  border: 1px solid var(--line);
  border-radius: 3px;
  background: var(--bg);
  color: var(--cyan);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  word-break: break-word;
}
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0;
}
.pill {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  border-radius: 999px;
  padding: 3px 8px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  font-weight: 750;
}
.pill span { color: currentColor; opacity: 0.68; }
.pill.good { border-color: var(--green); background: var(--green-panel); color: var(--green); }
.pill.info { border-color: var(--blue); background: var(--blue-panel); color: var(--blue); }
.pill.warn { border-color: var(--amber); background: var(--amber-panel); color: var(--amber); }
.pill.bad { border-color: var(--red); background: var(--red-panel); color: var(--red); }
.facts {
  display: grid;
  grid-template-columns: repeat(6, minmax(118px, 1fr));
  gap: 1px;
  margin: 0;
  border: 1px solid var(--line);
  background: var(--line);
  overflow: hidden;
}
.facts div {
  min-width: 0;
  padding: 8px 10px;
  background: oklch(0.18 0.018 215);
}
dt { color: var(--faint); }
dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
  color: var(--ink);
  font-weight: 700;
}
.warning {
  margin-top: 10px;
  padding: 9px 10px;
  border: 1px solid var(--amber);
  background: var(--amber-panel);
  color: oklch(0.92 0.09 75);
}
.actions, .admin-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.admin-row {
  padding-top: 10px;
  border-top: 1px dashed var(--line-strong);
}
.admin-row label {
  display: grid;
  gap: 4px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  text-transform: uppercase;
}
.monitor {
  padding: 12px;
  margin-bottom: 12px;
  background: var(--blue-panel);
  border-color: var(--blue);
}
.monitor .section-head {
  padding: 0 0 10px;
  margin: 0 0 10px;
  border: 0;
  background: transparent;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.metric {
  padding: 10px;
  border: 1px solid var(--line);
  background: var(--bg);
}
.metric strong {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  text-transform: uppercase;
}
.metric p {
  margin-top: 4px;
  color: var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 800;
}
.bar {
  height: 6px;
  margin-top: 8px;
  background: var(--panel-3);
  overflow: hidden;
}
.bar span {
  display: block;
  height: 100%;
  background: var(--blue);
}
.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.plan-grid article {
  min-width: 0;
  padding: 12px;
  background: var(--panel);
}
.plan-grid article:nth-child(1) { border-color: var(--blue); background: var(--blue-panel); }
.plan-grid article:nth-child(2) { border-color: var(--green); background: var(--green-panel); }
.plan-grid article:nth-child(3) { border-color: var(--amber); background: var(--amber-panel); }
.plan-grid article:nth-child(4) { border-color: var(--cyan); background: var(--cyan-panel); }
.plan-grid article h2 { color: var(--ink); }
.plan-grid article p {
  color: var(--muted);
  margin: 8px 0 10px;
  text-wrap: pretty;
}
pre {
  white-space: pre-wrap;
  margin: 10px 0 0;
  color: var(--muted);
  max-height: 180px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--line-strong); border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: var(--cyan-dim); }
@media (max-width: 980px) {
  .facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  main { padding: 10px; }
  .summary { grid-template-columns: 1fr; overflow: visible; }
  .alert { align-items: flex-start; flex-direction: column; }
  .workload-head { grid-template-columns: 1fr; }
  .facts, .metrics-grid { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .top-actions { width: 100%; }
  .top-actions button { flex: 1 1 auto; }
  h1 { font-size: 16px; }
}
@media (prefers-reduced-motion: no-preference) {
  button, .action, .workload, .plan-grid article {
    transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
  }
}
"""


JS = r"""
let state = null;
const monitorToggle = document.getElementById("monitor-toggle");
const monitorPanel = document.getElementById("monitor-panel");
const monitorStatus = document.getElementById("monitor-status");
const metricsEl = document.getElementById("metrics");
const adminToggle = document.getElementById("admin-toggle");
const routeSummary = document.getElementById("route-summary");
const summaryEl = document.getElementById("summary");
const exposureAlert = document.getElementById("exposure-alert");
const workloadsEl = document.getElementById("workloads");
const eventsEl = document.getElementById("events");
let monitorTimer = null;
let adminEnabled = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusClass(value) {
  const normalized = String(value || "").toLowerCase();
  if (["active", "ok", "tailnet", "local", "migrated"].includes(normalized)) return "good";
  if (["planned", "cloudflare-protected"].includes(normalized)) return "info";
  if (["restricted", "sensitive", "existing-funnel", "needs-discovery"].includes(normalized)) return "warn";
  if (["cloudflare-public", "blocked"].includes(normalized)) return "bad";
  return "neutral";
}

function pill(label, value) {
  const safeValue = value || "-";
  return `<span class="pill ${statusClass(safeValue)}"><span>${escapeHtml(label)}</span>${escapeHtml(safeValue)}</span>`;
}

function pct(value) {
  const num = Number(value || 0);
  return Math.max(0, Math.min(100, num));
}

function metricCard(label, value, percent) {
  const width = percent == null ? 0 : pct(percent);
  return `<div class="metric"><strong>${label}</strong><p>${value}</p>${percent == null ? "" : `<div class="bar"><span style="width:${width}%"></span></div>`}</div>`;
}

function renderMetrics(data) {
  if (!data || data.error) {
    metricsEl.innerHTML = metricCard("Metrics", data?.error || "No metrics.json yet", null);
    return;
  }
  metricsEl.innerHTML = [
    metricCard("CPU", `${data.cpu?.percent ?? "-"}%`, data.cpu?.percent),
    metricCard("Memory", `${data.memory?.percent ?? "-"}%`, data.memory?.percent),
    metricCard("Disk", `${data.disk?.percent ?? "-"}%`, data.disk?.percent),
    metricCard("Load", `${data.load?.one ?? "-"} ${data.load?.five ?? "-"} ${data.load?.fifteen ?? "-"}`, null)
  ].join("");
}

async function fetchMetrics() {
  monitorStatus.textContent = "loading metrics";
  try {
    let response = await fetch("/api/metrics", { cache: "no-store" });
    if (!response.ok) response = await fetch("./metrics.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`metrics ${response.status}`);
    renderMetrics(await response.json());
    monitorStatus.textContent = "metrics live";
  } catch (error) {
    renderMetrics({ error: error.message });
    monitorStatus.textContent = "metrics unavailable";
  }
}

function setMonitor(open) {
  monitorPanel.hidden = !open;
  monitorToggle.textContent = open ? "Hide Monitor" : "Show Monitor";
  if (monitorTimer) {
    clearInterval(monitorTimer);
    monitorTimer = null;
  }
  if (open) {
    fetchMetrics();
    monitorTimer = setInterval(fetchMetrics, Number(state?.monitoring?.refreshSeconds || 3) * 1000);
  }
}

function renderSummary() {
  const workloads = state?.workloads || [];
  const exposure = state?.exposure?.providers || {};
  const funnel = exposure?.tailscale?.funnel || {};
  const cloudflareState = exposure?.cloudflare?.enabled ? "Enabled" : "Disabled";
  const funnelState = funnel.observedEnabled ? "Observed" : "Clear";
  const migrated = workloads.filter((item) => item.migration?.status === "migrated").length;
  const backupPlans = workloads.filter((item) => item.backup?.status).length;
  summaryEl.innerHTML = [
    ["Workloads", workloads.length],
    ["Cloudflare", cloudflareState],
    ["Funnel", funnelState],
    ["Migrated", migrated],
    ["Backup plans", backupPlans]
  ].map(([label, value]) => `<div><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  exposureAlert.innerHTML = `<strong>Exposure control</strong><span>Funnel allowed in P0: ${funnel.allowedInP0 ? "yes" : "no"}. Observed Funnel: ${funnel.observedEnabled ? "yes" : "no"}. Cloudflare: ${cloudflareState.toLowerCase()}.</span>`;
}

function workloadActions(urls) {
  const actions = [];
  [
    ["Local", urls?.local || ""],
    ["Tailnet", urls?.tailnet || ""],
    ["Cloudflare", urls?.cloudflare || ""]
  ].forEach(([label, href]) => {
    if (!href) return;
    if (label === "Cloudflare" && href.endsWith(".invalid")) {
      actions.push(`<span class="action disabled">${escapeHtml(label)} planned</span>`);
    } else {
      actions.push(`<a class="action" href="${escapeHtml(href)}">${escapeHtml(label)}</a>`);
    }
  });
  return actions.length ? actions.join("") : '<span class="muted">No open URL configured</span>';
}

function renderWorkload(workload) {
  const id = workload.id;
  const runtime = workload.runtime || {};
  const network = workload.network || {};
  const health = workload.health || {};
  const migration = workload.migration || {};
  const privacy = workload.privacy || {};
  const access = workload.access || {};
  const urls = access.urls || {};
  const cloudflare = workload.routes?.cloudflare || {};
  const operations = workload.operations || {};
  const backup = workload.backup || {};
  const lastEvent = workload.lastAuditEvent || {};
  const error = access.lastError || "";
  const healthLabel = health.enabled ? "configured" : "not configured";
  return `
    <article
      class="workload"
      data-workload="${escapeHtml(id)}"
      data-privacy="${escapeHtml(privacy.privacy || "")}"
      data-access="${escapeHtml(access.effective || "")}"
      data-migration="${escapeHtml(migration.status || "")}"
    >
      <div class="workload-head">
        <div>
          <h2>${escapeHtml(workload.name || id)}</h2>
          <p>${escapeHtml(workload.description || "")}</p>
        </div>
        <code>${escapeHtml(id)}</code>
      </div>
      <div class="pills">
        ${pill("life", workload.lifecycle)}
        ${pill("privacy", privacy.privacy)}
        ${pill("desired", access.desired)}
        ${pill("effective", access.effective)}
        ${pill("migration", migration.status)}
        ${pill("backup", backup.status || "needs-discovery")}
      </div>
      <dl class="facts">
        <div><dt>Runtime</dt><dd>${escapeHtml(runtime.type || "")}</dd></div>
        <div><dt>Compose</dt><dd>${escapeHtml(runtime.composeProject || runtime.compose?.project || "-")}</dd></div>
        <div><dt>Health</dt><dd>${escapeHtml(healthLabel)} ${escapeHtml(health.expectedStatus || "")}</dd></div>
        <div><dt>Last Health</dt><dd>${escapeHtml(migration.lastHealthCheck || "-")}</dd></div>
        <div><dt>Local URL</dt><dd>${escapeHtml(urls.local || "-")}</dd></div>
        <div><dt>Tailnet URL</dt><dd>${escapeHtml(urls.tailnet || "-")}</dd></div>
        <div><dt>Cloudflare</dt><dd>${escapeHtml(cloudflare.mode || "disabled")}</dd></div>
        <div><dt>Internal Port</dt><dd>${escapeHtml(network.internalPort || "-")}</dd></div>
        <div><dt>Legacy Path</dt><dd>${escapeHtml(workload.paths?.legacy || "-")}</dd></div>
        <div><dt>Ops</dt><dd>logs ${escapeHtml(Boolean(operations.logsAllowed || operations.logs?.allowed))}, restart ${escapeHtml(Boolean(operations.restartAllowed || operations.restart?.allowed))}</dd></div>
        <div><dt>Backup</dt><dd>${escapeHtml(backup.destination || "-")}</dd></div>
        <div><dt>Last Event</dt><dd>${escapeHtml(lastEvent.action || "-")} ${escapeHtml(lastEvent.result || "")}</dd></div>
      </dl>
      ${error ? `<p class="warning">${escapeHtml(error)}</p>` : ""}
      <div class="actions">${workloadActions(urls)}</div>
      <div class="actions operation-row">
        <button type="button" data-operation="logs-preview" data-workload="${escapeHtml(id)}">Logs preview</button>
        <button type="button" data-operation="restart-preview" data-workload="${escapeHtml(id)}">Restart preview</button>
        <button type="button" data-operation="backup-preview" data-workload="${escapeHtml(id)}">Backup preview</button>
      </div>
      <div class="admin-row" hidden>
        <label>Privacy <select data-action="privacy" data-workload="${escapeHtml(id)}"></select></label>
        <label>Access <select data-action="access" data-workload="${escapeHtml(id)}"></select></label>
        <button type="button" data-preview="${escapeHtml(id)}">Preview</button>
        <button type="button" data-apply="${escapeHtml(id)}">Apply</button>
        <button type="button" data-operation="restart-apply" data-workload="${escapeHtml(id)}">Restart apply</button>
        <button type="button" data-operation="backup-apply" data-workload="${escapeHtml(id)}">Backup apply</button>
      </div>
    </article>
  `;
}

function renderPlans() {
  const route = state?.routes?.dashboard || {};
  const api = state?.routes?.api || {};
  const exposure = state?.exposure?.providers || {};
  const monitoring = state?.monitoring || {};
  const backupPlans = (state?.workloads || []).filter((item) => item.backup?.status).length;
  routeSummary.textContent = `${route.url || "dashboard"} · API ${api.bind || "127.0.0.1"}:${api.port || "8099"}`;
  document.querySelector("#access-plan p").textContent = "Desired and effective access remain separate. Cloudflare states are planned until explicitly applied by policy.";
  document.querySelector("#access-plan code").textContent = `API ${api.bind || "127.0.0.1"}:${api.port || "8099"}`;
  document.querySelector("#backup-plan p").textContent = `${backupPlans} workloads have manifest-backed backup metadata. Backup runs remain blocked unless the workload manifest allows them.`;
  document.querySelector("#cloudflare-plan p").textContent = exposure.cloudflare?.enabled ? "Cloudflare provider is enabled by policy." : "Cloudflare is disabled. Quick tunnels and named tunnels are blocked until an explicit later phase changes policy.";
  document.querySelector("#cloudflare-plan code").textContent = exposure.cloudflare?.configPath || "-";
  document.querySelector("#system-plan p").textContent = `Monitor refresh ${monitoring.refreshSeconds || 3}s. Dashboard remains view-only without admin mode.`;
  document.querySelector("#system-plan code").textContent = route.url || "-";
}

function renderEvents() {
  const events = state?.events || [];
  eventsEl.textContent = events.slice(-8).map((event) => `${event.timestamp || ""} ${event.workloadId || ""} ${event.action || ""} ${event.result || ""}`.trim()).join("\n") || "No audit events loaded.";
}

function renderDashboard() {
  renderSummary();
  workloadsEl.innerHTML = (state.workloads || []).map(renderWorkload).join("");
  renderPlans();
  renderEvents();
  if (adminEnabled) fillAdminControls();
}

async function loadDashboardState() {
  try {
    let response = await fetch("/api/dashboard-state", { cache: "no-store" });
    if (!response.ok) response = await fetch("./dashboard-state.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`dashboard state ${response.status}`);
    state = await response.json();
    renderDashboard();
  } catch (error) {
    routeSummary.textContent = "dashboard state unavailable";
    summaryEl.innerHTML = `<div><strong>!</strong><span>${escapeHtml(error.message)}</span></div>`;
    workloadsEl.innerHTML = "";
    eventsEl.textContent = "No dashboard state loaded.";
  }
}

function fillAdminControls() {
  document.querySelectorAll('select[data-action="privacy"]').forEach((select) => {
    select.innerHTML = (state?.privacyStates || []).map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
    const workload = select.dataset.workload;
    const current = state?.workloads?.find((item) => item.id === workload)?.privacy?.privacy;
    if (current) select.value = current;
  });
  document.querySelectorAll('select[data-action="access"]').forEach((select) => {
    select.innerHTML = (state?.accessStates || []).map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
    const workload = select.dataset.workload;
    const current = state?.workloads?.find((item) => item.id === workload)?.access?.desired;
    if (current) select.value = current;
  });
}

function setAdmin(open) {
  adminEnabled = open;
  adminToggle.textContent = open ? "Exit Admin" : "Admin Mode";
  document.querySelectorAll(".admin-row").forEach((row) => {
    row.hidden = !open;
  });
  if (open) fillAdminControls();
}

monitorToggle.addEventListener("click", () => setMonitor(monitorPanel.hidden));
adminToggle.addEventListener("click", () => {
  if (!adminEnabled) {
    const token = window.prompt("Control token");
    if (!token) return;
    sessionStorage.setItem("oreoControlToken", token);
  } else {
    sessionStorage.removeItem("oreoControlToken");
  }
  setAdmin(!adminEnabled);
});

document.addEventListener("click", async (event) => {
  const operation = event.target.closest("[data-operation]");
  if (operation) {
    const workload = operation.dataset.workload;
    const action = operation.dataset.operation;
    const token = sessionStorage.getItem("oreoControlToken") || "";
    if (!token) {
      window.alert("Admin token required");
      return;
    }
    const body = action.endsWith("-apply") ? { confirmation: window.prompt(`Type ${workload} to confirm`) || "" } : {};
    if (action.endsWith("-apply") && body.confirmation !== workload) return;
    const parts = action.split("-");
    const endpoint = `/api/workloads/${encodeURIComponent(workload)}/${parts[0]}/${parts[1]}`;
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });
      const payload = await response.json();
      const lines = Array.isArray(payload.lines) ? `\n\n${payload.lines.join("\n")}` : "";
      window.alert(`${payload.summary || payload.reason || response.statusText}${lines}`);
      await loadDashboardState();
    } catch (error) {
      window.alert(`Action failed: ${error.message}`);
    }
    return;
  }
  const preview = event.target.closest("[data-preview]");
  const apply = event.target.closest("[data-apply]");
  if (!preview && !apply) return;
  const workload = (preview || apply).dataset.preview || (preview || apply).dataset.apply;
  const mode = preview ? "preview" : "apply";
  window.alert(`${mode} for ${workload} requires the P0 control API phase.`);
});

loadDashboardState();
"""


def main() -> int:
    write(PUBLIC / "index.html", render_html())
    write(PUBLIC / "style.css", CSS.strip() + "\n")
    write(PUBLIC / "app.js", JS.strip() + "\n")
    print(f"Generated {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
