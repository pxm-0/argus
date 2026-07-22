# P5 Platform Maturity

P5 turns the P4 safety baseline into repeatable operations. It does not expose
new services, enable Cloudflare, enable Funnel, migrate stateful workloads, or
turn on backup execution for sensitive/restricted/admin workloads.

## Goals

- Run smoke checks on a schedule and leave local evidence.
- Add explicit backup retention and safe pruning.
- Define restore gates for stateful workloads before backups are enabled.
- Keep legacy wildcard binds visible as remediation work.

## Non-Goals

- No public routes.
- No DNS changes.
- No Cloudflare tunnels.
- No Tailscale Funnel.
- No PostgreSQL exposure.
- No Docker socket exposure.
- No restore automation for stateful workloads.

## Deliverables

- `scripts/argus-smoke-scheduled`
- `systemd/argus-smoke.service`
- `systemd/argus-smoke.timer`
- `scripts/argus-backup-prune`
- `docs/P5_SCHEDULED_SMOKE.md`
- `docs/P5_BACKUP_RETENTION.md`
- `docs/RUNBOOKS/stateful-restore-gates.md`

## Acceptance

- Scheduled smoke units are tracked but not installed automatically.
- Scheduled smoke writes `runtime/smoke/latest.log` and
  `runtime/smoke/latest.json`.
- Backup pruning previews by default.
- Backup pruning apply requires the exact phrase `prune argus backups`.
- Backup pruning only acts under approved per-workload backup destinations.
- P4 stateful/admin backup execution remains disabled.
- `scripts/smoke-test --offline` passes locally.
