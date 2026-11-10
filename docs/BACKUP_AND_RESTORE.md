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

## Sandboxed database backups

Host-side `docker compose exec` cannot reach a sealed sandbox daemon, so any
pre-cutover database backup schedule stops working the moment a workload moves
(#266). Sandboxed databases are dumped through the domain's own rootless socket:

```bash
sudo ./scripts/argus-m5-workload-db-backup --workload kadath
```

The dump first resolves the `postgres` UID/GID from the exact immutable image
used by the workload, then verifies that every entry in the database volume is
owned by that mapped account. This matters because the retained images do not
share one account convention (Kadath uses `999:999`; Intake uses `70:70`). The
dump then runs inside the sandbox. Only the role and database name are selected
from the inspected container environment; the environment is never printed and
no credential is read from the repository. The artifact is verified with
`pg_restore --list` before it replaces the night's copy. A partial dump is
removed rather than kept. Artifacts land in
`/var/backups/argus-m5-workload-db/<workload>/`, root-owned `0600`, with the
newest 14 retained.

If the ownership preflight reports a mismatch, inspect it without changing the
workload:

```bash
sudo ./scripts/argus-m5-workload-db-backup \
  --workload kadath --action check-ownership
```

Repair is deliberately opt-in and workload-scoped. It snapshots the exact
PostgreSQL volume, stops only the selected database container when it is
running, applies the image-derived ownership repair, starts the container, and
requires both
`pg_isready` and a real `SELECT 1` query. It restores the snapshot if ownership
or PostgreSQL query readiness does not verify. A root-owned per-workload lock
prevents a scheduled dump and an ownership repair from overlapping:

```bash
sudo ./scripts/argus-m5-workload-db-backup \
  --workload kadath --action repair-ownership --confirm kadath
```

Run the normal backup service only after the repair command reports
`"verified": true`. Never use the repair action for an arbitrary container or
volume; the script refuses any volume that is not discovered from the selected
database service.

Install the schedule per workload:

```bash
sudo install -m 0644 templates/systemd/argus-workload-db-backup@.service \
  templates/systemd/argus-workload-db-backup@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now argus-workload-db-backup@kadath.timer
```

Retire any pre-cutover replacement, including user-level units, which do not
appear in a root `systemctl list-timers` sweep:

```bash
sudo -u oreo XDG_RUNTIME_DIR=/run/user/1000 systemctl --user disable --now kadath-backup.timer
```

After a workload migration, audit user crontabs, `/etc/cron.d`, system timers,
**and** every per-user `systemctl --user` timer for references to the old source
path or legacy container name. Two schedules were missed at M5 cutover because a
system-level sweep cannot see user-level units.

## Hastur file backup

Hastur runs rootful, outside the sandbox, so its data and login credentials are
plain host directories rather than a database behind a sandboxed daemon
(`/home/oreo/hastur/data`, `/home/oreo/hastur/auth`). Like kadath before #266,
this had no backup. `argus-m5-hastur-backup` tars both paths directly — no
docker or sandbox socket involved:

```bash
sudo ./scripts/argus-m5-hastur-backup --workload hastur
```

Each archive is verified as listable before it replaces the night's copy; a
partial archive is removed rather than kept. Artifacts land in
`/var/backups/argus-m5-workload-files/hastur/`, root-owned `0700`, with the
newest 14 of each (`data-*.tar.gz`, `auth-*.tar.gz`) retained.

Install the schedule:

```bash
sudo install -m 0644 templates/systemd/argus-hastur-backup.service \
  templates/systemd/argus-hastur-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now argus-hastur-backup.timer
```

## Nightly encrypted snapshots and the pull directory

`argus-backup-snapshot.timer` runs `scripts/argus-backup-snapshot --reason nightly`
at 02:10 UTC (`Persistent=true`, `RandomizedDelaySec=5m`), before the 02:35
workload dumps. Archives are age-encrypted to the public keys in
`/etc/argus/snapshot-recipients.txt` and stay in `/var/backups/argus-snapshots`
(root `0700`).

- Retention: only `*-nightly.tar.age` is pruned (newest 14). Reason-named
  snapshots (`pre-deploy` and similar) are kept 60 days, or until pinned with a
  `<archive>.pinned` file.
- After a successful run, encrypted archives are mirrored (never plaintext) to
  `/var/backups/argus-snapshots-pull` (`oreo:oreo 0750`, files `0640`) so the Mac
  can pull without root. Create it once:
  `sudo install -d -o oreo -g oreo -m 0750 /var/backups/argus-snapshots-pull`.
- `/var/lib/argus/snapshot-last.json` (`{timestamp,size}`, `0644`) and
  `/var/lib/argus/backup-status.json` record freshness. The status file carries
  `staged_tar_verified` (the tar was verified before encryption) and
  `final_verified` (the final bytes were re-read; false for `.age`, because the
  identity is never on the server). A failing run triggers
  `argus-backup-snapshot-failure.service`, which writes `status: "failed"`.
- `--verify <file> [--identity <age identity>]` also compares against the previous
  snapshot in the same directory (`--previous FILE` to choose, `--no-compare` to
  skip) and fails if a `db/*` or `etc-argus/*` member disappeared or shrank by
  more than 50 percent. Run it from the Mac, which holds the identity.

Install:

```bash
sudo install -m 0644 systemd/argus-backup-snapshot.service \
  systemd/argus-backup-snapshot-failure.service systemd/argus-backup-snapshot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now argus-backup-snapshot.timer
```

### Encrypted dumps

`argus-m5-workload-db-backup` and `argus-m5-hastur-backup` take
`--age-recipient-file FILE`. The dump or tar is verified in the root-only tree
first, then encrypted to a partial file in the pull dir and published with
`os.replace`. Kadath keeps the newest 14 copies there. Hastur is frozen, so the
pull dir holds exactly one encrypted copy each of `data` and `auth`. The kadath
unit template passes the flag; run hastur once by hand:

```bash
sudo ./scripts/argus-m5-hastur-backup --workload hastur --age-recipient-file /etc/argus/snapshot-recipients.txt
```

The age identity is held by the operator (password manager plus paper copy); it
is never stored on the server or in this repository.
