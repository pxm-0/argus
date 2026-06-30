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
    <title>Oreo Cloud Mission Control</title>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="./style.css">
  </head>
  <body>
    <script id="oreo-state" type="application/json">{initial_state}</script>
    <header class="topbar">
      <div>
        <h1>Oreo Cloud Mission Control</h1>
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
        <strong>Exposure control</strong>
        <span>Funnel allowed in P0: {funnel_allowed}. Observed Funnel: {funnel_observed}. Cloudflare: {cloudflare_state.lower()}.</span>
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
