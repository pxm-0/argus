# P5 Backup Retention

P5 adds retention pruning for approved backup artifacts. It does not enable
backups for additional workloads.

## Command

Preview:

```bash
scripts/argus-backup-prune
```

JSON preview:

```bash
scripts/argus-backup-prune --json
```

Apply:

```bash
scripts/argus-backup-prune --apply --confirm "prune argus backups"
```

## Rules

- Only workloads with `backup.backupAllowed=true` are considered.
- The destination must be under
  `/srv/argus/runtime/backups/<workload-id>`.
- `backup.retention.keepLast` decides how many newest run directories stay.
- Apply mode requires the exact confirmation phrase.
- Pruning writes an audit event.

## Current State

No active workload is backup-enabled. P4 stateful/admin workloads remain
backup-disabled until their restore gates are satisfied; the prior
`hello-nginx` source-only backup was retired with that workload. Live smoke
treats this as a passing no-op; it requires a valid latest artifact again as
soon as any active workload enables backup execution.

## Snapshot and dump retention (off-host backups)

These are separate from `argus-backup-prune` above and are enforced by the
scripts that create the archives:

- Server snapshots (`/var/backups/argus-snapshots`): newest 14 `*-nightly.tar.age`;
  reason-named snapshots 60 days or until pinned. See
  [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md).
- Kadath dumps in the pull dir: newest 14. Hastur: one encrypted copy of each
  archive (frozen workload).
- `nodens` is static: it is covered by its image pin plus git, so it has no
  backup artifacts.
- The `/var/backups/argus-m5-workload-staging` staging area is about 20 GB. It
  has no retention and nothing deletes it automatically; any cleanup is a
  separate, operator-approved decision.
