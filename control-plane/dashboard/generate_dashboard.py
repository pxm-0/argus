#!/usr/bin/env python3
"""Generate the private Argus dashboard static files.

One overview: a "Needs attention" list, one workload table (declared and effective
access side by side), and per-workload detail with every action in one panel.
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
          <a href="#activity-heading">Activity</a>
          <a href="#system">System</a>
        </nav>
        <div class="private-state"><i aria-hidden="true"></i><span>Private<br>control plane</span></div>
      </aside>
      <div class="app-main">
    <header class="topbar">
      <div class="title-lockup">
        <h1>Argus</h1>
        <p id="route-summary">Loading estate evidence</p>
        <p id="state-age" class="state-age"><span class="state-badge info">Loading</span><span>Loading dashboard state</span></p>
      </div>
      <div class="top-actions" aria-label="Operator tools">
        <form id="signin-form" class="signin-form" method="post" hidden>
          <input id="signin-user" name="username" type="text" autocomplete="username" aria-label="Operator login" placeholder="Operator login" spellcheck="false" autocapitalize="off">
          <input id="admin-token" name="password" type="password" autocomplete="current-password" aria-label="Bootstrap token" placeholder="Bootstrap token" aria-describedby="signin-message">
          <input id="admin-totp" name="one-time-code" type="text" inputmode="numeric" autocomplete="one-time-code" aria-label="Authenticator code" placeholder="Authenticator code" maxlength="16" aria-describedby="signin-message">
          <button id="signin-submit" type="submit">Sign in</button>
          <button id="signin-cancel" type="button" hidden>Cancel</button>
          <p id="signin-message" class="signin-message" role="status" aria-live="polite"></p>
        </form>
        <button class="primary-action" id="workload-discover" type="button">Refresh estate</button>
        <div class="session-control" id="session-control" data-state="checking">
          <i class="session-signal" aria-hidden="true"></i>
          <span class="session-copy" role="status" aria-live="polite" aria-atomic="true">
            <strong id="session-status">Checking session</strong>
            <small id="session-detail">Confirming private operator session.</small>
          </span>
          <button id="admin-toggle" type="button" disabled>Checking</button>
        </div>
        <div class="view-tools" aria-label="View">
          <button class="utility-action" id="monitor-toggle" type="button" aria-pressed="false">Monitor</button>
          <button class="utility-action" id="theme-toggle" type="button" aria-pressed="false">Theme</button>
        </div>
      </div>
    </header>
    <main id="overview">
      <section class="alert" id="state-alert" data-state="open" role="alert" hidden>
        <strong>State unavailable</strong>
        <span id="state-alert-detail">Argus could not load the dashboard state. No action is authorized from stale or missing state.</span>
        <button type="button" id="state-retry">Retry</button>
      </section>
      <section class="attention" id="attention" aria-labelledby="attention-title">
        <div class="attention-head">
          <h2 id="attention-title">Needs attention</h2>
          <span id="attention-count" class="state-badge info">Loading</span>
        </div>
        <ul class="attention-list" id="attention-list" aria-live="polite"><li class="attention-item" data-tone="info"><div><strong>Loading estate state</strong></div></li></ul>
        <dl class="estate-facts" id="summary" aria-label="Estate summary"></dl>
      </section>
      <section class="command-panel" id="command-panel" tabindex="-1" aria-labelledby="command-title" aria-describedby="command-summary" hidden>
        <header class="command-header">
          <div class="command-heading">
            <span class="result-badge info" id="command-status">Result</span>
            <h2 id="command-title">Command completed</h2>
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
      <div id="active-operation" class="active-banner" role="status" hidden></div>
      <section class="section-head" id="stages-heading">
        <h2>Stages</h2>
        <span>Promote the staging image to production, or roll production back</span>
      </section>
      <section id="stages" aria-labelledby="stages-heading"></section>
      <section class="section-head" id="workloads-heading">
        <h2>Workloads</h2>
        <span>Inspect a workload to see its evidence and run its actions</span>
      </section>
      <section class="workloads" id="workloads"></section>
      <p class="empty-domains" id="empty-domains" hidden></p>
      <section class="section-head" id="activity-heading">
        <h2>Activity</h2>
        <span>Operations across all workloads, then the audit log</span>
      </section>
      <section id="activity" aria-labelledby="activity-heading"></section>
      <h3 class="subhead">Audit log</h3>
      <ol id="events" class="history-list"><li>loading events</li></ol>
      <section class="section-head" id="system">
        <h2>System</h2>
        <span>Exposure, routes, and estate evidence</span>
      </section>
      <dl class="system-facts" id="system-facts"><div><dt>System</dt><dd>loading system state</dd></div></dl>
      <section class="evidence-state" id="evidence-state" aria-labelledby="evidence-state-title" aria-live="polite">
        <div class="evidence-state-head">
          <h3 id="evidence-state-title">Estate evidence</h3>
          <span id="evidence-state-label" class="state-badge info">Loading</span>
        </div>
        <div id="evidence-state-body" class="evidence-state-body">Loading estate evidence.</div>
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
const adminTotpInput = document.getElementById("admin-totp");
const signinForm = document.getElementById("signin-form");
const signinSubmit = document.getElementById("signin-submit");
const signinCancel = document.getElementById("signin-cancel");
const signinMessage = document.getElementById("signin-message");
const sessionControl = document.getElementById("session-control");
const sessionStatus = document.getElementById("session-status");
const sessionDetail = document.getElementById("session-detail");
const routeSummary = document.getElementById("route-summary");
const summaryEl = document.getElementById("summary");
const stateAgeEl = document.getElementById("state-age");
const stateAlert = document.getElementById("state-alert");
const stateAlertDetail = document.getElementById("state-alert-detail");
const stateRetry = document.getElementById("state-retry");
const attentionList = document.getElementById("attention-list");
const attentionCount = document.getElementById("attention-count");
const emptyDomainsEl = document.getElementById("empty-domains");
const systemFactsEl = document.getElementById("system-facts");
const evidenceStateEl = document.getElementById("evidence-state");
const evidenceStateLabelEl = document.getElementById("evidence-state-label");
const evidenceStateBodyEl = document.getElementById("evidence-state-body");
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
let pendingStepUp = null;
let stepUpReturnFocus = null;
let csrfToken = "";
let operatorIdentity = "";
let operatorSessionState = "checking";
let operatorSessionReason = "";
let operatorSession = null;
let lastCommandTrigger = null;
const activeOperationPolls = new Set();
const operationCache = new Map();
const activeMigrationPolls = new Set();
const migrationCache = new Map();

function setTheme(theme) {
  const light = theme === "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  themeToggle.textContent = light ? "Dark Mode" : "Light Mode";
  themeToggle.setAttribute("aria-pressed", String(light));
}

const liveRegionMarkup = new WeakMap();

function setLiveRegionHTML(element, html) {
  // Rewriting unchanged live-region content makes screen readers announce it again on every poll.
  if (liveRegionMarkup.get(element) === html) return;
  liveRegionMarkup.set(element, html);
  element.innerHTML = html;
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
    // Logout, expiry or a lost CSRF cookie: the change cannot proceed, and the next submit must be a sign-in.
    if (pendingStepUp && operatorSessionState !== "checking") finishStepUp(false);
    setAdmin(false);
  }
  if (state) renderStages();
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
  if (payload.confirmationRequired) return payload.confirmationRequired;
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
  if (payload.confirmationPhrase) rows.push(["Confirmation phrase", payload.confirmationPhrase]);
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

function credentialBody(credential) {
  const totp = adminTotpInput.value.trim();
  return totp ? { bootstrapToken: credential, totp } : { bootstrapToken: credential };
}

function clearCredentialInputs() {
  adminTokenInput.value = "";
  adminTotpInput.value = "";
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
  if (/\/api\/workloads\/[^/]+\/(operations|migrations)$/.test(endpoint)) headers["Idempotency-Key"] = crypto.randomUUID();
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
  return { ok: response.ok, status: response.status, payload, retryAfter: Number(response.headers.get("Retry-After")) || 0 };
}

function setSigninMessage(text, tone = "") {
  signinMessage.textContent = text;
  signinMessage.dataset.tone = tone;
}

// The API keeps 401 generic (never says which factor failed), so the hint covers both.
function signinFailureMessage(result) {
  if (result.status === 429) {
    const minutes = Math.max(1, Math.ceil(result.retryAfter / 60));
    return `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`;
  }
  if (result.status === 401) return "Not accepted. Check the token and use a fresh code: each code works once, so wait for the next one if you just used it.";
  return result.payload.error || `Sign-in failed (${result.status}).`;
}

async function authenticateOperator() {
  const credential = tokenFor();
  if (!credential) throw new Error("Enter the bootstrap token.");
  let result;
  try {
    result = await apiPost(
      "/api/session/exchange",
      credentialBody(credential),
      { "X-Argus-CSRF-Bootstrap": bootstrapNonce() }
    );
  } finally {
    clearCredentialInputs();
  }
  if (!result.ok) throw new Error(signinFailureMessage(result));
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
  return requestStepUp();
}

// Resolves true once the operator confirms with a fresh code, false on Cancel; the change then continues or stops.
function requestStepUp() {
  if (pendingStepUp) pendingStepUp(false);
  return new Promise((resolve) => {
    pendingStepUp = resolve;
    stepUpReturnFocus = document.activeElement;
    setAdmin(true);
    signinSubmit.textContent = "Confirm";
    signinCancel.hidden = false;
    setSigninMessage("Confirm this change with your bootstrap token and a fresh authenticator code.");
    signinForm.scrollIntoView({ block: "nearest" });
    adminTokenInput.focus();
  });
}

function finishStepUp(confirmed) {
  const resolve = pendingStepUp;
  const returnFocus = stepUpReturnFocus;
  pendingStepUp = null;
  stepUpReturnFocus = null;
  signinSubmit.textContent = "Sign in";
  signinCancel.hidden = true;
  setSigninMessage("");
  clearCredentialInputs();
  setAdmin(adminEnabled);
  if (returnFocus instanceof HTMLElement && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
  if (resolve) resolve(confirmed);
}

async function submitStepUp() {
  const credential = tokenFor();
  if (!credential) {
    setSigninMessage("Enter the bootstrap token.", "bad");
    return;
  }
  let result;
  try {
    result = await apiPost("/api/session/step-up", credentialBody(credential));
  } finally {
    clearCredentialInputs();
  }
  if (!result.ok) {
    const check = await fetch("/api/session", { cache: "no-store", credentials: "same-origin" }).catch(() => null);
    const current = check?.ok ? await check.json().catch(() => ({})) : {};
    if (current.authenticated !== true) {
      await restoreOperatorSession();
      setAdmin(true);
      setSigninMessage("Your session ended, so the change was not made. Sign in again.", "bad");
      return;
    }
    setSigninMessage(signinFailureMessage(result), "bad");
    return;
  }
  setSigninMessage("");
  finishStepUp(true);
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

// Actions follow prototypes/states.json; loading has none ("No action yet").
const EVIDENCE_PRESENTATIONS = Object.freeze({
  loading: { label: "Loading", tone: "info", headline: "Loading estate evidence", detail: "Waiting for the private evidence summary.", action: null },
  empty: { label: "Empty", tone: "info", headline: "No estate evidence configured", detail: "The dashboard has no configured observation repository to reconcile.", action: "Open coverage" },
  error: { label: "Error", tone: "bad", headline: "Estate evidence unavailable", detail: "The private evidence summary could not be loaded. No action is authorized.", action: "Retry failed sources", refresh: true },
  partial: { label: "Partial", tone: "warn", headline: "Estate evidence is incomplete", detail: "Some sources or workload identities still need evidence before review can finish.", action: "Review coverage" },
  stale: { label: "Stale", tone: "warn", headline: "Estate evidence is stale", detail: "One or more source observations are outside the freshness window.", action: "Refresh estate", refresh: true },
  conflict: { label: "Conflict", tone: "bad", headline: "Estate identity conflict", detail: "The same workload evidence maps to incompatible trust-domain identities.", action: "Inspect evidence" },
  complete: { label: "Complete", tone: "good", headline: "Estate evidence is complete", detail: "All reconciled workload identities are known and the configured sources are fresh.", action: "Open workload", href: "#workloads-heading" }
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
  if (!reconciliation || reconciliation.status === "loading") return "loading";
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
  const actionMarkup = !presentation.action ? ""
    : presentation.refresh ? `<button type="button" class="action evidence-action" data-evidence-refresh>${presentation.action}</button>`
    : presentation.href ? `<a class="action evidence-action" href="${presentation.href}">${presentation.action}</a>`
    : `<a class="action evidence-action" href="#evidence-state">${presentation.action}</a>`;
  const sourceMarkup = sources.length
    ? `<ul class="evidence-state-sources">${sources.slice(0, 8).map((source) => `<li><span>${escapeHtml(safeEvidenceToken(source?.sourceId))}</span><strong>${escapeHtml(safeEvidenceToken(source?.state || "unknown"))}</strong></li>`).join("")}</ul>`
    : `<p class="evidence-state-empty">No source rows are available.</p>`;
  const blockerMarkup = blockers.length
    ? `<details class="evidence-state-blockers"><summary>${boundedCount(blockers.length)} blocker${blockers.length === 1 ? "" : "s"}</summary><ul>${blockers.slice(0, 6).map((blocker) => `<li>${escapeHtml(reconciliationBlockerLabel(blocker))}</li>`).join("")}</ul></details>`
    : `<p class="evidence-state-empty">No reconciliation blockers reported.</p>`;
  evidenceStateEl.dataset.state = stateId;
  evidenceStateLabelEl.className = `state-badge ${presentation.tone}`;
  if (evidenceStateLabelEl.textContent !== presentation.label) evidenceStateLabelEl.textContent = presentation.label;
  setLiveRegionHTML(evidenceStateBodyEl, `
    <div class="evidence-state-copy"><strong>${presentation.headline}</strong><p>${presentation.detail}</p>${actionMarkup}</div>
    <dl class="evidence-state-meta"><div><dt>Sources</dt><dd>${boundedCount(coverage.freshSources)} fresh / ${boundedCount(coverage.configuredSources)} configured</dd></div><div><dt>Workloads</dt><dd>${boundedCount(workloads.length)} reconciled</dd></div><div><dt>Mutation authority</dt><dd>None granted</dd></div></dl>
    <div class="evidence-state-detail"><div><h4>Source coverage</h4>${sourceMarkup}</div><div><h4>Blockers</h4>${blockerMarkup}</div></div>`);
}

function attentionAction(action) {
  if (!action) return "";
  return action.refresh
    ? `<button type="button" data-evidence-refresh>${escapeHtml(action.label)}</button>`
    : `<a class="action" href="${escapeHtml(action.href)}">${escapeHtml(action.label)}</a>`;
}

function renderSummary() {
  const workloads = state?.workloads || [];
  const exposure = state?.exposure?.providers || {};
  const topology = state?.topology || {};
  const topologySummary = topology.summary || {};
  const funnel = exposure?.tailscale?.funnel || {};
  const evidenceStateId = reconciliationState(state?.reconciliation);
  const reasons = exceptionReasons(state, evidenceStateId);
  const exceptions = reasons.reduce((total, item) => total + item.count, 0);
  const items = attentionItems(state, evidenceStateId, EVIDENCE_PRESENTATIONS[evidenceStateId]);
  const warnings = items.filter((item) => item.tone !== "bad").length;
  const privateExposure = !funnel.observedEnabled && !exposure?.cloudflare?.enabled;
  const agents = Number(topologySummary.domainAgentsAvailable || 0);
  const domains = (topology.domains || []).filter((domain) => domain.id !== "management");
  const usedDomains = domains.filter((domain) => (domain.workloadIds || []).length).length;
  attentionCount.className = `state-badge ${exceptions ? "bad" : warnings ? "warn" : "good"}`;
  attentionCount.textContent = exceptions
    ? `${exceptions} ${exceptions === 1 ? "exception" : "exceptions"}${warnings ? ` · ${warnings} ${warnings === 1 ? "warning" : "warnings"}` : ""}`
    : warnings ? `None open · ${warnings} ${warnings === 1 ? "warning" : "warnings"}` : "None open";
  setLiveRegionHTML(attentionList, items.length
    ? items.map((item) => `<li class="attention-item" data-tone="${escapeHtml(item.tone)}"><span class="attention-tone">${item.tone === "bad" ? "Exception" : "Warning"}</span><div><strong>${escapeHtml(item.title)}</strong>${item.detail ? `<p>${escapeHtml(item.detail)}</p>` : ""}</div>${attentionAction(item.action)}</li>`).join("")
    : '<li class="attention-item" data-tone="good"><span class="attention-tone">Clear</span><div><strong>Nothing needs attention</strong><p>No exceptions or warnings in the current state.</p></div></li>');
  summaryEl.innerHTML = [
    ["Workloads", workloads.length || "None registered", workloads.length ? "" : "warn"],
    ["Trust domains", `${usedDomains} of ${domains.length} in use`, ""],
    ["Agents available", agents, workloads.length && !agents ? "bad" : ""],
    ["Exposure", privateExposure ? "Private" : "Review", privateExposure ? "good" : "warn"]
  ].map(([label, value, tone]) => `<div${tone ? ` data-tone="${tone}"` : ""}><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  const empty = domains.filter((domain) => !(domain.workloadIds || []).length).map((domain) => domain.id);
  emptyDomainsEl.hidden = !empty.length;
  emptyDomainsEl.textContent = empty.length ? `No workloads in ${empty.join(", ")}. These trust domains are available as move targets.` : "";
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

// Why each action is unavailable, from the manifest and pins only; an offline agent is stated once for the panel.
function operationBlockers({
  sandboxReconcileOnly,
  logsAllowed,
  restartAllowed,
  backupAllowed,
  migrationAllowed,
  migrationCandidate,
  deployAllowed,
  deployPin,
  startAllowed,
  stopAllowed
}) {
  const manifest = "Disabled by the workload manifest.";
  const sandbox = sandboxReconcileOnly ? "Sandbox workloads are reconcile-only." : "";
  return {
    health: sandbox,
    logs: logsAllowed ? "" : manifest,
    restart: restartAllowed ? "" : manifest,
    backup: backupAllowed ? "" : "No approved backup plan in the workload manifest.",
    deploy: !deployAllowed ? manifest : deployPin ? "" : "No immutable image pin in the tracked compose file.",
    start: startAllowed ? "" : manifest,
    stop: stopAllowed ? "" : manifest,
    access: sandbox,
    move: !migrationCandidate ? "Runtime placement already matches the declared domain." : migrationAllowed ? "" : "Migration preflight is disabled by the workload manifest."
  };
}

function actionRow(workloadId, key, control, purpose, reason) {
  const noteId = `action-${workloadId}-${key}`;
  return `<li class="action-row${reason ? " is-blocked" : ""}">${control.replace("<button ", `<button aria-describedby="${escapeHtml(noteId)}" `)}<small id="${escapeHtml(noteId)}">${escapeHtml(reason || purpose)}</small></li>`;
}

function renderWorkloadReconciliation(workloadId) {
  const row = state?.reconciliation?.workloads?.find((item) => item.id === workloadId);
  if (!row) {
    return `<section class="workload-reconciliation" aria-label="${escapeHtml(workloadId)} reconciliation evidence"><div><h4>Reconciliation</h4><strong>Unavailable</strong><p>No sanitized reconciliation row is available for this workload.</p></div><span class="state-badge info">Incomplete</span></section>`;
  }
  const sources = Array.isArray(row.matchedSourceIds) ? row.matchedSourceIds.slice(0, 6).map((sourceId) => safeEvidenceToken(sourceId)) : [];
  const blockers = Array.isArray(row.blockers) ? row.blockers.slice(0, 4) : [];
  const stateId = safeEvidenceToken(row.state || "incomplete");
  const blockerText = blockers.length ? blockers.map(reconciliationBlockerLabel).join(" · ") : "No row blockers reported";
  return `<section class="workload-reconciliation" aria-label="${escapeHtml(workloadId)} reconciliation evidence"><div><h4>Reconciliation</h4><strong>${escapeHtml(stateId)}</strong><p>${sources.length ? `Matched source${sources.length === 1 ? "" : "s"}: ${escapeHtml(sources.join(", "))}.` : "No matching source identity."} ${escapeHtml(blockerText)}.</p></div><dl><div><dt>Mutation authority</dt><dd>None granted</dd></div><div><dt>Evidence digests</dt><dd>${boundedCount(Array.isArray(row.evidenceDigests) ? row.evidenceDigests.length : 0)} recorded</dd></div></dl></section>`;
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
  const trustDomain = topologyNode.trustDomain || "legacy-rootful";
  const agentAvailable = Boolean(topologyNode.agentAvailable);
  const sandboxReconcileOnly = workload.actions?.sandboxReconcileOnly === true;
  const healthAllowed = !sandboxReconcileOnly;
  const accessAllowed = !sandboxReconcileOnly;
  const logsAllowed = Boolean(operations.logsAllowed || operations.logs?.allowed);
  const restartAllowed = Boolean(operations.restartAllowed || operations.restart?.allowed);
  const backupAllowed = Boolean(operations.backupAllowed || operations.backup?.allowed || backup.backupAllowed);
  const deployAllowed = Boolean(operations.deployAllowed || operations.deploy?.allowed);
  const startAllowed = Boolean(operations.startAllowed || operations.start?.allowed);
  const stopAllowed = Boolean(operations.stopAllowed || operations.stop?.allowed);
  const deployPin = composePinDigest(runtime);
  const migrationAllowed = (
    operations.migrationPreflightAllowed === true
    || operations.migrationPreflight?.allowed === true
  );
  const declaredDomain = String(topologyNode.trustDomain || "");
  const runtimeDomain = String(topologyNode.runtimeTrustDomain || "");
  const migrationCandidate = Boolean(
    runtimeDomain && declaredDomain && runtimeDomain !== declaredDomain && declaredDomain.endsWith("-managed")
  );
  const desiredAccess = access.desired || "-";
  const effectiveAccess = access.effective || "-";
  const accessDrift = desiredAccess !== effectiveAccess;
  const healthEvidenceAt = health.lastObservedAt || migration.lastHealthCheck || "";
  const healthState = healthPresentation(health);
  const freshness = freshnessPresentation(healthEvidenceAt, HEALTH_STALE_SECONDS);
  const blockers = operationBlockers({
    sandboxReconcileOnly,
    logsAllowed,
    restartAllowed,
    backupAllowed,
    migrationAllowed,
    migrationCandidate,
    deployAllowed,
    deployPin,
    startAllowed,
    stopAllowed
  });
  const wid = escapeHtml(id);
  const enabled = (allowed) => (allowed && agentAvailable ? "" : "disabled");
  const opButton = (action, label, allowed, extra = "") => `<button type="button" data-operation="${action}" data-workload="${wid}"${extra} ${enabled(allowed)}>${label}</button>`;
  return `
    <article
      class="workload"
      data-workload="${wid}"
      data-health="${escapeHtml(healthState.label.toLowerCase())}"
      data-privacy="${escapeHtml(privacy.privacy || "")}"
      data-access="${escapeHtml(access.effective || "")}"
      data-migration="${escapeHtml(migration.status || "")}"
    >
      <div class="workload-overview">
        <span class="workload-identity"><strong>${escapeHtml(workload.name || id)}</strong><small>${wid}</small></span>
        <span data-label="Trust domain"><strong>${escapeHtml(trustDomain)}</strong></span>
        <span data-label="Health"><strong class="tone-${healthState.tone}" data-health-verdict="${wid}">${escapeHtml(healthState.label)}</strong><small>${escapeHtml(healthState.detail)}</small></span>
        <span data-label="Access"><strong>${escapeHtml(effectiveAccess)}</strong><small class="${accessDrift ? "tone-bad" : ""}">${accessDrift ? `Drift: declared ${escapeHtml(desiredAccess)}` : "Matches declared"}</small></span>
        <span data-label="Evidence"><strong class="tone-${freshness.tone}" data-health-freshness="${wid}">${escapeHtml(freshness.label)}</strong><small>${escapeHtml(freshness.age)}</small></span>
        <a class="action inspect-action" href="#/workloads/${encodeURIComponent(id)}" data-open-workload="${wid}">Inspect</a>
      </div>
      <div class="workload-detail" data-workload-detail="${wid}" hidden>
      <div class="workload-head">
        <div>
          <h2>${escapeHtml(workload.name || id)}</h2>
          <p>${escapeHtml(workload.description || "")}</p>
        </div>
        <div class="detail-heading-actions"><code>${wid}</code><a class="action detail-close" href="#workloads-heading" aria-label="Close ${escapeHtml(workload.name || id)} details">Close</a></div>
      </div>
      <dl class="workload-context" aria-label="Access and control evidence">
        <div><dt>Declared access</dt><dd>${escapeHtml(desiredAccess)}</dd></div>
        <div><dt>Observed access</dt><dd>${escapeHtml(observedAccessEvidence(workload))}</dd></div>
        <div class="${accessDrift ? "drift" : ""}"><dt>Effective access</dt><dd>${escapeHtml(effectiveAccess)}${accessDrift ? " · drift" : ""}</dd></div>
        <div><dt>Health evidence</dt><dd>${escapeHtml(`${freshness.label} · ${freshness.age}`)}</dd></div>
        <div><dt>Trust domain</dt><dd>${escapeHtml(trustDomain)}</dd></div>
        <div><dt>Lifecycle</dt><dd>${escapeHtml(workload.lifecycle || "-")}</dd></div>
        <div><dt>Privacy</dt><dd>${escapeHtml(privacy.privacy || "-")}</dd></div>
        <div><dt>Migration</dt><dd>${escapeHtml(migration.status || "-")}</dd></div>
      </dl>
      ${error ? `<details class="workload-notice"><summary>Access requires reconciliation</summary><p>${escapeHtml(error)}</p></details>` : ""}
      <section class="workload-controls" aria-labelledby="actions-${wid}">
        <div class="control-head">
          <h3 id="actions-${wid}">Actions</h3>
          <p class="agent-state ${agentAvailable ? "available" : "offline"}">${agentAvailable ? "Domain agent available" : "Domain agent offline"}</p>
          <div class="workload-links">${workloadActions(urls)}</div>
        </div>
        ${agentAvailable ? "" : `<p class="control-blocked">Every action is blocked until the ${escapeHtml(trustDomain)} agent reports in.</p>`}
        <div class="action-groups">
          <div class="action-group">
            <h4>Check</h4>
            <ul class="action-list">
              ${actionRow(id, "health", opButton("health-preview", "Refresh health", healthAllowed), "Run the typed health check now.", blockers.health)}
              ${actionRow(id, "logs", opButton("logs-preview", "Logs preview", logsAllowed), "Show recent redacted log lines.", blockers.logs)}
            </ul>
          </div>
          <div class="action-group">
            <h4>Change</h4>
            <p class="action-hint">Click once to preview and get a confirmation phrase. Type it here, then click again to run. A fresh authenticator code may be required.</p>
            <label class="confirm-field">Confirmation phrase <input type="text" autocomplete="off" spellcheck="false" data-confirm="${wid}" placeholder="${wid}"></label>
            <ul class="action-list">
              ${actionRow(id, "restart", opButton("restart-apply", "Restart", restartAllowed), "Restart the workload's containers.", blockers.restart)}
              ${actionRow(id, "backup", opButton("backup-apply", "Back up", backupAllowed), "Create a backup with the manifest's plan.", blockers.backup)}
              ${actionRow(id, "deploy", opButton("deploy-apply", "Deploy", deployAllowed && deployPin, ` data-target-revision="${escapeHtml(deployPin)}"`), deployPin ? `Deploy pinned image ${deployPin.slice(0, 19)}…` : "Deploy the pinned image.", blockers.deploy)}
              ${actionRow(id, "start", opButton("start-apply", "Start", startAllowed), "Start the workload.", blockers.start)}
              ${actionRow(id, "stop", opButton("stop-apply", "Stop", stopAllowed), "Stop the workload.", blockers.stop)}
              <li class="action-row action-row-access${blockers.access ? " is-blocked" : ""}"><button type="button" data-apply="${wid}" aria-describedby="action-${wid}-access" ${enabled(accessAllowed)}>Change access</button><label>to <select data-action="access" data-workload="${wid}" ${accessAllowed ? "" : "disabled"}></select></label><small id="action-${wid}-access">${escapeHtml(blockers.access || `Currently declared ${desiredAccess}.`)}</small></li>
              ${actionRow(id, "move", `<button type="button" data-migration-create="${wid}" ${migrationAllowed && migrationCandidate ? "" : "disabled"}>Managed move</button>`, `Move to ${declaredDomain || "the declared domain"}.`, blockers.move)}
            </ul>
          </div>
        </div>
        <div class="operation-history" data-operation-history="${wid}" aria-live="polite">
          <div class="history-head"><strong>Durable history</strong><span>Loading</span></div>
        </div>
        <div class="operation-history" data-migration-history="${wid}" aria-live="polite">
          <div class="history-head"><strong>Migration parent</strong><span>Loading</span></div>
        </div>
      </section>
      <details class="workload-evidence">
        <summary><span>Technical evidence</span><small>Reconciliation, runtime, reachability</small></summary>
        ${renderWorkloadReconciliation(id)}
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
              <div><dt>Last health</dt><dd>${escapeHtml(healthEvidenceAt || "-")}</dd></div>
              <div><dt>Local URL</dt><dd>${escapeHtml(urls.local || "-")}</dd></div>
              <div><dt>Tailnet URL</dt><dd>${escapeHtml(urls.tailnet || "-")}</dd></div>
            </dl>
          </section>
          <section>
            <h3>Controls</h3>
            <dl class="facts">
              <div><dt>Cloudflare</dt><dd>${escapeHtml(cloudflare.mode || "disabled")}</dd></div>
              <div><dt>Backup target</dt><dd>${escapeHtml(backup.destination || "-")}</dd></div>
              <div><dt>Last event</dt><dd>${escapeHtml(lastEvent.action || "-")} ${escapeHtml(lastEvent.result || "")}</dd></div>
            </dl>
          </section>
        </div>
      </details>
      </div>
    </article>
  `;
}

function renderSystem() {
  const route = state?.routes?.dashboard || {};
  const api = state?.routes?.api || {};
  const exposure = state?.exposure?.providers || {};
  const funnel = exposure?.tailscale?.funnel || {};
  const monitoring = state?.monitoring || {};
  const workloads = state?.workloads || [];
  const backupPlans = workloads.filter((item) => item.backup?.status).length;
  const healthEvidence = workloads.map((item) => item.health?.lastObservedAt || item.migration?.lastHealthCheck).filter((value) => Number.isFinite(Date.parse(value))).sort();
  const oldest = freshnessPresentation(healthEvidence[0] || "", HEALTH_STALE_SECONDS);
  routeSummary.textContent = `${workloads.length} workloads · oldest health evidence ${oldest.label.toLowerCase()} (${oldest.age})`;
  systemFactsEl.innerHTML = [
    ["Tailscale Funnel", `${funnel.observedEnabled ? "On" : "Off"} · ${funnel.allowedInP0 ? "allowed" : "not allowed"} in P0`, funnel.observedEnabled ? "bad" : ""],
    ["Cloudflare provider", exposure.cloudflare?.enabled ? "Enabled by policy" : "Disabled", exposure.cloudflare?.enabled ? "warn" : "", exposure.cloudflare?.configPath],
    ["Dashboard", route.url || "-", ""],
    ["API", `${api.bind || "127.0.0.1"}:${api.port || "8099"}`, ""],
    ["Backups", `${backupPlans} of ${workloads.length} workloads have a backup plan`, "", "/srv/argus/runtime/backups"],
    ["Monitor refresh", `${monitoring.refreshSeconds || 3}s`, ""]
  ].map(([label, value, tone, path]) => `<div${tone ? ` data-tone="${tone}"` : ""}><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}${path ? `<code>${escapeHtml(path)}</code>` : ""}</dd></div>`).join("");
}

function renderEvents() {
  const events = state?.events || [];
  eventsEl.innerHTML = events.slice(-8).map((event) => `<li>${escapeHtml(`${event.timestamp || ""} ${event.workloadId || ""} ${event.action || ""} ${event.result || ""}`.trim())}</li>`).join("") || "<li>No audit events loaded.</li>";
}

function renderDashboard() {
  renderEvidenceState();
  renderSummary();
  renderStages();
  // Down first, then Unknown, then Healthy; sort is stable so registry order holds within a verdict.
  const workloads = [...(state.workloads || [])].sort((a, b) => healthPresentation(b.health).rank - healthPresentation(a.health).rank);
  workloadsEl.innerHTML = workloads.length
    ? workloads.map(renderWorkload).join("")
    : '<p class="history-empty"><strong>No workloads registered.</strong> Registered workloads appear here with health, access, and evidence freshness.</p>';
  if (!csrfToken) document.getElementById("activity").innerHTML = '<p class="history-empty">Sign in to view recent operations.</p>';
  renderSystem();
  renderEvents();
  fillAdminControls();
  syncWorkloadRoute();
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
  // Inspect is a hash link with no matching id, so scroll ourselves. Instant: the browser's own
  // fragment handling cancels a smooth scroll started from hashchange.
  detail.closest(".workload")?.scrollIntoView({ block: "start", behavior: "instant" });
}

window.addEventListener("hashchange", syncWorkloadRoute);

const topbarEl = document.querySelector(".topbar");
new ResizeObserver(() => document.documentElement.style.setProperty("--topbar-h", `${topbarEl.offsetHeight}px`)).observe(topbarEl);

const navLinks = [...document.querySelectorAll(".nav-rail nav a")];
// The current section is the lowest nav target scrolled past the sticky chrome; at the page end, the lowest target.
function syncNavCurrent() {
  const offset = (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 72) + 24;
  const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
  let current = navLinks[0];
  let currentTop = -Infinity;
  navLinks.forEach((link) => {
    const top = document.querySelector(link.getAttribute("href"))?.getBoundingClientRect().top;
    if (top !== undefined && (atEnd || top <= offset) && top > currentTop) {
      current = link;
      currentTop = top;
    }
  });
  navLinks.forEach((link) => (link === current ? link.setAttribute("aria-current", "page") : link.removeAttribute("aria-current")));
}
let navFrame = 0;
window.addEventListener("scroll", () => {
  cancelAnimationFrame(navFrame);
  navFrame = requestAnimationFrame(syncNavCurrent);
}, { passive: true });
window.addEventListener("hashchange", syncNavCurrent);

let stateLoadFailed = false;
const STATE_FETCH_TIMEOUT_MS = 15000;

function stateRefreshPaused() {
  // Re-rendering would discard typed confirmations, admin controls, the open workload detail,
  // keyboard focus inside the page, and expanded <details>.
  return adminEnabled
    || location.hash.startsWith("#/workloads/")
    || Boolean(document.activeElement?.closest?.("main"))
    || Boolean(document.querySelector("main details[open]"))
    || [...document.querySelectorAll("main input, main textarea")].some((field) => field === document.activeElement || field.value);
}

function renderStateAge() {
  const generatedAt = state?.generatedAt;
  const freshness = freshnessPresentation(generatedAt, STATE_STALE_SECONDS);
  const paused = state && stateRefreshPaused() ? " · Auto-refresh paused" : "";
  const [label, tone, detail] = stateLoadFailed
    ? ["Unavailable", "bad", state ? `Refresh failed · showing state ${generatedAt ? `as of ${operationTime(generatedAt)} (${freshness.age})` : "of unknown age"}` : "No dashboard state loaded"]
    : !state ? ["Loading", "info", "Loading dashboard state"]
    : !generatedAt ? ["Stale", "warn", `State time not reported${paused}`]
    : [freshness.label, freshness.tone, `State as of ${operationTime(generatedAt)} · ${freshness.age}${paused}`];
  stateAgeEl.dataset.tone = tone;
  stateAgeEl.innerHTML = `<span class="state-badge ${tone}">${escapeHtml(label)}</span><span>${escapeHtml(detail)}</span>`;
}

function renderStateUnavailable() {
  const unavailable = "Unavailable: dashboard state not loaded.";
  routeSummary.textContent = "Estate state unavailable";
  summaryEl.innerHTML = '<div data-tone="bad"><dt>Estate summary</dt><dd>Unavailable</dd></div>';
  renderEvidenceState({ status: "unavailable" });
  attentionCount.className = "state-badge bad";
  attentionCount.textContent = "Unavailable";
  setLiveRegionHTML(attentionList, `<li class="attention-item" data-tone="bad"><span class="attention-tone">Exception</span><div><strong>Exceptions cannot be counted</strong><p>${unavailable}</p></div></li>`);
  systemFactsEl.innerHTML = `<div><dt>System</dt><dd>${unavailable}</dd></div>`;
  document.getElementById("stages").innerHTML = `<p class="history-empty">${unavailable}</p>`;
  emptyDomainsEl.hidden = true;
  workloadsEl.innerHTML = `<p class="history-empty">${unavailable}</p>`;
  eventsEl.innerHTML = "<li>No dashboard state loaded.</li>";
}

async function loadDashboardState() {
  try {
    let response = await fetch("/api/dashboard-state", { cache: "no-store", signal: AbortSignal.timeout(STATE_FETCH_TIMEOUT_MS) });
    if (!response.ok) response = await fetch("./dashboard-state.json", { cache: "no-store", signal: AbortSignal.timeout(STATE_FETCH_TIMEOUT_MS) });
    if (!response.ok) throw new Error(`dashboard state request returned HTTP ${response.status}`);
    state = await response.json();
    stateLoadFailed = false;
    stateAlert.hidden = true;
    renderDashboard();
    if (csrfToken) {
      await loadOperationHistory();
      await loadActivity();
    }
  } catch (error) {
    console.warn("Argus dashboard state load failed", error);
    stateLoadFailed = true;
    stateAlert.hidden = false;
    stateAlertDetail.textContent = state
      ? "Argus could not refresh the dashboard state. The data below may be out of date; no action is authorized from it."
      : "Argus could not load the dashboard state. No estate data or action is available until it loads.";
    if (!state) renderStateUnavailable();
  } finally {
    renderStateAge();
  }
}

async function pollDashboardState() {
  for (;;) {
    const delay = document.visibilityState === "hidden" ? 4 * STATE_POLL_SECONDS * 1000 : STATE_POLL_SECONDS * 1000;
    await new Promise((resolve) => setTimeout(resolve, delay));
    if (stateRefreshPaused()) renderStateAge();
    else await loadDashboardState();
  }
}

stateRetry.addEventListener("click", () => { void loadDashboardState(); });
// The age badge must turn Stale on time even while a fetch is pending or the poll sleeps in a hidden tab.
setInterval(renderStateAge, 10000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  renderStateAge();
  if (!stateRefreshPaused()) void loadDashboardState();
});

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
    const latest = freshnessPresentation(latestHealth.finished_at || latestHealth.created_at, HEALTH_STALE_SECONDS);
    freshness.className = `tone-${latest.tone}`;
    freshness.textContent = `${latest.label} · ${latest.age} · ${latestHealth.state}`;
  }
}

// @include status.js
// @include operations.js
// @include stages.js
async function pollOperation(operationId, workload, { present = true } = {}) {
  if (activeOperationPolls.has(operationId)) return;
  activeOperationPolls.add(operationId);
  try {
    while (activeOperationPolls.has(operationId)) {
      const operation = await operationStatus(operationId);
      operationCache.set(operationId, operation);
      updateActiveOperation(operation, workload);
      if (present) showCommandResult(`${workload} operation`, operation);
      await loadOperationHistory(workload);
      if (TERMINAL_STATES.includes(operation.state)) return;
      const delay = document.visibilityState === "hidden" ? 10000 : 2000;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  } catch (error) {
    if (present) showCommandResult(`${workload} progress unavailable`, error.message);
  } finally {
    activeOperationPolls.delete(operationId);
  }
}

async function migrationStatus(migrationId) {
  const response = await fetch(`/api/migrations/${encodeURIComponent(migrationId)}`, {
    cache: "no-store",
    credentials: "same-origin"
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `migration status ${response.status}`);
  return payload;
}

function renderMigrationHistory(workloadId, migrations) {
  const target = document.querySelector(`[data-migration-history="${CSS.escape(workloadId)}"]`);
  if (!target) return;
  const latest = migrations[0];
  if (!latest) {
    target.innerHTML = '<div class="history-head"><strong>Migration parent</strong><span>None</span></div><p class="history-empty">No durable migration parent recorded.</p>';
    return;
  }
  migrationCache.set(latest.migrationId, latest);
  target.innerHTML = `
    <div class="history-head"><strong>Migration parent</strong><span>${escapeHtml(latest.phase || "unknown")}</span></div>
    <p class="history-empty">${escapeHtml(latest.summary || "Parent migration is durably coordinating one phase at a time.")}</p>
    <div class="command-actions"><button type="button" data-view-migration="${escapeHtml(latest.migrationId)}" data-workload="${escapeHtml(workloadId)}">Migration details</button></div>
  `;
}

async function pollMigration(migrationId, workloadId) {
  if (activeMigrationPolls.has(migrationId)) return;
  activeMigrationPolls.add(migrationId);
  try {
    while (activeMigrationPolls.has(migrationId)) {
      const migration = await migrationStatus(migrationId);
      migrationCache.set(migrationId, migration);
      showCommandResult(`${workloadId} migration`, migration);
      await loadMigrationHistory(workloadId);
      if (TERMINAL_STATES.includes(migration.phase)) return;
      const delay = document.visibilityState === "hidden" ? 10000 : 2000;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  } catch (error) {
    showCommandResult(`${workloadId} migration progress unavailable`, error.message);
  } finally {
    activeMigrationPolls.delete(migrationId);
  }
}

async function loadMigrationHistory(workloadId = "") {
  const workloads = (state?.workloads || []).filter((item) => !workloadId || item.id === workloadId);
  await Promise.all(workloads.map(async (item) => {
    const target = document.querySelector(`[data-migration-history="${CSS.escape(item.id)}"]`);
    if (!target) return;
    try {
      const response = await fetch(`/api/workloads/${encodeURIComponent(item.id)}/migrations`, {
        cache: "no-store",
        credentials: "same-origin"
      });
      if (!response.ok) {
        const message = response.status === 401
          ? "Authenticate to inspect migration state."
          : "Migration history temporarily unavailable.";
        target.innerHTML = `<div class="history-head"><strong>Migration parent</strong><span>Unavailable</span></div><p class="history-empty">${message}</p>`;
        return;
      }
      const payload = await response.json();
      const migrations = payload.migrations || [];
      renderMigrationHistory(item.id, migrations);
      const active = migrations.find((migration) => !TERMINAL_STATES.includes(migration.phase));
      if (active) void pollMigration(active.migrationId, item.id);
    } catch {
      target.innerHTML = '<div class="history-head"><strong>Migration parent</strong><span>Unavailable</span></div><p class="history-empty">Migration history temporarily unavailable.</p>';
    }
  }));
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
  await loadMigrationHistory(workloadId);
}

async function estateRefreshStatus(runId) {
  const response = await fetch(`/api/estate/refresh/${encodeURIComponent(runId)}`, {
    cache: "no-store",
    credentials: "same-origin"
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `estate refresh status ${response.status}`);
  return payload;
}

async function pollEstateRefresh(runId) {
  for (let attempt = 0; attempt < 65; attempt += 1) {
    const payload = await estateRefreshStatus(runId);
    showCommandResult("Estate refresh", payload);
    if (["completed", "partial", "failed"].includes(payload.state)) {
      await loadDashboardState();
      return payload;
    }
    const delay = document.visibilityState === "hidden" ? 10000 : 2000;
    await new Promise((resolve) => setTimeout(resolve, delay));
  }
  throw new Error("The refresh is still queued. Open its status from the command result after the next scheduled pass.");
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
  signinForm.hidden = !(open && (operatorSessionState !== "authenticated" || pendingStepUp));
}

workloadDiscoverButton.addEventListener("click", async () => {
  if (!csrfToken) {
    showCommandResult("Operator session required", "Authenticate before refreshing workload evidence.");
    return;
  }
  workloadDiscoverButton.disabled = true;
  workloadDiscoverButton.textContent = "Refreshing...";
  try {
    const result = await apiPost("/api/estate/refresh", {});
    if (!result.ok) throw new Error(result.payload.error || `estate refresh ${result.status}`);
    const request = result.payload.request || {};
    showCommandResult("Estate refresh", request);
    if (!request.runId) throw new Error("The refresh request did not return a durable run ID.");
    await pollEstateRefresh(request.runId);
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
    clearCredentialInputs();
    operationCache.clear();
    activeOperationPolls.clear();
    migrationCache.clear();
    activeMigrationPolls.clear();
    setOperatorSessionState("unauthenticated", { reason: "cookie-missing" });
    renderDashboard();
    showCommandResult("Operator session", "Logged out.");
    return;
  }
  if (signinForm.hidden) {
    setSigninMessage("");
    setAdmin(true);
    adminTokenInput.focus({ preventScroll: true });
    return;
  }
  if (!signinSubmit.disabled) signinForm.requestSubmit();
});

// A real form submit lets password managers save and fill the token and offer the code; Enter submits.
signinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (signinSubmit.disabled) return;
  signinSubmit.disabled = true;
  try {
    if (pendingStepUp) {
      await submitStepUp();
      return;
    }
    setSigninMessage("Signing in...");
    const session = await authenticateOperator();
    setSigninMessage("");
    showCommandResult("Operator authenticated", { identity: session.identity, expiresAt: session.expiresAt });
    await loadOperationHistory();
    await loadActivity();
  } catch (error) {
    setSigninMessage(error.message, "bad");
    if (signinForm.hidden) showCommandResult("Sign-in failed", error.message);
  } finally {
    signinSubmit.disabled = false;
  }
});
signinCancel.addEventListener("click", () => finishStepUp(false));
signinForm.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && pendingStepUp) finishStepUp(false);
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
  if (event.target.closest("[data-evidence-refresh]")) {
    workloadDiscoverButton.click();
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
  const viewMigration = event.target.closest("[data-view-migration]");
  if (viewMigration) {
    const migrationId = viewMigration.dataset.viewMigration;
    const workloadId = viewMigration.dataset.workload;
    try {
      const migration = migrationCache.get(migrationId) || await migrationStatus(migrationId);
      migrationCache.set(migrationId, migration);
      showCommandResult(`${workloadId} migration`, migration);
    } catch (error) {
      showCommandResult(`${workloadId} migration unavailable`, error.message);
    }
    return;
  }
  const stageAction = event.target.closest("[data-stage-action]");
  if (stageAction) {
    await handleStageAction(stageAction);
    return;
  }
  const createMigration = event.target.closest("[data-migration-create]");
  if (createMigration) {
    const workload = createMigration.dataset.migrationCreate;
    const row = createMigration.closest(".workload");
    if (!csrfToken) {
      showCommandResult("Operator session required", "Authenticate before approving a managed-domain move.");
      return;
    }
    try {
      const previewResult = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/migration/preview`, {});
      const preview = previewResult.payload;
      if (!previewResult.ok || !preview.eligible) {
        showCommandResult(`${workload} migration blocked`, preview);
        return;
      }
      const confirmation = row?.querySelector("[data-confirm]")?.value || "";
      if (confirmation !== preview.confirmationPhrase) {
        showCommandResult(`${workload} managed move preview`, { ...preview, confirmationRequired: `Type "${preview.confirmationPhrase}" in the confirmation field, then click Managed move again.` });
        return;
      }
      if (!(await ensureStepUp())) return;
      const created = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/migrations`, {
        targetTrustDomain: preview.targetTrustDomain,
        previewDigest: preview.previewDigest,
        expectedRevision: preview.expectedRevision,
        policyVersion: preview.policyVersion,
        observationDigest: preview.observationDigest
      });
      if (!created.ok) {
        showCommandResult(`${workload} migration intent`, created.payload);
        return;
      }
      const approved = await apiPost(`/api/migrations/${encodeURIComponent(created.payload.migrationId)}/approve`, { confirmation });
      showCommandResult(`${workload} migration`, approved.payload);
      if (approved.ok) void pollMigration(created.payload.migrationId, workload);
    } catch (error) {
      showCommandResult("Migration approval failed", error.message);
    }
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
    try {
      const definition = resolveOperation(action);
      await runOperation({
        workload,
        operationType: definition.operationType,
        parameters: definition.parameters({ targetRevision: operation.dataset.targetRevision, targetTrustDomain: declaredTrustDomain(workload) }),
        confirm: definition.requiresConfirm ? confirmation : null,
        stepUp: Boolean(definition.requiresStepUp),
        executes: definition.executes,
        pollable: definition.pollable,
        queuedLabel: definition.queuedLabel
      });
    } catch (error) {
      showCommandResult("Action failed", error.message);
    }
    return;
  }
  const apply = event.target.closest("[data-apply]");
  if (!apply) return;
  const workload = apply.dataset.apply;
  const row = apply.closest(".workload");
  if (!csrfToken) {
    showCommandResult("Operator session required", "Authenticate before changing access.");
    return;
  }
  const current = state?.workloads?.find((item) => item.id === workload) || {};
  const accessTarget = selectedValue(row, 'select[data-action="access"]');
  const confirmation = selectedValue(row, "[data-confirm]");
  const accessChanged = accessTarget && accessTarget !== current.access?.desired;
  if (!accessChanged) {
    showCommandResult(`${workload} access`, "Pick a different access level first.");
    return;
  }
  try {
    if (confirmation !== workload) {
      // First click previews; the operator types the workload ID and clicks again to apply.
      const accessPreview = await apiPost(`/api/workloads/${encodeURIComponent(workload)}/operations/preview`, {
        operationType: "access.apply",
        parameters: { desired: accessTarget }
      });
      showCommandResult(`${workload} access preview`, { ...accessPreview.payload, confirmationRequired: `Type "${workload}" in the confirmation field, then click Change access again.` });
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
void pollDashboardState();
"""


def splice_include(js: str, name: str) -> str:
    marker = f"// @include {name}\n"
    if js.count(marker) != 1:
        raise RuntimeError(f"app.js include marker for {name} must appear exactly once")
    return js.replace(marker, (Path(__file__).resolve().parent / "assets" / name).read_text())


for _include in ("status.js", "operations.js", "stages.js"):
    JS = splice_include(JS, _include)


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
