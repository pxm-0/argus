# Argus M5 Phase 1 Closeout

Status: accepted for the parity baseline; PostgreSQL backup repair remains
tracked separately in issue #312.

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
| reviewed repository revision | `oreochiserver` | `c9f12d85` clean checkout | `main...origin/main`, no local changes |
| `argus-check` | `oreochiserver` | pass | 406 tests, 0 skips; compile, JSON, manifest, smoke, docs, and secret-safe checks passed |
| `argus doctor --json` | `oreochiserver` | pass | 0 failures; core-boundary audit pass; localhost-only control API; no observed Funnel exposure |
| scheduled smoke | `oreochiserver` | pass | `ok=true`, exit code 0, 0 failures, 0 warnings |
| workload health | `oreochiserver` | pass | 5 enabled workloads returned HTTP 200; disabled `hello-nginx` skipped |
| listener and unit safety | `oreochiserver` | pass with allowlisted backup failures | smoke timer enabled/active; core units active; only the two known PostgreSQL backup units remain failed |

## Acceptance gate

Phase 1 parity is accepted: the reviewed checkout is clean at the fast-forwarded
main revision, the scheduled smoke timer is enabled and active, manual scheduled
smoke reports zero failures and zero warnings, the core API/worker/issuer/domain-
agent units are active, and the private-only exposure boundary remains intact.
The two known PostgreSQL backup failures remain explicitly listed until issue
#312 completes its ownership repair and live backup verification.

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
