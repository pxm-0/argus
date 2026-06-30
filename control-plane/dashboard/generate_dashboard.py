#!/usr/bin/env python3
"""Generate the private Oreo Cloud dashboard static files."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "control-plane" / "dashboard" / "public"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "config" / name).read_text())


def load_manifest(workload_id: str) -> dict[str, Any]:
    path = ROOT / "workloads" / workload_id / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def recent_events() -> list[dict[str, Any]]:
    path = ROOT / "runtime" / "audit.log"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines()[-50:]:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(
            {
                "timestamp": event.get("timestamp", ""),
                "action": event.get("action", ""),
                "workloadId": event.get("workloadId", ""),
                "result": event.get("result", ""),
            }
        )
    return events


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(line.rstrip() for line in content.splitlines()) + "\n")


def merged_state() -> dict[str, Any]:
    workloads = load_json("workloads.json")["workloads"]
    privacy = load_json("privacy.json")
    access = load_json("access.json")
    routes = load_json("routes.json")
    exposure = load_json("exposure.json")
    monitoring = load_json("monitoring.json")

    merged = []
    events = recent_events()
    for workload in workloads:
        wid = workload["id"]
        manifest = load_manifest(wid)
        last_event = next((event for event in reversed(events) if event.get("workloadId") == wid), {})
        merged.append(
            {
                **workload,
                "privacy": privacy["workloads"].get(wid, {}),
                "access": access["workloads"].get(wid, {}),
                "routes": routes["workloadRoutes"].get(wid, {}),
                "manifest": manifest,
                "operations": manifest.get("operations", {}),
                "backup": manifest.get("backup", {}),
                "lastAuditEvent": last_event,
            }
        )
    return {
        "workloads": merged,
        "privacyStates": privacy["states"],
        "accessStates": access["states"],
        "routes": routes,
        "exposure": exposure,
        "monitoring": monitoring,
        "events": events[-20:],
    }


def status_class(value: str) -> str:
    value = value.lower()
    if value in {"active", "ok", "tailnet", "local", "planned"}:
        return "good"
    if value in {"restricted", "sensitive", "existing-funnel", "needs-discovery"}:
        return "warn"
    if value in {"cloudflare-public", "blocked"}:
        return "bad"
    return "neutral"


def pill(label: str, value: str) -> str:
    return f'<span class="pill {status_class(value)}"><span>{escape(label)}</span>{escape(value or "-")}</span>'


def workload_card(workload: dict[str, Any]) -> str:
    wid = workload["id"]
    runtime = workload.get("runtime", {})
    network = workload.get("network", {})
    health = workload.get("health", {})
    migration = workload.get("migration", {})
    privacy = workload.get("privacy", {})
    access = workload.get("access", {})
    urls = access.get("urls", {})
    routes = workload.get("routes", {})
    cloudflare = routes.get("cloudflare", {})
    operations = workload.get("operations", {})
    backup = workload.get("backup", {})
    last_event = workload.get("lastAuditEvent", {})
    error = access.get("lastError") or ""
    health_label = "configured" if health.get("enabled") else "not configured"
    actions = []
    for label, href in [
        ("Local", urls.get("local", "")),
        ("Tailnet", urls.get("tailnet", "")),
        ("Cloudflare", urls.get("cloudflare", "")),
    ]:
        if href:
            actions.append(f'<a class="action" href="{escape(href)}">{escape(label)}</a>')
    if not actions:
        actions.append('<span class="muted">No open URL configured</span>')

    return f"""
    <article class="workload" data-workload="{escape(wid)}">
      <div class="workload-head">
        <div>
          <h2>{escape(workload.get("name", wid))}</h2>
          <p>{escape(workload.get("description", ""))}</p>
        </div>
        <code>{escape(wid)}</code>
      </div>
      <div class="pills">
        {pill("life", workload.get("lifecycle", ""))}
        {pill("privacy", privacy.get("privacy", ""))}
        {pill("desired", access.get("desired", ""))}
        {pill("effective", access.get("effective", ""))}
        {pill("migration", migration.get("status", ""))}
        {pill("backup", backup.get("status", "needs-discovery"))}
      </div>
      <dl class="facts">
        <div><dt>Runtime</dt><dd>{escape(runtime.get("type", ""))}</dd></div>
        <div><dt>Compose</dt><dd>{escape(runtime.get("composeProject", "") or "-")}</dd></div>
        <div><dt>Health</dt><dd>{escape(health_label)} {escape(str(health.get("expectedStatus", "")))}</dd></div>
        <div><dt>Last Health</dt><dd>{escape(migration.get("lastHealthCheck", "") or "-")}</dd></div>
        <div><dt>Local URL</dt><dd>{escape(urls.get("local", "") or "-")}</dd></div>
        <div><dt>Tailnet URL</dt><dd>{escape(urls.get("tailnet", "") or "-")}</dd></div>
        <div><dt>Cloudflare</dt><dd>{escape(cloudflare.get("mode", "disabled"))}</dd></div>
        <div><dt>Internal Port</dt><dd>{escape(str(network.get("internalPort", "-")))}</dd></div>
        <div><dt>Legacy Path</dt><dd>{escape(workload.get("paths", {}).get("legacy", "") or "-")}</dd></div>
        <div><dt>Ops</dt><dd>logs {escape(str(bool(operations.get("logsAllowed", False))).lower())}, restart {escape(str(bool(operations.get("restartAllowed", False))).lower())}</dd></div>
        <div><dt>Backup</dt><dd>{escape(backup.get("destination", "") or "-")}</dd></div>
        <div><dt>Last Event</dt><dd>{escape(last_event.get("action", "") or "-")} {escape(last_event.get("result", "") or "")}</dd></div>
      </dl>
      {f'<p class="warning">{escape(error)}</p>' if error else ''}
      <div class="actions">{"".join(actions)}</div>
      <div class="admin-row" hidden>
        <label>Privacy <select data-action="privacy" data-workload="{escape(wid)}"></select></label>
        <label>Access <select data-action="access" data-workload="{escape(wid)}"></select></label>
        <button type="button" data-preview="{escape(wid)}">Preview</button>
        <button type="button" data-apply="{escape(wid)}">Apply</button>
      </div>
    </article>
    """


def script_json(data: dict[str, Any]) -> str:
    return (
        json.dumps(data, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def render_html(state: dict[str, Any]) -> str:
    workloads = "\n".join(workload_card(item) for item in state["workloads"])
    migrated = sum(1 for item in state["workloads"] if item.get("migration", {}).get("status") == "migrated")
    backup_plans = sum(1 for item in state["workloads"] if item.get("backup", {}).get("status"))
    events = "\n".join(
        f"{escape(event.get('timestamp', ''))} {escape(event.get('workloadId', ''))} {escape(event.get('action', ''))} {escape(event.get('result', ''))}"
        for event in state.get("events", [])[-8:]
    )
    route = state["routes"]["dashboard"]
    api = state["routes"]["api"]
    exposure = state["exposure"]["providers"]
    funnel = exposure["tailscale"]["funnel"]
    initial_state = script_json(state)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Oreo Cloud</title>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="./style.css">
  </head>
  <body>
    <script id="oreo-state" type="application/json">{initial_state}</script>
    <header class="topbar">
      <div>
        <h1>Oreo Cloud</h1>
        <p>{escape(route["url"])} · API {escape(api["bind"])}:{escape(str(api["port"]))}</p>
      </div>
      <div class="top-actions">
        <button id="monitor-toggle" type="button">Show Monitor</button>
        <button id="admin-toggle" type="button">Admin Mode</button>
      </div>
    </header>
    <main>
      <section class="summary" aria-label="System summary">
        <div><strong>{len(state["workloads"])}</strong><span>Workloads</span></div>
        <div><strong>{escape(str(exposure["cloudflare"]["enabled"]).lower())}</strong><span>Cloudflare enabled</span></div>
        <div><strong>{escape(str(funnel["observedEnabled"]).lower())}</strong><span>Funnel observed</span></div>
        <div><strong>{migrated}</strong><span>Migrated</span></div>
        <div><strong>{backup_plans}</strong><span>Backup plans</span></div>
      </section>
      <section class="alert">
        <strong>P0 exposure status</strong>
        <span>Funnel allowed in P0: {escape(str(funnel["allowedInP0"]).lower())}. Observed Funnel: {escape(str(funnel["observedEnabled"]).lower())}.</span>
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
      <section class="workloads">
        {workloads}
      </section>
      <section class="plan-grid">
        <article>
          <h2>Access Plan</h2>
          <p>Desired and effective access remain separate. Cloudflare states are planned until explicitly applied by policy.</p>
          <code>API {escape(api["bind"])}:{escape(str(api["port"]))}</code>
        </article>
        <article>
          <h2>Backups</h2>
          <p>{backup_plans} workloads have manifest-backed backup metadata. Backup runs remain blocked unless the workload manifest allows them.</p>
          <code>/srv/oreo-cloud/runtime/backups</code>
        </article>
        <article>
          <h2>Cloudflare Plan</h2>
          <p>Cloudflare is disabled. Quick tunnels and named tunnels are blocked in P0 until an explicit later phase changes policy.</p>
          <code>{escape(exposure["cloudflare"]["configPath"])}</code>
        </article>
        <article>
          <h2>Events</h2>
          <pre id="events">{events or "No audit events loaded."}</pre>
        </article>
        <article>
          <h2>System</h2>
          <p>Monitor refresh {escape(str(state["monitoring"]["refreshSeconds"]))}s. Dashboard remains view-only without admin mode.</p>
          <code>{escape(route["url"])}</code>
        </article>
      </section>
    </main>
    <script src="./app.js"></script>
  </body>
</html>
"""


