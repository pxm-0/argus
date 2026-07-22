# Backup and Restore

P1 adds backup and restore planning without pretending every workload has a safe
automated backup.

## Commands

```bash
argus-backup-plan <workload-id>
argus-backup-run <workload-id> --confirm <workload-id>
argus-restore-plan <workload-id>
```

## Rules

- Backup plans come from `workloads/<id>/manifest.json`.
- `argus-backup-plan` is read-only.
- `argus-restore-plan` is read-only.
- `argus-backup-run` refuses unless `operations.backupAllowed=true`.
- `argus-backup-run` requires exact workload ID confirmation.
- Backup destinations must live under `/srv/argus/runtime/backups/`.
- Backup output is ignored by Git.
- Env files, secrets, database dumps, and named volumes require explicit future
  implementation before they can be backed up automatically.

## Current P1 Status

`hello-nginx` has a backup plan, but `backupAllowed=false`.

That is intentional for P1:

- the workload has no named volumes
- the workload has no database
- env backup is disabled
- source backup is disabled
- restore automation is not enabled

The current safe behavior is:

```text
argus-backup-plan hello-nginx    # prints plan
argus-backup-run hello-nginx     # blocked
argus-restore-plan hello-nginx   # prints manual restore notes
```

## Runtime Paths

Allowed backup destination pattern:

```text
/srv/argus/runtime/backups/<workload-id>/<timestamp>
```

`runtime/*` is ignored by `.gitignore`, so backup artifacts are not tracked.

## Restore

Restore remains manual in P1. Use `argus-restore-plan <workload-id>` to review:

- backup destination
- restore-tested status
- database restore command, if configured
- migration rollback notes

Do not restore over a running workload without first writing and reviewing a
rollback plan.
