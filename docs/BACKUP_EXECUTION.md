# Backup Execution

P2 enables backup execution for one approved low-risk workload:

```text
hello-nginx
```

Backups remain opt-in. A workload must have both operation permission and backup metadata enabled in its manifest.

## Command

```bash
scripts/argus-backup-run hello-nginx --confirm hello-nginx
```

The confirmation value must exactly match the workload ID.

## Artifact Shape

The backup runner writes timestamped artifacts under:

```text
/srv/argus/runtime/backups/hello-nginx/YYYYMMDD-HHMMSS/
```

Each artifact contains:

```text
manifest.json
files.tar.gz
checksums.sha256
restore-plan.md
backup-summary.json
```

## Safety Rules

- Destination must stay under `/srv/argus/runtime/backups/<workload-id>`.
- Source backup is allowed for `hello-nginx`.
- `.env`, `.env.*`, secret-like, and credential-like files are excluded from source archives.
- Env, database, named volume, and bind mount backups remain blocked unless a later phase explicitly implements them.
- Runtime backup artifacts are ignored by Git.

## Restore Test

P2 performs only a non-destructive restore test. See:

```text
docs/RUNBOOKS/backup-restore-test.md
```