CSS = r"""
:root {
  color-scheme: light;
  --bg: #f7f8fa;
  --surface: #ffffff;
  --surface-2: #eef1f4;
  --text: #182026;
  --muted: #61707d;
  --border: #d8dee5;
  --good: #0b6b4f;
  --good-bg: #ddf4ec;
  --warn: #8a5a00;
  --warn-bg: #fff0c2;
  --bad: #9a251f;
  --bad-bg: #ffe1de;
  --shadow: 0 1px 2px rgba(20, 30, 40, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
button, select {
  font: inherit;
}
button, .action {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: 6px;
  padding: 8px 10px;
  text-decoration: none;
  cursor: pointer;
}
button:hover, .action:hover { border-color: #9aa7b4; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: rgba(247, 248, 250, 0.94);
  backdrop-filter: blur(10px);
}
h1, h2, p { margin: 0; }
h1 { font-size: 22px; line-height: 1.1; }
h2 { font-size: 15px; }
.topbar p, .section-head span, .muted { color: var(--muted); }
.top-actions { display: flex; gap: 8px; flex-wrap: wrap; }
main {
  width: min(1440px, 100%);
  margin: 0 auto;
  padding: 20px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.summary div, .alert, .monitor, .workload, .plan-grid article {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow);
}
.summary div {
  padding: 14px;
}
.summary strong {
  display: block;
  font-size: 24px;
  line-height: 1;
}
.summary span, dt {
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0;
}
.alert {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 16px;
  background: var(--warn-bg);
  border-color: #ebc96e;
  color: #4a3700;
}
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin: 18px 0 10px;
}
.workloads {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.workload { padding: 14px; }
.workload-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.workload-head p { color: var(--muted); margin-top: 3px; }
code {
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--surface-2);
  color: #33414c;
  font-size: 12px;
  word-break: break-word;
}
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 12px 0;
}
.pill {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  border-radius: 999px;
  padding: 4px 8px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 12px;
}
.pill span {
  color: var(--muted);
}
.pill.good { background: var(--good-bg); color: var(--good); }
.pill.warn { background: var(--warn-bg); color: var(--warn); }
.pill.bad { background: var(--bad-bg); color: var(--bad); }
.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}
.facts div {
  min-width: 0;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}
.warning {
  margin-top: 12px;
  padding: 10px;
  border-radius: 6px;
  background: var(--warn-bg);
  color: #4a3700;
}
.actions, .admin-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.admin-row {
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}
.admin-row label {
  display: grid;
  gap: 4px;
  color: var(--muted);
}
.monitor { padding: 14px; margin-bottom: 16px; }
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.metric {
  padding: 12px;
  border-radius: 6px;
  background: var(--surface-2);
}
.bar {
  height: 8px;
  margin-top: 8px;
  border-radius: 999px;
  background: #d2dae2;
  overflow: hidden;
}
.bar span {
  display: block;
  height: 100%;
  background: #2c6fbb;
}
.plan-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 18px;
}
.plan-grid article { padding: 14px; }
pre {
  white-space: pre-wrap;
  margin: 10px 0 0;
  color: var(--muted);
}
@media (max-width: 820px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  main { padding: 14px; }
  .summary, .workloads, .plan-grid, .metrics-grid { grid-template-columns: 1fr; }
  .facts { grid-template-columns: 1fr; }
}
"""


