# P5 Backup Retention

P5 adds retention pruning for approved backup artifacts. It does not enable
backups for additional workloads.

## Command

Preview:

```bash
scripts/oreo-backup-prune
```

JSON preview:

```bash
scripts/oreo-backup-prune --json
```

Apply:

```bash
scripts/oreo-backup-prune --apply --confirm "prune oreo backups"
```

## Rules

- Only workloads with `backup.backupAllowed=true` are considered.
- The destination must be under
  `/srv/oreo-cloud/runtime/backups/<workload-id>`.
- `backup.retention.keepLast` decides how many newest run directories stay.
- Apply mode requires the exact confirmation phrase.
- Pruning writes an audit event.

## Current State

`hello-nginx` is the only backup-enabled workload. P4 stateful/admin workloads
remain backup-disabled until their restore gates are satisfied.
