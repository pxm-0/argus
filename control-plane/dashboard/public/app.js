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