JS = r"""
const state = JSON.parse(document.getElementById("oreo-state").textContent);
const monitorToggle = document.getElementById("monitor-toggle");
const monitorPanel = document.getElementById("monitor-panel");
const monitorStatus = document.getElementById("monitor-status");
const metricsEl = document.getElementById("metrics");
const adminToggle = document.getElementById("admin-toggle");
let monitorTimer = null;
let adminEnabled = false;

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
    const response = await fetch("./metrics.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`metrics.json ${response.status}`);
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
    monitorTimer = setInterval(fetchMetrics, Number(state.monitoring.refreshSeconds || 3) * 1000);
  }
}

function fillAdminControls() {
  document.querySelectorAll('select[data-action="privacy"]').forEach((select) => {
    select.innerHTML = state.privacyStates.map((item) => `<option value="${item}">${item}</option>`).join("");
    const workload = select.dataset.workload;
    const current = state.workloads.find((item) => item.id === workload)?.privacy?.privacy;
    if (current) select.value = current;
  });
  document.querySelectorAll('select[data-action="access"]').forEach((select) => {
    select.innerHTML = state.accessStates.map((item) => `<option value="${item}">${item}</option>`).join("");
    const workload = select.dataset.workload;
    const current = state.workloads.find((item) => item.id === workload)?.access?.desired;
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
  const preview = event.target.closest("[data-preview]");
  const apply = event.target.closest("[data-apply]");
  if (!preview && !apply) return;
  const workload = (preview || apply).dataset.preview || (preview || apply).dataset.apply;
  const mode = preview ? "preview" : "apply";
  window.alert(`${mode} for ${workload} requires the P0 control API phase.`);
});
"""


def main() -> int:
    state = merged_state()
    write(PUBLIC / "index.html", render_html(state))
    write(PUBLIC / "style.css", CSS.strip() + "\n")
    write(PUBLIC / "app.js", JS.strip() + "\n")
    print(f"Generated {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
