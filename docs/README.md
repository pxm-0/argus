# Argus Documentation Paths

Use this index to distinguish current operating contracts from milestone-era
evidence. Historical documents remain immutable context; an address, command,
or branch in them is not current guidance unless a current document repeats it.

## Operator

- [`OPERATIONS.md`](OPERATIONS.md) — current commands and private dashboard URL discovery.
- [`ARGUS_M5_PHASE1_RUNBOOK.md`](ARGUS_M5_PHASE1_RUNBOOK.md) — current private control-plane deployment and recovery.
- [`DASHBOARD_RUNTIME.md`](DASHBOARD_RUNTIME.md) — generated assets and runtime-state boundaries.
- [`TAILSCALE_ACCESS_STANDARD.md`](TAILSCALE_ACCESS_STANDARD.md) — private tailnet route safety contract.
- [`BACKUP_AND_RESTORE.md`](BACKUP_AND_RESTORE.md) — current backup and restore entry point.
- [`RUNBOOKS/sandbox-firewall-remediation.md`](RUNBOOKS/sandbox-firewall-remediation.md) — exact sandbox network policy plan/apply/verify/rollback.

## Contributor

- [`PR_WORKFLOW.md`](PR_WORKFLOW.md) — current `main`-based P0 branch and PR contract.
- [`ARGUS_ISSUE_REMEDIATION_PLAN.md`](ARGUS_ISSUE_REMEDIATION_PLAN.md) — approved implementation sequence and critique loop.
- [`CODEX_TASKS.md`](CODEX_TASKS.md) — task prompts where still linked by a current issue.
- [`ACCEPTANCE_SUMMARIES.md`](ACCEPTANCE_SUMMARIES.md) — redacted PR evidence contract.

Run the transitional local suite with:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q control-plane scripts tests
python3 scripts/validate-manifests
python3 scripts/smoke-test --offline
```

PR 6A replaces this block with the single maintained `argus-check` command.

## Architecture

- [`ARGUS_V1_DECISIONS.md`](ARGUS_V1_DECISIONS.md) — accepted decisions and trust boundaries.
- [`ARGUS_M5_OPERATIONS_CONTROL_PLANE.md`](ARGUS_M5_OPERATIONS_CONTROL_PLANE.md) — current private operations architecture.
- [`ARGUS_M5_TOPOLOGY_UI.md`](ARGUS_M5_TOPOLOGY_UI.md) — topology and operator-state contract.
- [`ARGUS_ISSUE_REMEDIATION_PLAN.md`](ARGUS_ISSUE_REMEDIATION_PLAN.md) — deterministic evidence, discovery, migration, and optional companion boundaries.

## Historical Record

The following families are retained for audit history and are not current
operator instructions:

- `ARGUS_M0_*` through `ARGUS_M4_*`
- `ARGUS_P1.md` through `ARGUS_P2.md`
- `P1_*` through `P6_*` baseline, closeout, and phase evidence
- [`ARCHITECTURE.md`](ARCHITECTURE.md), [`ACCEPTANCE.md`](ACCEPTANCE.md), and
  [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) as the original P0 package
- [`DASHBOARD_AND_API.md`](DASHBOARD_AND_API.md) as the retired direct-route and
  browser-token dashboard contract

When historical evidence must be reproduced, open a linked issue and restate the
safe current command in that issue or PR. Never treat local/macOS output as
`oreochiserver` evidence.
