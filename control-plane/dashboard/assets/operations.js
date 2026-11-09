// Operation table and the single preview -> confirm -> step-up -> create -> approve -> poll sequence.
// Concatenated into app.js by generate_dashboard.py; relies on apiPost, ensureStepUp, pollOperation, showCommandResult.
const NO_PARAMETERS = () => ({});
const OPERATIONS = {
  "health-preview": { operationType: "health.refresh", parameters: NO_PARAMETERS, executes: true, requiresConfirm: false, requiresStepUp: false, pollable: true, queuedLabel: "health queued" },
  "migration-preflight": { operationType: "migration.preflight", parameters: () => ({ targetTrustDomain: "personal-sandbox" }), executes: true, requiresConfirm: false, requiresStepUp: false, pollable: true, queuedLabel: "migration preflight queued" },
  "logs-preview": { operationType: "logs.preview", parameters: NO_PARAMETERS, executes: false },
  "restart-preview": { operationType: "workload.restart", parameters: NO_PARAMETERS, executes: false },
  "restart-apply": { operationType: "workload.restart", parameters: NO_PARAMETERS, executes: true, requiresConfirm: true, requiresStepUp: true, pollable: true },
  "backup-preview": { operationType: "backup.create", parameters: NO_PARAMETERS, executes: false },
  "backup-apply": { operationType: "backup.create", parameters: NO_PARAMETERS, executes: true, requiresConfirm: true, requiresStepUp: true, pollable: true },
  "deploy-apply": { operationType: "workload.deploy", parameters: (context) => ({ targetRevision: context.targetRevision || "" }), executes: true, requiresConfirm: true, requiresStepUp: true, pollable: true },
  "start-apply": { operationType: "workload.start", parameters: NO_PARAMETERS, executes: true, requiresConfirm: true, requiresStepUp: true, pollable: true },
  "stop-apply": { operationType: "workload.stop", parameters: NO_PARAMETERS, executes: true, requiresConfirm: true, requiresStepUp: true, pollable: true }
};

function resolveOperation(action) {
  const definition = Object.hasOwn(OPERATIONS, action) ? OPERATIONS[action] : undefined;
  if (!definition) throw new Error(`Unknown operation action: ${action}`);
  return definition;
}

// Tracked compose pin: the first immutable sha256 digest in the workload's image line.
function composePinDigest(runtime) {
  const line = String(runtime?.imagePin || runtime?.image || "");
  return (line.match(/sha256:[0-9a-f]{64}/) || [""])[0];
}

async function runOperation({ workload, operationType, parameters = {}, confirm = null, stepUp = false, executes = true, pollable = true, queuedLabel = "operation queued" }) {
  const base = `/api/workloads/${encodeURIComponent(workload)}/operations`;
  const previewResult = await apiPost(`${base}/preview`, { operationType, parameters });
  if (!executes) {
    showCommandResult(`${workload} ${operationType}`, previewResult.payload);
    return { ok: previewResult.ok, stage: "preview", payload: previewResult.payload };
  }
  const preview = previewResult.payload;
  if (!previewResult.ok || !preview.allowed) {
    showCommandResult(`${workload} blocked`, preview);
    return { ok: false, stage: "blocked", payload: preview };
  }
  let confirmation = "";
  if (confirm !== null) {
    const phrase = preview.confirmationPhrase || workload;
    if (confirm !== phrase) {
      showCommandResult(`${workload} ${operationType} preview`, { ...preview, confirmationRequired: `Type "${phrase}" in the confirmation field, then run the action again.` });
      return { ok: false, stage: "confirm", payload: preview };
    }
    confirmation = confirm;
  }
  if (stepUp && !(await ensureStepUp())) return { ok: false, stage: "step-up", payload: preview };
  const created = await apiPost(base, {
    operationType,
    parameters,
    previewDigest: preview.previewDigest,
    expectedRevision: preview.expectedRevision,
    policyVersion: preview.policyVersion
  });
  if (!created.ok) {
    showCommandResult(`${workload} operation`, created.payload);
    return { ok: false, stage: "create", payload: created.payload };
  }
  const operationId = created.payload.operation_id;
  if (confirm === null) {
    showCommandResult(`${workload} ${queuedLabel}`, created.payload);
    if (pollable) pollOperation(operationId, workload);
    return { ok: true, stage: "queued", payload: created.payload };
  }
  const approved = await apiPost(`/api/operations/${encodeURIComponent(operationId)}/approve`, { confirmation });
  showCommandResult(`${workload} operation queued`, approved.payload);
  if (approved.ok && pollable) pollOperation(operationId, workload);
  return { ok: approved.ok, stage: "approved", payload: approved.payload };
}
