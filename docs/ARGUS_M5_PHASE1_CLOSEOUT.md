# Argus M5 Phase 1 Closeout

Status: pending current server revalidation.

This record is the sanitized source-of-truth summary for the Phase 1 server
baseline. Raw runtime evidence remains on `oreochiserver` under the ignored
runtime evidence tree and must not be copied into GitHub or Git.

## Scope

- durable operation ledger and worker
- scoped capability issuer and domain-local agents
- private control API and Tailscale-only dashboard route
- scheduled smoke service and timer
- no public provider, DNS, Funnel, router-port, database, cache, or Docker
  socket exposure

## Current revalidation

| Check | Target | Result | Evidence |
|---|---|---|---|
| reviewed repository revision | `oreochiserver` | pending | sanitized server record |
| `argus-check` | `oreochiserver` | pending | command summary |
| `argus doctor --json` | `oreochiserver` | pending | safe JSON fields only |
| scheduled smoke | `oreochiserver` | pending | failure/warning counts only |
| workload health | `oreochiserver` | pending | status codes only |
| listener and unit safety | `oreochiserver` | pending | class/count summary only |

## Acceptance gate

Phase 1 is current only when the reviewed checkout is clean, the scheduled
smoke timer is enabled and active, manual scheduled smoke reports zero failures
and zero warnings, the core API/worker/issuer/domain-agent units are active, and
the private-only exposure boundary remains intact. Known unrelated backup
failures must remain explicitly listed until issue #312 is complete.

## Verification commands

```text
./scripts/argus-check
scripts/argus-doctor --json
scripts/argus-health
scripts/argus-smoke-scheduled
systemctl --failed --no-legend --plain
systemctl is-enabled argus-smoke.timer
systemctl is-active argus-smoke.timer
git status --short --branch
git rev-parse HEAD
```

No credentials, private addresses, raw logs, runtime payloads, workload source,
backup artifacts, or database files belong in this document.
