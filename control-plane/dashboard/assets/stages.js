// Stages (staging vs production), global Activity, active-operation banner, Promote/Rollback.
// Concatenated into app.js by generate_dashboard.py; relies on state, escapeHtml, apiPost, ensureStepUp,
// pollOperation, pollMigration, showCommandResult, operationStateTone, operationTime, composePinDigest.
const TERMINAL_STATES = ["succeeded", "failed", "denied", "expired", "indeterminate", "rolled-back"];
const shortImage = (digest) => (digest ? digest.slice(0, 19) : "none");
let bannerTimer = null;

function declaredTrustDomain(workloadId) {
  return String(state?.topology?.nodes?.find((node) => node.id === workloadId)?.trustDomain || "");
}

// One family per staging workload: explicit `promotesTo`, else "<name>-staging" -> "<name>-production".
function stageFamilies(workloads) {
  const byId = new Map(workloads.map((item) => [item.id, item]));
  return workloads.filter((item) => item.promotesTo || String(item.id).endsWith("-staging")).map((staging) => {
    const productionId = staging.promotesTo || String(staging.id).replace(/-staging$/, "-production");
    return { name: String(staging.id).replace(/-staging$/, ""), staging, production: byId.get(productionId) || null };
  });
}

function stageCell(item) {
  if (!item) return '<td colspan="1"><span class="history-empty">Not registered</span></td>';
  const runtime = item.runtime || {};
  const pinned = runtime.pinnedImage || composePinDigest(runtime);
  const observed = runtime.observedImage || "";
  const drift = !pinned ? "no pin" : !observed ? "unobserved" : pinned === observed ? "in sync" : "drift";
  const tone = drift === "in sync" ? "good" : drift === "drift" ? "bad" : "warn";
  return `<td>
    <div>Pinned <code title="${escapeHtml(pinned)}">${escapeHtml(shortImage(pinned))}</code></div>
    <div>Running <code title="${escapeHtml(observed)}">${escapeHtml(shortImage(observed))}</code>
      <span class="history-state ${tone}">${escapeHtml(drift)}</span></div>
    <small>${escapeHtml(runtime.lastDeployedAt ? operationTime(runtime.lastDeployedAt) : "never deployed")} · ${escapeHtml(runtime.lastOperationState || "no operations")}</small>
  </td>`;
}

function renderStages() {
  const target = document.getElementById("stages");
  if (!target) return;
  const families = stageFamilies(state?.workloads || []);
  if (!families.length) {
    target.innerHTML = '<p class="history-empty">No staging workloads registered.</p>';
    return;
  }
  const pinOf = (item) => item?.runtime?.pinnedImage || composePinDigest(item?.runtime);
  target.innerHTML = `<table class="stages-table"><caption class="sr-only">Staging and production image pins</caption>
    <thead><tr><th scope="col">Workload</th><th scope="col">Staging</th><th scope="col">Production</th><th scope="col">Actions</th></tr></thead>
    <tbody>${families.map(({ name, staging, production }) => {
      const outOfSync = pinOf(staging) !== pinOf(production);
      return `<tr>
        <th scope="row">${escapeHtml(name)} ${outOfSync ? '<span class="history-state warn">out of sync</span>' : ""}</th>
        ${stageCell(staging)}${stageCell(production)}
        <td>
          <label class="sr-only" for="stage-confirm-${escapeHtml(name)}">Confirmation phrase for ${escapeHtml(name)}</label>
          <input id="stage-confirm-${escapeHtml(name)}" data-stage-confirm="${escapeHtml(name)}" autocomplete="off" placeholder="confirmation phrase">
          <div class="command-actions">
            <button type="button" data-stage-action="promote" data-workload="${escapeHtml(staging.id)}" data-stage="${escapeHtml(name)}">Promote</button>
            ${production ? `<button type="button" data-stage-action="rollback" data-workload="${escapeHtml(production.id)}" data-stage="${escapeHtml(name)}">Rollback</button>` : ""}
          </div>
        </td></tr>`;
    }).join("")}</tbody></table>`;
}

function renderActivity(operations) {
  const target = document.getElementById("activity");
  if (!target) return;
  if (!operations.length) {
    target.innerHTML = '<p class="history-empty">No operations recorded.</p>';
    return;
  }
  operations.forEach((item) => operationCache.set(item.operation_id, item));
  target.innerHTML = `<table class="activity-table"><caption class="sr-only">Recent operations across workloads</caption>
    <thead><tr><th scope="col">State</th><th scope="col">Type</th><th scope="col">Workload</th><th scope="col">Requester</th><th scope="col">Time</th><th scope="col">Details</th></tr></thead>
    <tbody>${operations.map((item) => `<tr>
      <td><span class="history-state ${operationStateTone(item.state)}">${escapeHtml(String(item.state || "unknown").replaceAll("-", " "))}</span></td>
      <td>${escapeHtml(item.operation_type || "")}</td>
      <td>${escapeHtml(item.workload_id || "")}</td>
      <td>${escapeHtml(item.requested_by || "")}</td>
      <td>${escapeHtml(operationTime(item.created_at))}</td>
      <td><button type="button" data-view-operation="${escapeHtml(item.operation_id)}" data-workload="${escapeHtml(item.workload_id || "")}">Details</button></td>
    </tr>`).join("")}</tbody></table>`;
}

