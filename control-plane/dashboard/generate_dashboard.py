#!/usr/bin/env python3
"""Generate the private Argus dashboard static files.

The M5 estate matrix prioritizes categorical comparison: trust domain, workload,
declared access, effective access, and drift remain visible in one scanning path.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m5_style import M5_CSS


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
    <title>Argus</title>
    <link rel="icon" href="data:,">
    <script>const requestedTheme = new URLSearchParams(location.search).get("theme"); document.documentElement.dataset.theme = ["light", "dark"].includes(requestedTheme) ? requestedTheme : (localStorage.getItem("argus-theme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));</script>
    <link rel="stylesheet" href="./style.css">
  </head>
  <body>
    <div class="app-shell">
      <aside class="nav-rail" aria-label="Primary navigation">
        <a class="brand" href="#overview" aria-label="Argus overview">A</a>
        <nav>
          <a href="#overview" aria-current="page"><span>01</span>Topology</a>
          <a href="#workloads-heading"><span>02</span>Workloads</a>
          <a href="#evidence"><span>03</span>Evidence</a>
        </nav>
        <div class="private-state"><i aria-hidden="true"></i><span>Private<br>control plane</span></div>
      </aside>
      <div class="app-main">
    <header class="topbar">
      <div class="title-lockup">
        <p class="eyebrow">PRIVATE CONTROL PLANE</p>
        <h1>Argus</h1>
        <p id="route-summary">loading dashboard state</p>
      </div>
      <div class="top-actions" aria-label="Operator tools">
        <input id="admin-token" type="password" autocomplete="off" placeholder="bootstrap credential" hidden>
        <button id="workload-discover" type="button">Refresh Workloads</button>
        <button id="monitor-toggle" type="button">Show Monitor</button>
        <button id="theme-toggle" type="button" aria-pressed="false">Light Mode</button>
        <button id="admin-toggle" type="button">Admin Mode</button>
      </div>
    </header>
    <main id="overview">
      <section class="summary" id="summary" aria-label="System summary"></section>
      <section class="alert" id="exposure-alert">
        <strong>Exposure control</strong>
        <span>loading exposure state</span>
      </section>
      <section class="instrument-head">
        <div><p class="eyebrow">LIVE ESTATE MODEL</p><h2>Estate matrix</h2></div>
        <p>Compare containment, placement, and access state across every trust domain. Select a workload to inspect its evidence.</p>
      </section>
      <section class="topology" id="topology" aria-label="Whole-estate topology"></section>
      <section class="command-panel" id="command-panel" hidden>
        <div class="section-head">
          <h2>Command Result</h2>
          <button id="command-close" type="button">Close</button>
        </div>
        <pre id="command-output"></pre>
        <div id="command-actions" class="actions"></div>
      </section>
      <section class="monitor" id="monitor-panel" hidden>
        <div class="section-head">
          <h2>Monitor</h2>
          <span id="monitor-status">metrics idle</span>
        </div>
        <div id="metrics" class="metrics-grid"></div>
      </section>
      <section class="section-head" id="workloads-heading">
        <h2>Workloads</h2>
        <span>Migration, backup, access, and operations</span>
      </section>
      <section class="workloads" id="workloads"></section>
      <section class="plan-grid" id="evidence">
        <article id="access-plan">
          <h2>Access Plan</h2>
          <p>loading access state</p>
          <code>-</code>
        </article>
        <article id="backup-plan">
          <h2>Backups</h2>
          <p>loading backup state</p>
          <code>/srv/argus/runtime/backups</code>
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
      </div>
    </div>
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
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
button, select, input { font: inherit; }
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
input {
  min-height: 32px;
  min-width: 190px;
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
#admin-token {
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel-2);
  color: var(--ink);
  width: 200px;
}
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
.command-panel {
  padding: 12px;
  margin-bottom: 12px;
  background: var(--panel);
  border: 1px solid var(--line-strong);
}
.command-panel .section-head {
  padding: 0 0 10px;
  margin: 0 0 10px;
  border: 0;
  background: transparent;
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
  input { width: 100%; }
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
const workloadDiscoverButton = document.getElementById("workload-discover");
const monitorToggle = document.getElementById("monitor-toggle");
const monitorPanel = document.getElementById("monitor-panel");
const monitorStatus = document.getElementById("monitor-status");
const metricsEl = document.getElementById("metrics");
const adminToggle = document.getElementById("admin-toggle");
const themeToggle = document.getElementById("theme-toggle");
const adminTokenInput = document.getElementById("admin-token");
const routeSummary = document.getElementById("route-summary");
const summaryEl = document.getElementById("summary");
const exposureAlert = document.getElementById("exposure-alert");
const topologyEl = document.getElementById("topology");
const workloadsEl = document.getElementById("workloads");
const eventsEl = document.getElementById("events");
const commandPanel = document.getElementById("command-panel");
const commandOutput = document.getElementById("command-output");
const commandActions = document.getElementById("command-actions");
const commandClose = document.getElementById("command-close");
let monitorTimer = null;
let adminEnabled = false;
let csrfToken = "";
let operatorIdentity = "";
let selectedTopologyId = null;

function setTheme(theme) {
  const light = theme === "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  themeToggle.textContent = light ? "Dark Mode" : "Light Mode";
  themeToggle.setAttribute("aria-pressed", String(light));
}

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

function showCommandResult(title, payload) {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  commandOutput.textContent = `${title}\n\n${body}`;
  commandActions.innerHTML = "";
  commandPanel.hidden = false;
  commandPanel.scrollIntoView({ block: "nearest" });
}

function renderDiscoveryCandidates(candidates) {
  commandActions.innerHTML = (candidates || [])
    .map((id) => `<button type="button" data-register="${escapeHtml(id)}">Register ${escapeHtml(id)}</button>`)
    .join("");
}

function tokenFor() {
  return adminTokenInput.value;
}

function selectedValue(row, selector) {
  return row?.querySelector(selector)?.value || "";
}

async function apiPost(endpoint, token, body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (csrfToken && endpoint !== "/api/session/exchange") headers["X-Argus-CSRF"] = csrfToken;
  const response = await fetch(endpoint, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body || {})
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = { error: error.message };
  }
  return { ok: response.ok, status: response.status, payload };
}

async function authenticateOperator() {
  const credential = tokenFor();
  if (!credential) throw new Error("Enter the bootstrap credential.");
  const result = await apiPost("/api/session/exchange", credential, {});
  adminTokenInput.value = "";
  if (!result.ok) throw new Error(result.payload.error || `authentication ${result.status}`);
  csrfToken = result.payload.csrfToken || "";
  operatorIdentity = result.payload.identity || "";
  return result.payload;
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

function renderTopology() {
  const topology = state?.topology || {};
  const workloadNodes = (topology.nodes || []).filter((node) => node.kind === "workload");
  const nodes = new Map(workloadNodes.map((node) => [node.id, node]));
  const domains = (topology.domains || []).filter((domain) => domain.id !== "management");
  if (!selectedTopologyId || !nodes.has(selectedTopologyId)) {
    selectedTopologyId = nodes.has("hello-nginx") ? "hello-nginx" : workloadNodes[0]?.id;
  }
  const selected = nodes.get(selectedTopologyId) || {};
  const domainRows = domains.map((domain) => {
    const rows = domain.workloadIds.map((id) => {
      const node = nodes.get(id) || {};
      const active = id === selectedTopologyId ? " selected" : "";
      return `<button class="matrix-row${active}" type="button" data-focus-workload="${escapeHtml(id)}" aria-pressed="${id === selectedTopologyId}">
        <span class="matrix-workload"><b>${escapeHtml(node.label || id)}</b><small>${escapeHtml(node.classificationStatus || "unknown")}</small></span>
        <span class="access-value">${escapeHtml(node.declaredAccess || "none")}</span>
        <span class="access-arrow" aria-hidden="true">→</span>
        <span class="access-value">${escapeHtml(node.effectiveAccess || "none")}</span>
        <span class="drift-state ${node.drift ? "has-drift" : "aligned"}">${node.drift ? "DRIFT" : "ALIGNED"}</span>
      </button>`;
    }).join("") || `<div class="matrix-empty"><span>No workloads assigned</span><small>Available target domain</small></div>`;
    return `<section class="domain-group" data-domain-state="${escapeHtml(domain.state)}">
      <header><span class="domain-state" aria-hidden="true"></span><div><h3>${escapeHtml(domain.id)}</h3><p>${escapeHtml(domain.kind)} · ${escapeHtml(domain.state)} · ${domain.workloadIds.length} workloads</p></div></header>
      <div class="domain-workloads">${rows}</div>
    </section>`;
  }).join("");
  const controlBlocked = selected.controlMode === "domain-agent-required";
  const verdict = controlBlocked ? "Controls require a domain agent; direct management-plane execution remains disabled." : "Legacy-local controls remain manifest-gated and require Admin Mode acknowledgement.";
  topologyEl.innerHTML = `
    <div class="matrix-stage">
      <div class="matrix-columns" aria-hidden="true"><span>Trust domain</span><span>Workload</span><span>Declared</span><span></span><span>Effective</span><span>Status</span></div>
      ${domainRows}
    </div>
    <aside class="topology-inspector" aria-live="polite">
      <p class="inspector-kicker">SELECTED OBJECT / ${escapeHtml(selected.trustDomain || "unknown")}</p>
      <h3>${escapeHtml(selected.label || selected.id || "No workload")}</h3>
      <p class="inspector-state">${escapeHtml(selected.classificationStatus || "unclassified")} · admission ${escapeHtml(selected.admission || "unknown")}</p>
      <dl class="inspector-facts">
        <div><dt>Trust domain</dt><dd>${escapeHtml(selected.trustDomain || "-")}</dd></div>
        <div><dt>Realm / zone</dt><dd>${escapeHtml(selected.realm || "-")} / ${escapeHtml(selected.zone || "-")}</dd></div>
        <div><dt>Declared access</dt><dd>${escapeHtml(selected.declaredAccess || "-")}</dd></div>
        <div><dt>Effective access</dt><dd>${escapeHtml(selected.effectiveAccess || "-")}</dd></div>
        <div><dt>Access drift</dt><dd>${selected.drift ? "Detected" : "Aligned"}</dd></div>
        <div><dt>Control mode</dt><dd>${escapeHtml(selected.controlMode || "-")}</dd></div>
      </dl>
      <div class="control-verdict ${controlBlocked ? "blocked" : ""}"><strong>${controlBlocked ? "Execution boundary enforced" : "Guarded legacy control"}</strong><span>${escapeHtml(verdict)}</span></div>
      <button class="inspect-action" type="button" data-focus-workload="${escapeHtml(selected.id || "")}" data-open-detail="true">View workload evidence</button>
    </aside>`;
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
  const topologyNode = state?.topology?.nodes?.find((node) => node.id === id) || {};
  const domainAgentRequired = topologyNode.controlMode === "domain-agent-required";
  const logsAllowed = Boolean(operations.logsAllowed || operations.logs?.allowed);
  const restartAllowed = Boolean(operations.restartAllowed || operations.restart?.allowed);
  const backupAllowed = Boolean(operations.backupAllowed || operations.backup?.allowed || backup.backupAllowed);
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
        ${pill("domain", topologyNode.trustDomain || "legacy-rootful")}
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
      ${domainAgentRequired ? '<p class="warning">Domain operations are read-only until an identity-backed domain agent and scoped capability flow are available.</p>' : ""}
      <div class="actions">${workloadActions(urls)}</div>
      <div class="actions operation-row">
        <button type="button" data-operation="logs-preview" data-workload="${escapeHtml(id)}" ${logsAllowed && !domainAgentRequired ? "" : "disabled"}>Logs preview</button>
        <button type="button" data-operation="restart-preview" data-workload="${escapeHtml(id)}" ${restartAllowed && !domainAgentRequired ? "" : "disabled"}>Restart preview</button>
        <button type="button" data-operation="backup-preview" data-workload="${escapeHtml(id)}" ${backupAllowed && !domainAgentRequired ? "" : "disabled"}>Backup preview</button>
      </div>
      <div class="admin-row" hidden>
        <label>Privacy <select data-action="privacy" data-workload="${escapeHtml(id)}" ${domainAgentRequired ? "disabled" : ""}></select></label>
        <label>Access <select data-action="access" data-workload="${escapeHtml(id)}" ${domainAgentRequired ? "disabled" : ""}></select></label>
        <label>Confirm <input type="text" autocomplete="off" data-confirm="${escapeHtml(id)}" placeholder="${escapeHtml(id)}"></label>
        <button type="button" data-preview="${escapeHtml(id)}" ${domainAgentRequired ? "disabled" : ""}>Preview</button>
        <button type="button" data-apply="${escapeHtml(id)}" ${domainAgentRequired ? "disabled" : ""}>Apply</button>
        <button type="button" data-operation="restart-apply" data-workload="${escapeHtml(id)}" ${restartAllowed && !domainAgentRequired ? "" : "disabled"}>Restart apply</button>
        <button type="button" data-operation="backup-apply" data-workload="${escapeHtml(id)}" ${backupAllowed && !domainAgentRequired ? "" : "disabled"}>Backup apply</button>
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
  renderTopology();
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
  adminToggle.textContent = open ? (csrfToken ? "Logout" : "Authenticate") : "Admin Mode";
  adminTokenInput.hidden = !open;
  if (open) fillAdminControls();
  document.querySelectorAll(".admin-row").forEach((row) => {
    row.hidden = !open;
  });
}

workloadDiscoverButton.addEventListener("click", async () => {
  if (!csrfToken) {
    showCommandResult("Operator session required", "Authenticate before refreshing workload evidence.");
    return;
  }
  workloadDiscoverButton.disabled = true;
  workloadDiscoverButton.textContent = "Refreshing...";
  try {
    const result = await apiPost("/api/workloads/discover", "", {});
    showCommandResult("Workload discovery", result.payload);
    renderDiscoveryCandidates(result.payload.newComposeProjects);
  } catch (error) {
    showCommandResult("Refresh failed", error.message);
  } finally {
    workloadDiscoverButton.disabled = false;
    workloadDiscoverButton.textContent = "Refresh Workloads";
  }
});

monitorToggle.addEventListener("click", () => setMonitor(monitorPanel.hidden));
themeToggle.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  localStorage.setItem("argus-theme", theme);
  setTheme(theme);
});
adminToggle.addEventListener("click", async () => {
  if (!adminEnabled) {
    setAdmin(true);
    showCommandResult("Operator authentication", "Enter the bootstrap credential, then choose Authenticate.");
    return;
  }
  if (!csrfToken) {
    try {
      const session = await authenticateOperator();
      setAdmin(true);
      showCommandResult("Operator authenticated", { identity: session.identity, expiresAt: session.expiresAt });
    } catch (error) {
      showCommandResult("Authentication failed", error.message);
    }
  } else {
    await apiPost("/api/session/logout", "", {});
    csrfToken = "";
    operatorIdentity = "";
    adminTokenInput.value = "";
    setAdmin(false);
    showCommandResult("Operator session", "Logged out.");
  }
});

commandClose.addEventListener("click", () => {
  commandPanel.hidden = true;
  commandOutput.textContent = "";
});

document.addEventListener("click", async (event) => {
  const focus = event.target.closest("[data-focus-workload]");
  if (focus) {
    selectedTopologyId = focus.dataset.focusWorkload;
    renderTopology();
    if (focus.dataset.openDetail === "true") {
      document.querySelector(`[data-workload="${CSS.escape(selectedTopologyId)}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    return;
  }
  const register = event.target.closest("[data-register]");
  if (register) {
    const workloadId = register.dataset.register;
    if (!csrfToken) {
      showCommandResult("Operator session required", "Authenticate before registering workloads.");
      return;
    }
    register.disabled = true;
    try {
      const result = await apiPost(`/api/workloads/${encodeURIComponent(workloadId)}/register`, "", { composeProject: workloadId });
      showCommandResult(`Register ${workloadId}`, result.payload);
      await loadDashboardState();
    } catch (error) {
      showCommandResult("Register failed", error.message);
      register.disabled = false;
    }
    return;
  }
  const operation = event.target.closest("[data-operation]");
  if (operation) {
    const workload = operation.dataset.workload;
    const action = operation.dataset.operation;
    const row = operation.closest(".workload");
    if (!csrfToken) {
      showCommandResult("Operator session required", "Authenticate before running operations.");
      return;
    }
    const confirmation = row?.querySelector("[data-confirm]")?.value || "";
    const body = action.endsWith("-apply") ? { confirmation } : {};
    if (action.endsWith("-apply") && body.confirmation !== workload) {
      showCommandResult("Confirmation required", `Type ${workload} in the confirmation field before applying.`);
      return;
    }
    const parts = action.split("-");
    const endpoint = `/api/workloads/${encodeURIComponent(workload)}/${parts[0]}/${parts[1]}`;
    try {
      const result = await apiPost(endpoint, "", body);
      const lines = Array.isArray(result.payload.lines) ? { ...result.payload, lines: result.payload.lines } : result.payload;
      showCommandResult(`${workload} ${action}`, { status: result.status, ...lines });
      await loadDashboardState();
    } catch (error) {
      showCommandResult("Action failed", error.message);
    }
    return;
  }
  const preview = event.target.closest("[data-preview]");
  const apply = event.target.closest("[data-apply]");
  if (!preview && !apply) return;
  const workload = (preview || apply).dataset.preview || (preview || apply).dataset.apply;
  const row = (preview || apply).closest(".workload");
  if (!csrfToken) {
    showCommandResult("Operator session required", "Authenticate before applying changes.");
    return;
  }
  const current = state?.workloads?.find((item) => item.id === workload) || {};
  const privacyTarget = selectedValue(row, 'select[data-action="privacy"]');
  const accessTarget = selectedValue(row, 'select[data-action="access"]');
  const confirmation = selectedValue(row, "[data-confirm]");
  const privacyChanged = privacyTarget && privacyTarget !== current.privacy?.privacy;
  const accessChanged = accessTarget && accessTarget !== current.access?.desired;
  if (preview) {
    try {
      const accessPreview = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/access/preview`, "", { desired: accessTarget });
      showCommandResult(`${workload} preview`, {
        privacy: {
          from: current.privacy?.privacy || "",
          to: privacyTarget,
          wouldUpdate: privacyChanged
        },
        access: {
          status: accessPreview.status,
          ...accessPreview.payload
        }
      });
    } catch (error) {
      showCommandResult("Preview failed", error.message);
    }
    return;
  }
  if (!privacyChanged && !accessChanged) {
    showCommandResult(`${workload} apply`, "No privacy or access change selected.");
    return;
  }
  const results = [];
  try {
    if (privacyChanged) {
      const privacyResult = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/privacy`, "", {
        privacy: privacyTarget,
        reason: "Dashboard admin change"
      });
      results.push({ privacy: { status: privacyResult.status, ...privacyResult.payload } });
      if (!privacyResult.ok) {
        showCommandResult(`${workload} apply`, results);
        return;
      }
    }
    if (accessChanged) {
      const accessResult = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/access/apply`, "", {
        desired: accessTarget,
        confirmation
      });
      results.push({ access: { status: accessResult.status, ...accessResult.payload } });
    }
    showCommandResult(`${workload} apply`, results);
    await loadDashboardState();
  } catch (error) {
    showCommandResult("Apply failed", error.message);
  }
});

document.addEventListener("keydown", (event) => {
  const focus = event.target.closest('[role="button"][data-focus-workload]');
  if (!focus || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  selectedTopologyId = focus.dataset.focusWorkload;
  renderTopology();
});

setTheme(document.documentElement.dataset.theme);
async function restoreOperatorSession() {
  const response = await fetch("/api/session", { cache: "no-store", credentials: "same-origin" });
  if (response.ok) {
    const session = await response.json();
    csrfToken = session.csrfToken || "";
    operatorIdentity = session.identity || "";
    setAdmin(true);
  }
  await loadDashboardState();
}
restoreOperatorSession();
"""


def main() -> int:
    write(PUBLIC / "index.html", render_html())
    write(PUBLIC / "style.css", M5_CSS.strip() + "\n")
    write(PUBLIC / "app.js", JS.strip() + "\n")
    print(f"Generated {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
