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
    if value in {"active", "ok", "tailnet", "local", "migrated"}:
        return "good"
    if value in {"planned", "cloudflare-protected"}:
        return "info"
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
            if label == "Cloudflare" and href.endswith(".invalid"):
                actions.append(f'<span class="action disabled">{escape(label)} planned</span>')
            else:
                actions.append(f'<a class="action" href="{escape(href)}">{escape(label)}</a>')
    if not actions:
        actions.append('<span class="muted">No open URL configured</span>')

    return f"""
    <article
      class="workload"
      data-workload="{escape(wid)}"
      data-privacy="{escape(privacy.get("privacy", ""))}"
      data-access="{escape(access.get("effective", ""))}"
      data-migration="{escape(migration.get("status", ""))}"
    >
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
    cloudflare_state = "Enabled" if exposure["cloudflare"].get("enabled") else "Disabled"
    funnel_state = "Observed" if funnel.get("observedEnabled") else "Clear"
    funnel_allowed = "yes" if funnel.get("allowedInP0") else "no"
    funnel_observed = "yes" if funnel.get("observedEnabled") else "no"
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
        <div><strong>{cloudflare_state}</strong><span>Cloudflare</span></div>
        <div><strong>{funnel_state}</strong><span>Funnel</span></div>
        <div><strong>{migrated}</strong><span>Migrated</span></div>
        <div><strong>{backup_plans}</strong><span>Backup plans</span></div>
      </section>
      <section class="alert">
        <strong>P0 exposure status</strong>
        <span>Funnel allowed in P0: {funnel_allowed}. Observed Funnel: {funnel_observed}.</span>
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
  --bg: oklch(0.965 0.012 190);
  --panel: oklch(0.99 0.005 190);
  --panel-2: oklch(0.946 0.014 190);
  --ink: oklch(0.215 0.035 205);
  --muted: oklch(0.43 0.04 210);
  --faint: oklch(0.62 0.032 205);
  --border: oklch(0.85 0.026 195);
  --border-strong: oklch(0.7 0.05 195);
  --accent: oklch(0.43 0.12 187);
  --accent-ink: oklch(0.24 0.075 187);
  --accent-bg: oklch(0.92 0.052 187);
  --accent-border: oklch(0.76 0.08 187);
  --info: oklch(0.43 0.12 238);
  --info-ink: oklch(0.24 0.082 238);
  --info-bg: oklch(0.925 0.048 238);
  --info-border: oklch(0.77 0.075 238);
  --good: oklch(0.37 0.105 150);
  --good-bg: oklch(0.925 0.06 150);
  --good-border: oklch(0.75 0.09 150);
  --warn: oklch(0.43 0.112 72);
  --warn-bg: oklch(0.94 0.08 82);
  --warn-border: oklch(0.8 0.1 82);
  --bad: oklch(0.43 0.15 24);
  --bad-bg: oklch(0.935 0.058 24);
  --bad-border: oklch(0.78 0.08 24);
  --shadow: 0 1px 2px rgb(24 33 45 / 7%);
  --focus: 0 0 0 3px oklch(0.72 0.11 187 / 42%);
}
* { box-sizing: border-box; }
html { min-width: 320px; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
button, select {
  font: inherit;
}
button, .action {
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--ink);
  border-radius: 6px;
  min-height: 34px;
  padding: 7px 10px;
  text-decoration: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-weight: 650;
}
button:hover, .action:hover { border-color: var(--accent-border); background: var(--accent-bg); color: var(--accent-ink); }
button:focus-visible, .action:focus-visible, select:focus-visible { outline: 0; box-shadow: var(--focus); }
select {
  min-height: 34px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
  color: var(--ink);
  padding: 6px 8px;
}
.action.disabled {
  color: var(--muted);
  cursor: default;
  background: var(--panel-2);
}
.action.disabled:hover { border-color: var(--border); }
#monitor-toggle {
  background: var(--info-bg);
  border-color: var(--info-border);
  color: var(--info-ink);
}
#admin-toggle {
  background: var(--warn-bg);
  border-color: var(--warn-border);
  color: var(--warn);
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 14px 24px;
  border-bottom: 1px solid var(--accent-border);
  background: oklch(0.985 0.012 190 / 96%);
  backdrop-filter: blur(14px);
}
h1, h2, p { margin: 0; }
h1 {
  font-size: 20px;
  line-height: 1.1;
  letter-spacing: 0;
}
h2 {
  font-size: 15px;
  line-height: 1.25;
  letter-spacing: 0;
}
.topbar p, .section-head span, .muted { color: var(--muted); }
.top-actions { display: flex; gap: 8px; flex-wrap: wrap; }
main {
  width: min(1480px, 100%);
  margin: 0 auto;
  padding: 18px 24px 32px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--border);
}
.summary div, .alert, .monitor, .workload, .plan-grid article {
  background: var(--panel);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.summary div {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  padding: 14px 16px;
}
.summary div:nth-child(1) { background: var(--good-bg); }
.summary div:nth-child(2) { background: var(--info-bg); }
.summary div:nth-child(3) { background: var(--warn-bg); }
.summary div:nth-child(4) { background: var(--accent-bg); }
.summary div:nth-child(5) { background: oklch(0.94 0.045 128); }
.summary strong {
  display: block;
  font-size: 22px;
  line-height: 1;
  letter-spacing: 0;
}
.summary div:nth-child(1) strong { color: var(--good); }
.summary div:nth-child(2) strong { color: var(--info-ink); }
.summary div:nth-child(3) strong { color: var(--warn); }
.summary div:nth-child(4) strong { color: var(--accent-ink); }
.summary div:nth-child(5) strong { color: oklch(0.34 0.095 128); }
.summary span, dt {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0;
  font-weight: 700;
}
.alert {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 18px;
  background: var(--warn-bg);
  border-color: var(--warn-border);
  border-radius: 8px;
  color: oklch(0.28 0.06 72);
  box-shadow: none;
}
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin: 22px 0 10px;
}
.section-head h2 {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.section-head h2::before {
  content: "";
  width: 9px;
  height: 9px;
  border-radius: 3px;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-bg);
}
.workloads {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}
.workload {
  border-radius: 8px;
  padding: 16px;
  border-color: var(--border-strong);
}
.workload[data-privacy="unclassified"] {
  background: oklch(0.99 0.012 150);
  border-color: var(--good-border);
}
.workload[data-privacy="internal"] {
  background: oklch(0.99 0.013 187);
  border-color: var(--accent-border);
}
.workload[data-privacy="sensitive"] {
  background: oklch(0.988 0.018 82);
  border-color: var(--warn-border);
}
.workload[data-privacy="restricted"] {
  background: oklch(0.988 0.014 24);
  border-color: var(--bad-border);
}
.workload[data-migration="migrated"] .workload-head h2 {
  color: var(--good);
}
.workload[data-access="tailnet"] .workload-head h2,
.workload[data-access="local"] .workload-head h2 {
  color: var(--accent-ink);
}
.workload-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.workload-head p {
  color: var(--muted);
  margin-top: 4px;
  max-width: 72ch;
  text-wrap: pretty;
}
code {
  padding: 3px 6px;
  border-radius: 4px;
  background: oklch(0.93 0.018 205);
  color: oklch(0.29 0.06 205);
  font-size: 12px;
  word-break: break-word;
}
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 12px 0 14px;
}
.pill {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  border-radius: 999px;
  padding: 4px 9px;
  background: var(--panel-2);
  color: var(--ink);
  font-size: 12px;
  font-weight: 650;
  border: 1px solid transparent;
}
.pill span {
  color: currentColor;
  opacity: 0.72;
  font-weight: 700;
}
.pill.good { background: var(--good-bg); border-color: var(--good-border); color: var(--good); }
.pill.info { background: var(--info-bg); border-color: var(--info-border); color: var(--info-ink); }
.pill.warn { background: var(--warn-bg); border-color: var(--warn-border); color: var(--warn); }
.pill.bad { background: var(--bad-bg); border-color: var(--bad-border); color: var(--bad); }
.facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 0;
  margin: 0;
  border: 1px solid oklch(0.82 0.035 195);
  border-radius: 8px;
  overflow: hidden;
}
.facts div {
  min-width: 0;
  padding: 10px 12px;
  border-top: 0;
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: oklch(0.995 0.006 190);
}
dt { color: oklch(0.38 0.055 205); }
.facts div:nth-child(4n) {
  border-right: 0;
}
.facts div:nth-last-child(-n + 4) {
  border-bottom: 0;
}
dd {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
  font-weight: 650;
}
.warning {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  color: oklch(0.28 0.06 72);
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
.monitor {
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 18px;
  background: var(--info-bg);
  border-color: var(--info-border);
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.metric {
  padding: 12px;
  border-radius: 6px;
  background: oklch(0.985 0.012 238);
  border: 1px solid var(--info-border);
}
.metric strong { font-size: 12px; color: var(--muted); }
.metric p { margin-top: 4px; font-weight: 750; }
.bar {
  height: 8px;
  margin-top: 8px;
  border-radius: 999px;
  background: oklch(0.86 0.035 238);
  overflow: hidden;
}
.bar span {
  display: block;
  height: 100%;
  background: var(--info);
}
.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
  margin-top: 22px;
}
.plan-grid article {
  border-radius: 8px;
  padding: 14px;
  min-width: 0;
}
.plan-grid article:nth-child(1) {
  background: var(--info-bg);
  border-color: var(--info-border);
}
.plan-grid article:nth-child(2) {
  background: var(--good-bg);
  border-color: var(--good-border);
}
.plan-grid article:nth-child(3) {
  background: var(--warn-bg);
  border-color: var(--warn-border);
}
.plan-grid article:nth-child(4) {
  background: var(--accent-bg);
  border-color: var(--accent-border);
}
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
  font-size: 12px;
}
@media (max-width: 820px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  main { padding: 14px 14px 28px; }
  .summary, .metrics-grid { grid-template-columns: 1fr; }
  .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .facts div:nth-child(4n) { border-right: 1px solid var(--border); }
  .facts div:nth-child(2n) { border-right: 0; }
  .facts div:nth-last-child(-n + 4) { border-bottom: 1px solid var(--border); }
  .facts div:nth-last-child(-n + 2) { border-bottom: 0; }
}
@media (max-width: 520px) {
  .top-actions { width: 100%; }
  .top-actions button { flex: 1 1 auto; }
  .alert { align-items: flex-start; flex-direction: column; }
  .workload-head { flex-direction: column; }
  .facts { grid-template-columns: 1fr; }
  .facts div,
  .facts div:nth-child(2n),
  .facts div:nth-child(4n),
  .facts div:nth-last-child(-n + 4) {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }
  .facts div:last-child { border-bottom: 0; }
}
@media (prefers-reduced-motion: no-preference) {
  button, .action, .workload, .plan-grid article {
    transition: background-color 160ms ease, border-color 160ms ease, transform 160ms ease;
  }
  .workload:hover, .plan-grid article:hover {
    transform: translateY(-1px);
  }
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