async function loadActivity() {
  const target = document.getElementById("activity");
  if (!target) return;
  try {
    const response = await fetch("/api/operations?limit=25", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) {
      target.innerHTML = `<p class="history-empty">${response.status === 401 ? "Sign in to view recent operations." : "Activity temporarily unavailable."}</p>`;
      return;
    }
    const operations = (await response.json()).operations || [];
    renderActivity(operations);
    const inFlight = operations.find((item) => ["queued", "running", "rollback-running"].includes(item.state));
    if (inFlight) void pollOperation(inFlight.operation_id, inFlight.workload_id, { present: false });
  } catch {
    target.innerHTML = '<p class="history-empty">Activity temporarily unavailable.</p>';
  }
}

// Called by pollOperation on every poll so progress is visible on any route.
function updateActiveOperation(operation, workload) {
  const banner = document.getElementById("active-operation");
  if (!banner) return;
  clearTimeout(bannerTimer);
  const done = TERMINAL_STATES.includes(operation.state);
  banner.hidden = false;
  banner.textContent = `${workload}: ${operation.operation_type || "operation"} ${String(operation.state || "").replaceAll("-", " ")}`;
  if (done) {
    bannerTimer = setTimeout(() => { banner.hidden = true; }, 8000);
    void loadActivity();
  }
}

async function runMigrationMove(workload, confirmation, delta) {
  const base = `/api/workloads/${encodeURIComponent(workload)}`;
  const previewResult = await apiPost(`${base}/migration/preview`, {});
  const preview = previewResult.payload;
  if (!previewResult.ok || !preview.eligible) {
    showCommandResult(`${workload} promotion blocked`, { ...preview, pinnedImageDelta: delta });
    return;
  }
  if (confirmation !== preview.confirmationPhrase) {
    showCommandResult(`${workload} promotion preview`, { ...preview, pinnedImageDelta: delta, confirmationRequired: `Type "${preview.confirmationPhrase}" in the confirmation field, then promote again.` });
    return;
  }
  if (!(await ensureStepUp())) return;
  const created = await apiPost(`${base}/migrations`, {
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
  showCommandResult(`${workload} promotion`, approved.payload);
  if (approved.ok) void pollMigration(created.payload.migrationId, workload);
}

async function runMigrationRollback(workload, confirmation) {
  const response = await fetch(`/api/workloads/${encodeURIComponent(workload)}/migrations`, { cache: "no-store", credentials: "same-origin" });
  const migrations = response.ok ? (await response.json()).migrations || [] : [];
  const latest = migrations.find((item) => item.phase === "succeeded");
  if (!latest) {
    showCommandResult(`${workload} rollback unavailable`, "No succeeded migration to roll back.");
    return;
  }
  const phrase = latest.preview?.rollbackConfirmationPhrase || `rollback migration ${workload}`;
  if (confirmation !== phrase) {
    showCommandResult(`${workload} rollback preview`, { migrationId: latest.migrationId, confirmationRequired: `Type "${phrase}" in the confirmation field, then roll back again.` });
    return;
  }
  if (!(await ensureStepUp())) return;
  const result = await apiPost(`/api/migrations/${encodeURIComponent(latest.migrationId)}/rollback`, { confirmation });
  showCommandResult(`${workload} rollback`, result.payload);
  if (result.ok) void pollMigration(latest.migrationId, workload);
}

async function handleStageAction(button) {
  if (!csrfToken) {
    showCommandResult("Operator session required", "Authenticate before promoting or rolling back.");
    return;
  }
  const { workload, stage, stageAction } = button.dataset;
  const confirmation = document.querySelector(`[data-stage-confirm="${CSS.escape(stage)}"]`)?.value || "";
  try {
    if (stageAction === "promote") {
      const family = stageFamilies(state?.workloads || []).find((item) => item.name === stage);
      const delta = { staging: family?.staging?.runtime?.pinnedImage || "", production: family?.production?.runtime?.pinnedImage || "", declaredTrustDomain: declaredTrustDomain(workload) };
      await runMigrationMove(workload, confirmation, delta);
    } else {
      await runMigrationRollback(workload, confirmation);
    }
  } catch (error) {
    showCommandResult(`${stageAction} failed`, error.message);
  }
}
