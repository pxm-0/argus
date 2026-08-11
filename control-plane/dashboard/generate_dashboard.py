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
from dashboard_assets import write_assets
from dashboard_prototypes import render_prototypes


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "control-plane" / "dashboard" / "public"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(line.rstrip() for line in content.splitlines()) + "\n")


def render_html() -> str:
    return f"""<!doctype html>
<html lang="en" class="no-js">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Argus</title>
    <meta name="theme-color" content="#0d1324">
    <link rel="icon" href="./favicon.svg" type="image/svg+xml">
    <link rel="icon" href="./favicon-32.png" sizes="32x32" type="image/png">
    <link rel="icon" href="./favicon-16.png" sizes="16x16" type="image/png">
    <link rel="apple-touch-icon" href="./apple-touch-icon.png">
    <link rel="manifest" href="./manifest.webmanifest">
    <script>document.documentElement.classList.remove("no-js"); const requestedTheme = new URLSearchParams(location.search).get("theme"); document.documentElement.dataset.theme = ["light", "dark"].includes(requestedTheme) ? requestedTheme : (localStorage.getItem("argus-theme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));</script>
    <link rel="stylesheet" href="./style.css">
  </head>
  <body>
    <noscript>
      <section class="no-js-state" aria-labelledby="no-js-title">
        <img src="./favicon.svg" alt="" width="48" height="48">
        <div><h1>Argus</h1><h2 id="no-js-title">JavaScript required</h2><p>Argus fails closed and shows no estate data or controls without JavaScript.</p></div>
      </section>
    </noscript>
    <div class="app-shell">
      <aside class="nav-rail" aria-label="Primary navigation">
        <a class="brand" href="#overview" aria-label="Argus overview"><img src="./favicon.svg" alt="" width="40" height="40"></a>
        <nav>
          <a href="#overview" aria-current="page">Overview</a>
          <a href="#workloads-heading">Workloads</a>
          <a href="#estate-coverage">Coverage</a>
        </nav>
        <div class="private-state"><i aria-hidden="true"></i><span>Private<br>control plane</span></div>
      </aside>
      <div class="app-main">
    <header class="topbar">
      <div class="title-lockup">
        <h1>Argus</h1>
        <p id="route-summary">Loading estate evidence</p>
      </div>
      <div class="top-actions" aria-label="Operator tools">
        <input id="admin-token" type="password" autocomplete="off" placeholder="bootstrap credential" hidden>
        <button class="primary-action" id="workload-discover" type="button">Refresh estate</button>
        <button class="utility-action" id="monitor-toggle" type="button">Monitor</button>
        <button class="utility-action" id="theme-toggle" type="button" aria-pressed="false">Theme</button>
        <div class="session-control" id="session-control" data-state="checking">
          <i class="session-signal" aria-hidden="true"></i>
          <span class="session-copy" role="status" aria-live="polite" aria-atomic="true">
            <strong id="session-status">Checking session</strong>
            <small id="session-detail">Confirming private operator session.</small>
          </span>
          <button id="admin-toggle" type="button" disabled>Checking</button>
        </div>
      </div>
    </header>
    <main id="overview">
      <section class="summary" id="summary" aria-label="System summary"></section>
      <section class="alert" id="exposure-alert">
        <strong>Exposure control</strong>
        <span>loading exposure state</span>
      </section>
      <section class="evidence-state" id="evidence-state" aria-labelledby="evidence-state-title" aria-live="polite">
        <div class="section-head">
          <div><p class="eyebrow">Evidence gate</p><h2 id="evidence-state-title">Estate completeness</h2></div>
          <span id="evidence-state-label" class="state-badge info">Loading</span>
        </div>
        <div id="evidence-state-body">Loading estate evidence.</div>
      </section>
      <section class="command-panel" id="command-panel" tabindex="-1" aria-labelledby="command-title" aria-describedby="command-summary" hidden>
        <header class="command-header">
          <div class="command-heading">
            <span class="result-badge info" id="command-status">Result</span>
            <div>
              <p class="eyebrow">Command result</p>
              <h2 id="command-title">Command completed</h2>
            </div>
          </div>
          <button id="command-close" type="button" aria-label="Close command result">Close</button>
        </header>
        <p class="command-summary" id="command-summary"></p>
        <dl class="command-highlights" id="command-highlights"></dl>
        <div class="command-assurance" id="command-assurance"></div>
        <details class="command-details" id="command-details">
          <summary>Technical details <span>Raw response</span></summary>
          <pre id="command-output"></pre>
        </details>
        <div id="command-actions" class="command-actions"></div>
        <p class="sr-only" id="command-announcer" aria-live="polite" aria-atomic="true"></p>
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
        <span>Placement, health, access, and evidence freshness</span>
      </section>
      <section class="workloads" id="workloads"></section>
      <section class="instrument-head" id="estate-coverage">
        <div><h2>Estate coverage</h2></div>
        <p>Compare trust-domain placement and access evidence. This view remains read-only.</p>
      </section>
      <section class="topology" id="topology" aria-label="Estate coverage by trust domain"></section>
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
const sessionControl = document.getElementById("session-control");
const sessionStatus = document.getElementById("session-status");
const sessionDetail = document.getElementById("session-detail");
const routeSummary = document.getElementById("route-summary");
const summaryEl = document.getElementById("summary");
const exposureAlert = document.getElementById("exposure-alert");
const evidenceStateEl = document.getElementById("evidence-state");
const evidenceStateLabelEl = document.getElementById("evidence-state-label");
const evidenceStateBodyEl = document.getElementById("evidence-state-body");
const topologyEl = document.getElementById("topology");
const workloadsEl = document.getElementById("workloads");
const eventsEl = document.getElementById("events");
const commandPanel = document.getElementById("command-panel");
const commandOutput = document.getElementById("command-output");
const commandTitle = document.getElementById("command-title");
const commandStatus = document.getElementById("command-status");
const commandSummary = document.getElementById("command-summary");
const commandHighlights = document.getElementById("command-highlights");
const commandAssurance = document.getElementById("command-assurance");
const commandDetails = document.getElementById("command-details");
const commandActions = document.getElementById("command-actions");
const commandClose = document.getElementById("command-close");
const commandAnnouncer = document.getElementById("command-announcer");
let monitorTimer = null;
let adminEnabled = false;
let csrfToken = "";
let operatorIdentity = "";
let operatorSessionState = "checking";
let operatorSessionReason = "";
let operatorSession = null;
let selectedTopologyId = null;
let lastCommandTrigger = null;
const activeOperationPolls = new Set();
const operationCache = new Map();

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

const SESSION_REASON_STATES = Object.freeze({
  "identity-missing": "unauthenticated",
  "operator-disabled": "unauthenticated",
  "cookie-missing": "unauthenticated",
  "session-not-found": "unauthenticated",
  "session-expired": "expired",
  "session-revoked": "expired",
  "session-store-unavailable": "unavailable"
});

function sessionPresentation(stateName, reason, session) {
  if (stateName === "checking") {
    return { status: "Checking session", detail: "Confirming private operator session.", action: "Checking" };
  }
  if (stateName === "authenticated") {
    const detail = session?.expiresAt ? `Session active until ${session.expiresAt}.` : "Operator session active.";
    return { status: "Signed in", detail, action: "Log out" };
  }
  if (stateName === "expired") {
    const revoked = reason === "session-revoked";
    return {
      status: revoked ? "Session revoked" : "Session expired",
      detail: revoked ? "This session was revoked. Sign in again." : "The session reached its declared expiry. Sign in again.",
      action: "Sign in"
    };
  }
  if (stateName === "unavailable") {
    if (reason === "csrf-missing") {
      return {
        status: "Mutation protection missing",
        detail: "The session is readable, but its CSRF cookie is missing. Sign in again before making changes.",
        action: "Sign in"
      };
    }
    return {
      status: "Session unavailable",
      detail: "Argus could not verify the existing session. It was not treated as a logout.",
      action: "Retry"
    };
  }
  if (reason === "identity-missing") {
    return { status: "Tailnet identity missing", detail: "Open Argus through the private Tailscale route.", action: "Retry" };
  }
  if (reason === "operator-disabled") {
    return { status: "Operator access disabled", detail: "This Tailnet identity is not enabled for Argus.", action: "Retry" };
  }
  return {
    status: "Sign in required",
    detail: reason === "session-not-found" ? "The browser session is no longer recognized." : "No active Argus session was found.",
    action: "Sign in"
  };
}

function setOperatorSessionState(nextState, { reason = "", session = null } = {}) {
  const allowed = ["checking", "authenticated", "unauthenticated", "expired", "unavailable"];
  operatorSessionState = allowed.includes(nextState) ? nextState : "unavailable";
  operatorSessionReason = reason;
  operatorSession = operatorSessionState === "authenticated" ? session : null;
  const presentation = sessionPresentation(operatorSessionState, operatorSessionReason, operatorSession);
  sessionControl.dataset.state = operatorSessionState;
  sessionStatus.textContent = presentation.status;
  sessionDetail.textContent = presentation.detail;
  adminToggle.textContent = presentation.action;
  adminToggle.disabled = operatorSessionState === "checking";
  if (operatorSessionState === "authenticated") {
    csrfToken = cookieValue("argus_csrf");
    operatorIdentity = operatorSession?.identity || "";
    setAdmin(true);
  } else {
    csrfToken = "";
    operatorIdentity = "";
    setAdmin(false);
  }
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

function commandResultTone(title, payload) {
  const stateValue = typeof payload === "object" && payload ? payload.state || payload.status || "" : "";
  const value = `${title} ${stateValue}`.toLowerCase();
  if (/(fail|error|blocked|unavailable|rejected)/.test(value)) return ["Failed", "bad"];
  if (/(awaiting|pending|queued|running|required|preview)/.test(value)) return ["Attention", "warn"];
  if (/(success|succeeded|complete|completed|approved|authenticated|cancelled|healthy)/.test(value)) return ["Success", "good"];
  return ["Result", "info"];
}

function commandResultSummary(title, payload) {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return `${title} completed.`;
  if (payload.redacted_summary) return payload.redacted_summary;
  if (payload.error) return payload.error;
  if (payload.detail) return payload.detail;
  if (payload.message) return payload.message;
  if (payload.allowed === true) return payload.reason ? `Allowed by policy: ${payload.reason}.` : "Allowed by current policy.";
  if (payload.allowed === false) return payload.reason ? `Blocked by policy: ${payload.reason}.` : "Blocked by current policy.";
  if (Array.isArray(payload.newComposeProjects)) {
    const count = payload.newComposeProjects.length;
    return count ? `${count} unregistered Compose ${count === 1 ? "project" : "projects"} found.` : "No unregistered Compose projects found.";
  }
  if (payload.state) return `Operation is ${String(payload.state).replaceAll("-", " ")}.`;
  return `${title} completed.`;
}

function commandResultHighlights(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "";
  const fields = [
    ["State", payload.state || payload.status],
    ["Decision", payload.allowed === true ? "Allowed" : payload.allowed === false ? "Blocked" : ""],
    ["Operation", payload.operation_type || payload.operationType],
    ["Workload", payload.workload_id || payload.workloadId],
    ["Trust domain", payload.trust_domain || payload.trustDomain],
    ["Error class", payload.error_class || payload.errorClass],
    ["Operation ID", payload.operation_id || payload.operationId],
    ["Identity", payload.identity],
    ["Policy", payload.policy_version || payload.policyVersion],
    ["Created", payload.created_at || payload.createdAt],
    ["Expires", payload.expiresAt]
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  return fields.slice(0, 8).map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
}

function commandResultAssurance(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "";
  const rows = [];
  const migrationReadiness = payload.migrationReadiness || payload.redactedResult;
  const digestValue = payload.previewDigest || payload.preview_digest;
  const revision = payload.expectedRevision || payload.expected_revision;
  if (payload.reason) rows.push(["Policy decision", payload.reason]);
  if (payload.expectedBlastRadius) rows.push(["Expected impact", payload.expectedBlastRadius]);
  if (payload.rollbackBehavior) rows.push(["Rollback", payload.rollbackBehavior]);
  if (digestValue) rows.push(["Preview digest", digestValue]);
  if (revision) rows.push(["Canonical revision", revision]);
  if (Array.isArray(payload.healthChecks) && payload.healthChecks.length) {
    rows.push(["Health checks", payload.healthChecks]);
  }
  if (migrationReadiness?.operation === "migration-preflight" || payload.migrationReadiness) {
    rows.push([
      "Migration readiness",
      migrationReadiness.readyForCutover ? "Ready for a separately approved cutover" : "Blocked"
    ]);
    if (Array.isArray(migrationReadiness.blockers) && migrationReadiness.blockers.length) {
      rows.push(["Blocking conditions", migrationReadiness.blockers]);
    }
  }
  return rows.map(([label, value]) => {
    const content = Array.isArray(value)
      ? `<ul>${value.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : `<span>${escapeHtml(value)}</span>`;
    return `<div class="assurance-row"><strong>${escapeHtml(label)}</strong>${content}</div>`;
  }).join("");
}

function showCommandResult(title, payload) {
  const wasHidden = commandPanel.hidden;
  const [status, tone] = commandResultTone(title, payload);
  const structured = typeof payload === "object" && payload !== null;
  if (wasHidden) lastCommandTrigger = document.activeElement;
  commandTitle.textContent = title;
  commandStatus.textContent = status;
  commandStatus.className = `result-badge ${tone}`;
  commandSummary.textContent = commandResultSummary(title, payload);
  commandHighlights.innerHTML = commandResultHighlights(payload);
  commandHighlights.hidden = !commandHighlights.innerHTML;
  commandAssurance.innerHTML = commandResultAssurance(payload);
  commandAssurance.hidden = !commandAssurance.innerHTML;
  commandOutput.textContent = structured ? JSON.stringify(payload, null, 2) : String(payload ?? "");
  commandDetails.hidden = !structured;
  commandDetails.open = false;
  commandActions.innerHTML = "";
  commandPanel.hidden = false;
  commandAnnouncer.textContent = `${status}: ${title}. ${commandSummary.textContent}`;
  if (wasHidden) commandPanel.focus({ preventScroll: true });
}

function renderDiscoveryCandidates(candidates) {
  commandActions.innerHTML = (candidates || [])
    .map((id) => `<button type="button" data-register="${escapeHtml(id)}">Register ${escapeHtml(id)}</button>`)
    .join("");
}

function tokenFor() {
  return adminTokenInput.value;
}

function cookieValue(name) {
  const prefix = `${name}=`;
  const item = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

function bootstrapNonce() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function selectedValue(row, selector) {
  return row?.querySelector(selector)?.value || "";
}

async function apiPost(endpoint, body, extraHeaders = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...extraHeaders
  };
  const cookieCsrf = cookieValue("argus_csrf");
  if (!cookieCsrf && endpoint !== "/api/session/exchange") {
    setOperatorSessionState("unavailable", { reason: "csrf-missing" });
    return {
      ok: false,
      status: 403,
      payload: { error: "Mutation protection is unavailable. Sign in again before making changes." }
    };
  }
  if (cookieCsrf && endpoint !== "/api/session/exchange") headers["X-Argus-CSRF"] = cookieCsrf;
  if (/\/api\/workloads\/[^/]+\/operations$/.test(endpoint)) headers["Idempotency-Key"] = crypto.randomUUID();
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
  const result = await apiPost(
    "/api/session/exchange",
    { bootstrapToken: credential },
    { "X-Argus-CSRF-Bootstrap": bootstrapNonce() }
  );
  adminTokenInput.value = "";
  if (!result.ok) throw new Error(result.payload.error || `authentication ${result.status}`);
  if (!cookieValue("argus_csrf")) {
    setOperatorSessionState("unavailable", { reason: "csrf-missing" });
    throw new Error("Authentication completed without mutation protection. Sign in again.");
  }
  setOperatorSessionState("authenticated", { session: result.payload });
  return result.payload;
}

async function ensureStepUp() {
  const response = await fetch("/api/session", { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) {
    showCommandResult("Operator session required", "Authenticate again before creating a mutation.");
    return false;
  }
  const session = await response.json();
  csrfToken = cookieValue("argus_csrf");
  if (session.stepUpValid) return true;
  const credential = tokenFor();
  if (!credential) {
    showCommandResult("Step-up required", "Enter the bootstrap credential in the operator field, then retry the mutation.");
    return false;
  }
  const result = await apiPost("/api/session/step-up", { bootstrapToken: credential });
  adminTokenInput.value = "";
  if (!result.ok) {
    showCommandResult("Step-up failed", result.payload);
    return false;
  }
  return true;
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

const EVIDENCE_PRESENTATIONS = Object.freeze({
  loading: { label: "Loading", tone: "info", headline: "Loading estate evidence", detail: "Waiting for the private evidence summary.", action: "Review coverage" },
  empty: { label: "Empty", tone: "info", headline: "No estate evidence configured", detail: "The dashboard has no configured observation repository to reconcile.", action: "Review coverage" },
  error: { label: "Error", tone: "bad", headline: "Estate evidence unavailable", detail: "The private evidence summary could not be loaded. No action is authorized.", action: "Review coverage" },
  partial: { label: "Partial", tone: "warn", headline: "Estate evidence is incomplete", detail: "Some sources or workload identities still need evidence before review can finish.", action: "Review coverage" },
  stale: { label: "Stale", tone: "warn", headline: "Estate evidence is stale", detail: "One or more source observations are outside the freshness window.", action: "Review coverage" },
  conflict: { label: "Conflict", tone: "bad", headline: "Estate identity conflict", detail: "The same workload evidence maps to incompatible trust-domain identities.", action: "Review coverage" },
  complete: { label: "Complete", tone: "good", headline: "Estate evidence is complete", detail: "All reconciled workload identities are known and the configured sources are fresh.", action: "Review coverage" }
});

function safeEvidenceToken(value) {
  const token = String(value ?? "");
  return /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(token) ? token : "redacted";
}

function reconciliationBlockerLabel(blocker) {
  const labels = [safeEvidenceToken(blocker?.code || "unclassified")];
  if (blocker?.sourceId) labels.push(`source ${safeEvidenceToken(blocker.sourceId)}`);
  if (blocker?.workloadId) labels.push(`workload ${safeEvidenceToken(blocker.workloadId)}`);
  if (blocker?.trustDomain) labels.push(`domain ${safeEvidenceToken(blocker.trustDomain)}`);
  return labels.join(" · ");
}

function boundedCount(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.min(9999, Math.floor(number)) : 0;
}

function reconciliationState(reconciliation) {
  if (!reconciliation) return "loading";
  if (reconciliation.status === "unavailable") return "error";
  const coverage = reconciliation.coverage || {};
  const workloads = Array.isArray(reconciliation.workloads) ? reconciliation.workloads : [];
  const states = new Set(workloads.map((workload) => workload?.state).filter(Boolean));
  const sources = Array.isArray(coverage.sources) ? coverage.sources : [];
  if (reconciliation.status === "empty" || coverage.status === "not-configured" || (coverage.configuredSources === 0 && !workloads.length)) return "empty";
  if (states.has("conflicting")) return "conflict";
  if (states.has("stale") || sources.some((source) => source?.state === "stale")) return "stale";
  if (reconciliation.status === "complete" && coverage.status === "complete" && workloads.length && reconciliation.safeToMoveWorkloads === true && workloads.every((workload) => workload?.state === "known")) return "complete";
  return "partial";
}

function renderEvidenceState(reconciliation = state?.reconciliation) {
  const stateId = reconciliationState(reconciliation);
  const presentation = EVIDENCE_PRESENTATIONS[stateId];
  const coverage = reconciliation?.coverage || {};
  const workloads = Array.isArray(reconciliation?.workloads) ? reconciliation.workloads : [];
  const sources = Array.isArray(coverage.sources) ? coverage.sources : [];
  const blockers = Array.isArray(reconciliation?.blockers) ? reconciliation.blockers : [];
  const sourceMarkup = sources.length
    ? `<ul class="evidence-state-sources">${sources.slice(0, 8).map((source) => `<li><span>${escapeHtml(safeEvidenceToken(source?.sourceId))}</span><strong>${escapeHtml(safeEvidenceToken(source?.state || "unknown"))}</strong></li>`).join("")}</ul>`
    : `<p class="evidence-state-empty">No source rows are available.</p>`;
  const blockerMarkup = blockers.length
    ? `<details class="evidence-state-blockers"><summary>${boundedCount(blockers.length)} blocker${blockers.length === 1 ? "" : "s"}</summary><ul>${blockers.slice(0, 6).map((blocker) => `<li>${escapeHtml(reconciliationBlockerLabel(blocker))}</li>`).join("")}</ul></details>`
    : `<p class="evidence-state-empty">No reconciliation blockers reported.</p>`;
  evidenceStateEl.dataset.state = stateId;
  evidenceStateLabelEl.className = `state-badge ${presentation.tone}`;
  evidenceStateLabelEl.textContent = presentation.label;
  evidenceStateBodyEl.innerHTML = `
    <div class="evidence-state-copy"><strong>${presentation.headline}</strong><p>${presentation.detail}</p><a class="action evidence-action" href="#estate-coverage">${presentation.action}</a></div>
    <dl class="evidence-state-meta"><div><dt>Sources</dt><dd>${boundedCount(coverage.freshSources)} fresh / ${boundedCount(coverage.configuredSources)} configured</dd></div><div><dt>Workloads</dt><dd>${boundedCount(workloads.length)} reconciled</dd></div><div><dt>Mutation authority</dt><dd>None granted</dd></div></dl>
    <div class="evidence-state-detail"><div><p class="eyebrow">Source coverage</p>${sourceMarkup}</div><div><p class="eyebrow">Blockers</p>${blockerMarkup}</div></div>`;
}

function renderSummary() {
  const workloads = state?.workloads || [];
  const exposure = state?.exposure?.providers || {};
  const topology = state?.topology || {};
  const topologySummary = topology.summary || {};
  const funnel = exposure?.tailscale?.funnel || {};
  const cloudflareState = exposure?.cloudflare?.enabled ? "Enabled" : "Disabled";
  const exceptions = Number(topologySummary.accessDrift || 0) + Number(topologySummary.unresolvedClassifications || 0);
  const privateExposure = !funnel.observedEnabled && !exposure?.cloudflare?.enabled;
  summaryEl.innerHTML = [
    ["Exceptions", exceptions],
    ["Workloads", workloads.length],
    ["Trust domains", (topology.domains || []).filter((domain) => domain.id !== "management").length],
    ["Agents available", Number(topologySummary.domainAgentsAvailable || 0)],
    ["Exposure", privateExposure ? "Private" : "Review"]
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
  const controlBlocked = !selected.agentAvailable;
  const verdict = controlBlocked ? "Controls are blocked until the trust-domain agent is available." : "Controls execute through a typed, scoped trust-domain agent.";
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
      <div class="control-verdict ${controlBlocked ? "blocked" : ""}"><strong>${controlBlocked ? "Agent unavailable" : "Domain agent available"}</strong><span>${escapeHtml(verdict)}</span></div>
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

function observedAccessEvidence(workload) {
  const bindings = Array.isArray(workload.network?.observedBindings)
    ? workload.network.observedBindings.map(String)
    : [];
  const observations = [];
  if (workload.routes?.tailnet?.enabled) observations.push("tailnet route");
  if (bindings.some((item) => item.includes("0.0.0.0:") || item.includes("[::]:"))) {
    observations.push("host-wide binding");
  } else if (bindings.some((item) => item.includes("127.0.0.1:"))) {
    observations.push("loopback binding");
  } else if (bindings.length) {
    observations.push(`${bindings.length} runtime ${bindings.length === 1 ? "binding" : "bindings"}`);
  }
  return observations.join(" + ") || "none recorded";
}

function evidenceFreshness(value) {
  if (!value) return "never recorded";
  const instant = Date.parse(value);
  if (!Number.isFinite(instant)) return String(value);
  const seconds = Math.max(0, Math.floor((Date.now() - instant) / 1000));
  if (seconds < 60) return "less than 1m old";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m old`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h old`;
  return `${Math.floor(seconds / 86400)}d old`;
}

function operationBlockers({
  agentAvailable,
  logsAllowed,
  restartAllowed,
  backupAllowed,
  migrationAllowed,
  migrationStatus
}) {
  const blockers = [];
  if (!agentAvailable) blockers.push("All commands: the trust-domain agent is unavailable.");
  if (!logsAllowed) blockers.push("Logs preview: disabled by the workload manifest.");
  if (!restartAllowed) blockers.push("Restart: disabled by the workload manifest.");
  if (!backupAllowed) blockers.push("Backup: no approved backup plan in the workload manifest.");
  if (!["planned", "rolled-back"].includes(migrationStatus)) {
    blockers.push(`Migration preflight: status ${migrationStatus || "unknown"} is not a migration candidate.`);
  } else if (!migrationAllowed) {
    blockers.push("Migration preflight: disabled by the workload manifest.");
  }
  return blockers;
}

function renderWorkloadReconciliation(workloadId) {
  const row = state?.reconciliation?.workloads?.find((item) => item.id === workloadId);
  if (!row) {
    return `<section class="workload-reconciliation" aria-label="${escapeHtml(workloadId)} reconciliation evidence"><div><p class="eyebrow">D5 evidence</p><strong>Unavailable</strong><p>No sanitized reconciliation row is available for this workload.</p></div><span class="state-badge info">Incomplete</span></section>`;
  }
  const sources = Array.isArray(row.matchedSourceIds) ? row.matchedSourceIds.slice(0, 6).map((sourceId) => safeEvidenceToken(sourceId)) : [];
  const blockers = Array.isArray(row.blockers) ? row.blockers.slice(0, 4) : [];
  const stateId = safeEvidenceToken(row.state || "incomplete");
  const blockerText = blockers.length ? blockers.map(reconciliationBlockerLabel).join(" · ") : "No row blockers reported";
  return `<section class="workload-reconciliation" aria-label="${escapeHtml(workloadId)} reconciliation evidence"><div><p class="eyebrow">D5 evidence</p><strong>${escapeHtml(stateId)}</strong><p>${sources.length ? `Matched source${sources.length === 1 ? "" : "s"}: ${escapeHtml(sources.join(", "))}.` : "No matching source identity."} ${escapeHtml(blockerText)}.</p></div><dl><div><dt>Mutation authority</dt><dd>None granted</dd></div><div><dt>Evidence digests</dt><dd>${boundedCount(Array.isArray(row.evidenceDigests) ? row.evidenceDigests.length : 0)} recorded</dd></div></dl></section>`;
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
  const agentAvailable = Boolean(topologyNode.agentAvailable);
  const sandboxReconcileOnly = workload.actions?.sandboxReconcileOnly === true;
  const healthAllowed = !sandboxReconcileOnly;
  const accessAllowed = !sandboxReconcileOnly;
  const logsAllowed = Boolean(operations.logsAllowed || operations.logs?.allowed);
  const restartAllowed = Boolean(operations.restartAllowed || operations.restart?.allowed);
  const backupAllowed = Boolean(operations.backupAllowed || operations.backup?.allowed || backup.backupAllowed);
  const migrationAllowed = (
    operations.migrationPreflightAllowed === true
    || operations.migrationPreflight?.allowed === true
  );
  const migrationStatus = String(migration.status || "");
  const migrationCandidate = ["planned", "rolled-back"].includes(migrationStatus);
  const desiredAccess = access.desired || "-";
  const effectiveAccess = access.effective || "-";
  const accessDrift = desiredAccess !== effectiveAccess;
  const healthEvidenceAt = migration.lastHealthCheck || "";
  const blockers = operationBlockers({
    agentAvailable,
    logsAllowed,
    restartAllowed,
    backupAllowed,
    migrationAllowed,
    migrationStatus
  });
  return `
    <article
      class="workload"
      data-workload="${escapeHtml(id)}"
      data-privacy="${escapeHtml(privacy.privacy || "")}"
      data-access="${escapeHtml(access.effective || "")}"
      data-migration="${escapeHtml(migration.status || "")}"
    >
      <div class="workload-overview">
        <span class="workload-identity"><strong>${escapeHtml(workload.name || id)}</strong><small>${escapeHtml(id)}</small></span>
        <span data-label="Trust domain"><strong>${escapeHtml(topologyNode.trustDomain || "legacy-rootful")}</strong></span>
        <span data-label="Health"><strong>${health.enabled ? "Configured" : "Unknown"}</strong></span>
        <span data-label="Effective access"><strong>${escapeHtml(effectiveAccess)}</strong><small>${accessDrift ? "Drift from declared access" : "Aligned"}</small></span>
        <span data-label="Evidence"><strong data-health-freshness="${escapeHtml(id)}">${escapeHtml(evidenceFreshness(healthEvidenceAt))}</strong></span>
        <a class="inspect-action" href="#/workloads/${encodeURIComponent(id)}" data-open-workload="${escapeHtml(id)}">Inspect</a>
      </div>
      <div class="workload-detail" data-workload-detail="${escapeHtml(id)}" hidden>
      <div class="workload-head">
        <div>
          <h2>${escapeHtml(workload.name || id)}</h2>
          <p>${escapeHtml(workload.description || "")}</p>
        </div>
        <div class="detail-heading-actions"><code>${escapeHtml(id)}</code><a class="detail-close" href="#workloads-heading" aria-label="Close ${escapeHtml(workload.name || id)} details">Close</a></div>
      </div>
      <div class="workload-status">
        <div class="pills" aria-label="Primary workload state">
        ${pill("life", workload.lifecycle)}
        ${pill("privacy", privacy.privacy)}
        ${pill("effective", access.effective)}
        ${pill("migration", migration.status)}
        </div>
        <div class="workload-context" aria-label="Access and control evidence">
          <span>Declared access<strong>${escapeHtml(desiredAccess)}</strong></span>
          <span>Observed access<strong>${escapeHtml(observedAccessEvidence(workload))}</strong></span>
          <span>Effective access<strong>${escapeHtml(effectiveAccess)}</strong></span>
          <span class="${accessDrift ? "drift" : ""}">Alignment<strong>${accessDrift ? "Drift detected" : "Aligned"}</strong></span>
          <span>Health evidence<strong data-health-freshness="${escapeHtml(id)}">${escapeHtml(evidenceFreshness(healthEvidenceAt))}</strong></span>
          <span>Trust domain<strong>${escapeHtml(topologyNode.trustDomain || "legacy-rootful")}</strong></span>
        </div>
      </div>
      ${renderWorkloadReconciliation(id)}
      ${error ? `<details class="workload-notice"><summary>Access requires reconciliation</summary><p>${escapeHtml(error)}</p></details>` : ""}
      <details class="workload-evidence">
        <summary><span>Technical evidence</span><small>12 fields</small></summary>
        <div class="fact-groups">
          <section>
            <h3>Runtime</h3>
            <dl class="facts">
              <div><dt>Type</dt><dd>${escapeHtml(runtime.type || "-")}</dd></div>
              <div><dt>Compose project</dt><dd>${escapeHtml(runtime.composeProject || runtime.compose?.project || "-")}</dd></div>
              <div><dt>Internal port</dt><dd>${escapeHtml(network.internalPort || "-")}</dd></div>
              <div><dt>Legacy path</dt><dd>${escapeHtml(workload.paths?.legacy || "-")}</dd></div>
            </dl>
          </section>
          <section>
            <h3>Reachability</h3>
            <dl class="facts">
              <div><dt>Health</dt><dd>${escapeHtml(healthLabel)} ${escapeHtml(health.expectedStatus || "")}</dd></div>
              <div><dt>Last health</dt><dd>${escapeHtml(migration.lastHealthCheck || "-")}</dd></div>
              <div><dt>Local URL</dt><dd>${escapeHtml(urls.local || "-")}</dd></div>
              <div><dt>Tailnet URL</dt><dd>${escapeHtml(urls.tailnet || "-")}</dd></div>
            </dl>
          </section>
          <section>
            <h3>Controls</h3>
            <dl class="facts">
              <div><dt>Cloudflare</dt><dd>${escapeHtml(cloudflare.mode || "disabled")}</dd></div>
              <div><dt>Operations</dt><dd>logs ${escapeHtml(logsAllowed)}, restart ${escapeHtml(restartAllowed)}</dd></div>
              <div><dt>Backup target</dt><dd>${escapeHtml(backup.destination || "-")}</dd></div>
              <div><dt>Last event</dt><dd>${escapeHtml(lastEvent.action || "-")} ${escapeHtml(lastEvent.result || "")}</dd></div>
            </dl>
          </section>
        </div>
      </details>
      <section class="workload-controls" aria-label="${escapeHtml(id)} controls">
        <div class="control-head">
          <div><p class="control-label">Operations</p><p class="agent-state ${agentAvailable ? "available" : "offline"}">${agentAvailable ? "Domain agent available" : "Domain agent offline"}</p></div>
          <div class="workload-links">${workloadActions(urls)}</div>
        </div>
        <div class="operation-row">
          <span class="control-label">Inspect</span>
          <button type="button" data-operation="health-preview" data-workload="${escapeHtml(id)}" ${healthAllowed && agentAvailable ? "" : "disabled"}>Refresh health</button>
          <button type="button" data-operation="logs-preview" data-workload="${escapeHtml(id)}" ${logsAllowed && agentAvailable ? "" : "disabled"}>Logs preview</button>
        </div>
        <details class="more-operations">
          <summary>More operations</summary>
          <div class="operation-row">
            <button type="button" data-operation="restart-preview" data-workload="${escapeHtml(id)}" ${restartAllowed && agentAvailable ? "" : "disabled"}>Restart plan</button>
            <button type="button" data-operation="backup-preview" data-workload="${escapeHtml(id)}" ${backupAllowed && agentAvailable ? "" : "disabled"}>Backup plan</button>
            <button type="button" data-operation="migration-preflight" data-workload="${escapeHtml(id)}" ${migrationAllowed && migrationCandidate && agentAvailable ? "" : "disabled"}>Run migration preflight</button>
          </div>
        </details>
        ${blockers.length ? `<details class="operation-blockers"><summary>${blockers.length} blocking ${blockers.length === 1 ? "condition" : "conditions"}</summary><ul aria-label="Disabled operation reasons">${blockers.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></details>` : ""}
        <div class="operation-history" data-operation-history="${escapeHtml(id)}" aria-live="polite">
          <div class="history-head"><strong>Durable history</strong><span>Loading</span></div>
        </div>
      </section>
      <div class="admin-row" hidden>
        <div class="admin-heading"><strong>Mutation controls</strong><span>Step-up and typed confirmation required</span></div>
        <label>Access <select data-action="access" data-workload="${escapeHtml(id)}" ${accessAllowed ? "" : "disabled"}></select></label>
        <label>Confirm <input type="text" autocomplete="off" data-confirm="${escapeHtml(id)}" placeholder="${escapeHtml(id)}"></label>
        <button type="button" data-preview="${escapeHtml(id)}" ${accessAllowed && agentAvailable ? "" : "disabled"}>Preview</button>
        <button type="button" data-apply="${escapeHtml(id)}" ${accessAllowed && agentAvailable ? "" : "disabled"}>Apply</button>
        <button type="button" data-operation="restart-apply" data-workload="${escapeHtml(id)}" ${restartAllowed && agentAvailable ? "" : "disabled"}>Restart apply</button>
        <button type="button" data-operation="backup-apply" data-workload="${escapeHtml(id)}" ${backupAllowed && agentAvailable ? "" : "disabled"}>Backup apply</button>
      </div>
      </div>
    </article>
  `;
}

function renderPlans() {
  const route = state?.routes?.dashboard || {};
  const api = state?.routes?.api || {};
  const exposure = state?.exposure?.providers || {};
  const monitoring = state?.monitoring || {};
  const workloads = state?.workloads || [];
  const backupPlans = workloads.filter((item) => item.backup?.status).length;
  const healthEvidence = workloads.map((item) => item.migration?.lastHealthCheck).filter((value) => Number.isFinite(Date.parse(value))).sort();
  routeSummary.textContent = `${workloads.length} workloads · oldest evidence ${evidenceFreshness(healthEvidence[0] || "")}`;
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
  renderEvidenceState();
  renderSummary();
  renderTopology();
  workloadsEl.innerHTML = (state.workloads || []).map(renderWorkload).join("");
  renderPlans();
  renderEvents();
  syncWorkloadRoute();
  if (adminEnabled) fillAdminControls();
}

function syncWorkloadRoute() {
  const match = location.hash.match(/^#\/workloads\/([^?]+)/);
  let workloadId = "";
  try {
    workloadId = match ? decodeURIComponent(match[1]) : "";
  } catch {
    routeSummary.textContent = "Invalid workload route";
  }
  document.querySelectorAll("[data-workload-detail]").forEach((detail) => {
    const open = detail.dataset.workloadDetail === workloadId;
    detail.hidden = !open;
    detail.closest(".workload")?.classList.toggle("detail-open", open);
  });
  if (!workloadId) return;
  const detail = document.querySelector(`[data-workload-detail="${CSS.escape(workloadId)}"]`);
  if (!detail) {
    routeSummary.textContent = `Workload ${workloadId} not found`;
    return;
  }
  routeSummary.textContent = `Inspecting ${workloadId}`;
  detail.querySelector(".detail-close")?.focus({ preventScroll: true });
}

window.addEventListener("hashchange", syncWorkloadRoute);

async function loadDashboardState() {
  try {
    let response = await fetch("/api/dashboard-state", { cache: "no-store" });
    if (!response.ok) response = await fetch("./dashboard-state.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`dashboard state ${response.status}`);
    state = await response.json();
    renderDashboard();
    if (csrfToken) await loadOperationHistory();
  } catch (error) {
    routeSummary.textContent = "dashboard state unavailable";
    summaryEl.innerHTML = `<div><strong>!</strong><span>${escapeHtml(error.message)}</span></div>`;
    renderEvidenceState({ status: "unavailable" });
    workloadsEl.innerHTML = "";
    eventsEl.textContent = "No dashboard state loaded.";
  }
}

async function operationStatus(operationId) {
  const response = await fetch(`/api/operations/${encodeURIComponent(operationId)}`, {
    cache: "no-store",
    credentials: "same-origin"
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `operation status ${response.status}`);
  return payload;
}

function operationStateTone(value) {
  if (["succeeded", "rolled-back"].includes(value)) return "good";
  if (["failed", "denied", "expired", "indeterminate"].includes(value)) return "bad";
  if (["planned", "awaiting-approval", "queued", "running", "rollback-running"].includes(value)) return "warn";
  return "";
}

function operationTime(value) {
  if (!value) return "time unavailable";
  const instant = Date.parse(value);
  if (!Number.isFinite(instant)) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(instant));
}

function renderOperationHistory(workloadId, operations) {
  const target = document.querySelector(`[data-operation-history="${CSS.escape(workloadId)}"]`);
  if (!target) return;
  const visible = operations.slice(0, 4);
  const signature = JSON.stringify(visible.map((item) => [
    item.operation_id,
    item.state,
    item.redacted_summary,
    item.finished_at
  ]));
  if (target.dataset.historySignature === signature) return;
  target.dataset.historySignature = signature;
  operations.forEach((item) => operationCache.set(item.operation_id, item));
  const awaitingApproval = operations.find((item) => item.state === "awaiting-approval");
  const cancellable = operations.find((item) => ["awaiting-approval", "queued"].includes(item.state));
  if (!visible.length) {
    target.innerHTML = '<div class="history-head"><strong>Durable history</strong><span>0 operations</span></div><p class="history-empty">No durable operations recorded.</p>';
    return;
  }
  target.innerHTML = `
    <div class="history-head"><strong>Durable history</strong><span>${operations.length} recorded</span></div>
    <ol class="history-list">
      ${visible.map((item) => `
        <li class="history-item">
          <span class="history-state ${operationStateTone(item.state)}">${escapeHtml(String(item.state || "unknown").replaceAll("-", " "))}</span>
          <span class="history-copy">
            <strong>${escapeHtml(String(item.operation_type || "operation").replaceAll(".", " "))}</strong>
            <small>${escapeHtml(item.redacted_summary || operationTime(item.created_at))}</small>
          </span>
          <button type="button" data-view-operation="${escapeHtml(item.operation_id)}" data-workload="${escapeHtml(workloadId)}">Details</button>
        </li>
      `).join("")}
    </ol>
    ${awaitingApproval || cancellable ? `<div class="command-actions">
      ${awaitingApproval ? `<button type="button" data-resume-operation="${escapeHtml(awaitingApproval.operation_id)}" data-workload="${escapeHtml(workloadId)}">Resume approval</button>` : ""}
      ${cancellable ? `<button type="button" data-cancel-operation="${escapeHtml(cancellable.operation_id)}" data-workload="${escapeHtml(workloadId)}">Cancel pending ${escapeHtml(cancellable.operation_type)}</button>` : ""}
    </div>` : ""}
  `;
  const latestHealth = operations.find((item) => item.operation_type === "health.refresh");
  const freshness = document.querySelector(`[data-health-freshness="${CSS.escape(workloadId)}"]`);
  if (latestHealth && freshness) {
    freshness.textContent = `${evidenceFreshness(latestHealth.finished_at || latestHealth.created_at)} · ${latestHealth.state}`;
  }
}

async function pollOperation(operationId, workload, { present = true } = {}) {
  if (activeOperationPolls.has(operationId)) return;
  activeOperationPolls.add(operationId);
  try {
    while (activeOperationPolls.has(operationId)) {
      const operation = await operationStatus(operationId);
      operationCache.set(operationId, operation);
      if (present) showCommandResult(`${workload} operation`, operation);
      await loadOperationHistory(workload);
      if (["succeeded", "failed", "denied", "expired", "indeterminate", "rolled-back"].includes(operation.state)) return;
      const delay = document.visibilityState === "hidden" ? 10000 : 2000;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  } catch (error) {
    if (present) showCommandResult(`${workload} progress unavailable`, error.message);
  } finally {
    activeOperationPolls.delete(operationId);
  }
}

async function loadOperationHistory(workloadId = "") {
  const workloads = (state?.workloads || []).filter((item) => !workloadId || item.id === workloadId);
  await Promise.all(workloads.map(async (item) => {
    const target = document.querySelector(`[data-operation-history="${CSS.escape(item.id)}"]`);
    if (!target) return;
    try {
      const response = await fetch(`/api/workloads/${encodeURIComponent(item.id)}/operations`, {
        cache: "no-store",
        credentials: "same-origin"
      });
      if (!response.ok) {
        const message = response.status === 401
          ? "Operator session expired; authenticate to restore history."
          : "History temporarily unavailable.";
        target.innerHTML = `<div class="history-head"><strong>Durable history</strong><span>Unavailable</span></div><p class="history-empty">${message}</p>`;
        return;
      }
      const payload = await response.json();
      const operations = payload.operations || [];
      renderOperationHistory(item.id, operations);
      const inFlight = operations.find((operation) =>
        ["queued", "running", "rollback-running"].includes(operation.state)
      );
      if (inFlight) void pollOperation(inFlight.operation_id, item.id, { present: false });
    } catch {
      target.innerHTML = '<div class="history-head"><strong>Durable history</strong><span>Unavailable</span></div><p class="history-empty">History temporarily unavailable.</p>';
    }
  }));
}

function fillAdminControls() {
  document.querySelectorAll('select[data-action="access"]').forEach((select) => {
    const phaseOneStates = (state?.accessStates || []).filter((item) => ["none", "local", "tailnet"].includes(item));
    select.innerHTML = phaseOneStates.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
    const workload = select.dataset.workload;
    const current = state?.workloads?.find((item) => item.id === workload)?.access?.desired;
    if (phaseOneStates.includes(current)) select.value = current;
  });
}

function setAdmin(open) {
  adminEnabled = open;
  adminTokenInput.hidden = !open;
  if (open && operatorSessionState === "authenticated") fillAdminControls();
  document.querySelectorAll(".admin-row").forEach((row) => {
    row.hidden = !(open && operatorSessionState === "authenticated");
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
    const result = await apiPost("/api/workloads/discover", {});
    showCommandResult("Workload discovery", result.payload);
    renderDiscoveryCandidates(result.payload.newComposeProjects);
  } catch (error) {
    showCommandResult("Refresh failed", error.message);
  } finally {
    workloadDiscoverButton.disabled = false;
    workloadDiscoverButton.textContent = "Refresh estate";
  }
});

monitorToggle.addEventListener("click", () => setMonitor(monitorPanel.hidden));
themeToggle.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  localStorage.setItem("argus-theme", theme);
  setTheme(theme);
});
adminToggle.addEventListener("click", async () => {
  if (operatorSessionState === "checking") return;
  if ((operatorSessionState === "unavailable" && operatorSessionReason !== "csrf-missing") || ["identity-missing", "operator-disabled"].includes(operatorSessionReason)) {
    await restoreOperatorSession();
    return;
  }
  if (operatorSessionState === "authenticated") {
    const result = await apiPost("/api/session/logout", {});
    if (!result.ok) {
      showCommandResult("Logout failed", result.payload);
      return;
    }
    adminTokenInput.value = "";
    operationCache.clear();
    activeOperationPolls.clear();
    setOperatorSessionState("unauthenticated", { reason: "cookie-missing" });
    renderDashboard();
    showCommandResult("Operator session", "Logged out.");
    return;
  }
  if (!adminEnabled) {
    setAdmin(true);
    adminTokenInput.focus({ preventScroll: true });
    return;
  }
  try {
    const session = await authenticateOperator();
    showCommandResult("Operator authenticated", { identity: session.identity, expiresAt: session.expiresAt });
    await loadOperationHistory();
  } catch (error) {
    showCommandResult("Authentication failed", error.message);
  }
});

function closeCommandPanel() {
  commandPanel.hidden = true;
  commandOutput.textContent = "";
  commandAnnouncer.textContent = "";
  if (lastCommandTrigger instanceof HTMLElement && document.contains(lastCommandTrigger)) {
    lastCommandTrigger.focus({ preventScroll: true });
  }
}

commandClose.addEventListener("click", closeCommandPanel);

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
  const resumeApproval = event.target.closest("[data-resume-operation]");
  if (resumeApproval) {
    if (!csrfToken) {
      showCommandResult("Operator session required", "Authenticate before resuming approval.");
      return;
    }
    const operationId = resumeApproval.dataset.resumeOperation;
    const workloadId = resumeApproval.dataset.workload;
    const row = document.querySelector(`.workload[data-workload="${CSS.escape(workloadId)}"]`);
    const confirmation = row?.querySelector("[data-confirm]")?.value || "";
    if (confirmation !== workloadId) {
      showCommandResult("Confirmation required", `Type ${workloadId} in its confirmation field before resuming approval.`);
      return;
    }
    if (!(await ensureStepUp())) return;
    const approved = await apiPost(`/api/operations/${encodeURIComponent(operationId)}/approve`, { confirmation });
    showCommandResult(`${workloadId} operation queued`, approved.payload);
    if (approved.ok) void pollOperation(operationId, workloadId);
    return;
  }
  const viewOperation = event.target.closest("[data-view-operation]");
  if (viewOperation) {
    const operationId = viewOperation.dataset.viewOperation;
    const workloadId = viewOperation.dataset.workload;
    try {
      const operation = operationCache.get(operationId) || await operationStatus(operationId);
      operationCache.set(operationId, operation);
      showCommandResult(`${workloadId} operation`, operation);
    } catch (error) {
      showCommandResult(`${workloadId} operation unavailable`, error.message);
    }
    return;
  }
  const cancelPending = event.target.closest("[data-cancel-operation]");
  if (cancelPending) {
    if (!csrfToken) {
      showCommandResult("Operator session required", "Authenticate before cancelling a pending operation.");
      return;
    }
    const operationId = cancelPending.dataset.cancelOperation;
    const result = await apiPost(`/api/operations/${encodeURIComponent(operationId)}/cancel`, {});
    showCommandResult(`${cancelPending.dataset.workload} cancellation`, result.payload);
    await loadOperationHistory();
    return;
  }
  const register = event.target.closest("[data-register]");
  if (register) {
    showCommandResult("Registration unavailable", "Workload admission is outside the Phase 1 routine-operation surface.");
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
    if (action.endsWith("-apply") && confirmation !== workload) {
      showCommandResult("Confirmation required", `Type ${workload} in the confirmation field before applying.`);
      return;
    }
    if (action.endsWith("-apply") && !(await ensureStepUp())) return;
    const operationType = action.startsWith("health")
      ? "health.refresh"
      : action.startsWith("logs")
        ? "logs.preview"
        : action.startsWith("restart")
          ? "workload.restart"
          : action.startsWith("migration")
            ? "migration.preflight"
            : "backup.create";
    try {
      const previewResult = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/operations/preview`, {
        operationType,
        parameters: {}
      });
      if (
        !action.endsWith("-apply")
        && !["health.refresh", "migration.preflight"].includes(operationType)
      ) {
        showCommandResult(`${workload} ${action}`, previewResult.payload);
        return;
      }
      if (!previewResult.ok || !previewResult.payload.allowed) {
        showCommandResult(`${workload} blocked`, previewResult.payload);
        return;
      }
      const created = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/operations`, {
        operationType,
        parameters: {},
        previewDigest: previewResult.payload.previewDigest,
        expectedRevision: previewResult.payload.expectedRevision,
        policyVersion: previewResult.payload.policyVersion
      });
      if (!created.ok) {
        showCommandResult(`${workload} operation`, created.payload);
        return;
      }
      if (["health.refresh", "migration.preflight"].includes(operationType)) {
        const label = operationType === "migration.preflight" ? "migration preflight" : "health";
        showCommandResult(`${workload} ${label} queued`, created.payload);
        pollOperation(created.payload.operation_id, workload);
        return;
      }
      const approved = await apiPost(`/api/operations/${created.payload.operation_id}/approve`, { confirmation });
      showCommandResult(`${workload} operation queued`, approved.payload);
      if (approved.ok) pollOperation(created.payload.operation_id, workload);
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
    showCommandResult("Operator session required", "Authenticate before changing access.");
    return;
  }
  const current = state?.workloads?.find((item) => item.id === workload) || {};
  const accessTarget = selectedValue(row, 'select[data-action="access"]');
  const confirmation = selectedValue(row, "[data-confirm]");
  const accessChanged = accessTarget && accessTarget !== current.access?.desired;
  if (preview) {
    try {
      const accessPreview = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/operations/preview`, {
        operationType: "access.apply",
        parameters: { desired: accessTarget }
      });
      showCommandResult(`${workload} access preview`, accessPreview.payload);
    } catch (error) {
      showCommandResult("Preview failed", error.message);
    }
    return;
  }
  if (!accessChanged) {
    showCommandResult(`${workload} apply`, "No access change selected.");
    return;
  }
  try {
    if (confirmation !== workload) {
      showCommandResult("Confirmation required", `Type ${workload} before applying access.`);
      return;
    }
    if (!(await ensureStepUp())) return;
    const accessPreview = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/operations/preview`, {
      operationType: "access.apply",
      parameters: { desired: accessTarget }
    });
    if (!accessPreview.ok || !accessPreview.payload.allowed) {
      showCommandResult(`${workload} access blocked`, accessPreview.payload);
      return;
    }
    const created = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/operations`, {
      operationType: "access.apply",
      parameters: { desired: accessTarget },
      previewDigest: accessPreview.payload.previewDigest,
      expectedRevision: accessPreview.payload.expectedRevision,
      policyVersion: accessPreview.payload.policyVersion
    });
    if (!created.ok) {
      showCommandResult(`${workload} access`, created.payload);
      return;
    }
    const approved = await apiPost(`/api/operations/${created.payload.operation_id}/approve`, { confirmation });
    showCommandResult(`${workload} access queued`, approved.payload);
    if (approved.ok) pollOperation(created.payload.operation_id, workload);
  } catch (error) {
    showCommandResult("Apply failed", error.message);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !commandPanel.hidden) {
    event.preventDefault();
    closeCommandPanel();
    return;
  }
  const focus = event.target.closest('[role="button"][data-focus-workload]');
  if (!focus || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  selectedTopologyId = focus.dataset.focusWorkload;
  renderTopology();
});

setTheme(document.documentElement.dataset.theme);
async function restoreOperatorSession() {
  setOperatorSessionState("checking");
  try {
    const response = await fetch("/api/session", { cache: "no-store", credentials: "same-origin" });
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      setOperatorSessionState("unavailable", { reason: "session-store-unavailable" });
      return;
    }
    if (response.ok && payload.authenticated === true) {
      if (cookieValue("argus_csrf")) {
        setOperatorSessionState("authenticated", { session: payload });
      } else {
        setOperatorSessionState("unavailable", { reason: "csrf-missing" });
      }
    } else if (response.status === 401 && SESSION_REASON_STATES[payload.reason]) {
      setOperatorSessionState(SESSION_REASON_STATES[payload.reason], { reason: payload.reason });
    } else {
      setOperatorSessionState("unavailable", { reason: "session-store-unavailable" });
    }
  } catch (error) {
    setOperatorSessionState("unavailable", { reason: "session-store-unavailable" });
  } finally {
    await loadDashboardState();
  }
}
restoreOperatorSession();
"""


def main() -> int:
    write_assets(PUBLIC)
    write(PUBLIC / "index.html", render_html())
    write(PUBLIC / "state-prototypes.html", render_prototypes())
    write(PUBLIC / "style.css", M5_CSS.strip() + "\n")
    write(PUBLIC / "app.js", JS.strip() + "\n")
    print(f"Generated {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
