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
