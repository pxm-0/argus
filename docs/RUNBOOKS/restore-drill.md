# Off-host backup pull and restore drill

Argus snapshots are encrypted on the server (age) and pulled to the operator Mac. Two launchd jobs keep
that honest: a twice-daily pull that verifies every archive, and a monthly drill that proves the newest
archive restores. Both run only on the Mac, over ssh as `oreo`, and need no sudo on the server.

## What runs where

| Job | Script | Schedule | Log |
|-----|--------|----------|-----|
| `dev.argus.backup-pull` | `scripts/argus-backup-pull` | 03:30 and 13:30, every 6h, and at load (catches up after sleep) | `~/Library/Logs/argus-backup-pull.log`, `~/Archives/argus-snapshots/verify.log` |
| `dev.argus.restore-drill` | `scripts/argus-restore-drill` | 1st of each month 04:15 | `~/Library/Logs/argus-restore-drill.log`, `~/Archives/argus-snapshots/drill.log` |

The scripts need python 3.12+ and `age` and `rsync`. The plists use the mise python 3.14 and
`/opt/homebrew/bin` on PATH; launchd does not expand `~`, so the plists carry absolute `/Users/oreo` paths.
The macOS system python 3.9 is refused on purpose (it misreads good archives).

## Install (operator, once)

```
cp ops/launchd/dev.argus.backup-pull.plist ops/launchd/dev.argus.restore-drill.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/dev.argus.backup-pull.plist
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/dev.argus.restore-drill.plist
```

Run the pull once by hand and read the log before trusting it:

```
~/.local/share/mise/installs/python/3.14/bin/python scripts/argus-backup-pull
tail ~/Archives/argus-snapshots/verify.log      # every new archive: OK <name> sha256=...
cat ~/Archives/argus-snapshots/.last-ok
ssh oreochiserver 'ls -l ~/argus-pull-ok'       # evidence the pull reached the server
```

Server prerequisite: PR3 merged and deployed, so `/var/backups/argus-snapshots-pull` (oreo:oreo 0750) exists and holds
`*-nightly.tar.age`, `hastur-*.tar.gz.age` and `kadath-*.dump.age`. Check with
`ssh oreochiserver 'ls -l /var/backups/argus-snapshots-pull'`. The pull only runs `rsync` and `touch ~/argus-pull-ok`
as oreo; no sudo and no other server state. Until PR3 is deployed the first run reports RSYNC_FAIL (exit 1) and is harmless.

Rollback (Mac only, nothing to undo on the server): `launchctl bootout gui/$UID/dev.argus.backup-pull` and
`dev.argus.restore-drill`, delete the plists. Archives stay in place; to undo the code, revert the PR.

## What the pull does

1. `rsync --ignore-existing` (never `--delete`) from `oreochiserver:/var/backups/argus-snapshots-pull/` to
   `~/Archives/argus-snapshots/` (0700). Already-known, quarantined and retention-pruned names are not fetched again.
2. Verifies each new archive with `argus-backup-snapshot --verify --identity ~/.config/argus/snapshot-age.key`.
   Good archives are recorded in `SHA256SUMS` and `verify.log`. A failing archive (tampered or truncated)
   is moved to `quarantine/` with a macOS notification. Nothing unverified is ever deleted.
3. Retention on the Mac: the newest 30 `*-nightly` archives; every reason-named archive (`pre-deploy` and so on) is kept.
4. Writes `.last-ok` after a clean run and touches `~/argus-pull-ok` on the server.
5. Notifies when the newest verified archive is older than 36h.
6. Also pulls and verifies the hastur copy (`<name>-<stamp>.tar.gz.age`, newest one per name kept) and the kadath
   dumps (`<workload>-<stamp>.dump.age`, newest 14 per workload): age stream decrypt plus a tar or `PGDMP` check. A
   stale kadath dump raises the same staleness alarm. A missing `age`, a wrong key or an unwritable scratch dir is a
   retry (`RETRY` in verify.log), never a quarantine: only a failure confirmed against a known-good archive quarantines.

Exit codes: 0 ok, 1 verification or rsync failure, 3 stale (over 36h or nothing verified), 75 server
unreachable (retry on the next trigger; it becomes an alarm only when the 36h limit passes).

Triage a quarantined archive: `tail verify.log`, then compare the size with the server copy. A truncated
transfer is fixed by moving the file out of `quarantine/` into a scratch dir and re-pulling; a hash or
decryption failure with the correct key means the server copy is bad: take a fresh snapshot
(`sudo systemctl start argus-backup-snapshot.service`).

## What the drill does

Decrypts the newest archive recorded in `SHA256SUMS` into a 0700 temp dir inside `~/Archives/argus-snapshots`
(never `/tmp`), rebuilds a root (restored runtime and databases, config from the snapshot's git commit when the
local clone has it), then runs `argus-m1-verify`, `argus-m1-audit-checkpoint --verify` and sqlite
`integrity_check` on every database, and starts the control API on a free loopback port against the restored
session and operations databases. The API has no `/health` route, so the check is an unauthenticated
`GET /api/session` answering 401, which proves it opened the restored state. The temp dir is deleted on every
path, the result is appended to `drill.log` (`DRILL_OK` or `DRILL_FAIL <reason>`), and a failure raises a
notification and a non-zero exit. Run it by hand any time: `python scripts/argus-restore-drill`.

A failed drill means do not assume the backups are good: run the pull by hand, check `verify.log`, and take a
fresh snapshot on the server before the next change.

## Age identity custody

The age identity (`~/.config/argus/snapshot-age.key`) is the only way to read any backup. Lose it and every
archive is unreadable.

- Store it in a password manager AND on paper (print the file, keep it somewhere physically separate from the Mac).
  Keep the paper and the password-manager copy in two different places.
- The server holds only the public recipient file; it cannot decrypt its own backups. Never copy the identity to the server.
- The scripts pass the identity path to `age` and never read, print or log it. Do not paste it into chat, tickets or the repo.
- Test custody at least once: from the password-manager or paper copy, restore it to a temp file and run
  `age -d -i <temp> <newest archive> | tar -tf - | head`, then delete the temp file.
- Rotation: generate a new identity, add its public key to the server recipient file, wait for a nightly archive
  to verify under the new key, and keep the old identity until the last archive encrypted to it has aged out.
