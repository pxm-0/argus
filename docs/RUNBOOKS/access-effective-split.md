# Runbook: split server-applied access state out of `config/access.json` (D028)

<!-- sudoers: root-shell-runbook (a one-time migration with every writer stopped; run the sudo steps from a root shell) -->

Before D028 the M1 access writer rewrote the tracked `config/access.json` on the server, so a Cloudflare
activation left the `/srv/argus` checkout dirty (decision: [D028](../ARGUS_V1_DECISIONS.md)). After D028 the
writer only writes the ignored `config/access.effective.json`. This runbook moves an existing dirty file's
`effective`, `lastAppliedAt` and `lastError` into that overlay once, without changing what any reader sees.

cloudflared, its config under `/etc/cloudflared/` and the Cloudflare Access application are never touched, so the
public route keeps its protection at every step. The merged effective state of every workload is the same before,
during and after the split.

## Pre-checks (read-only, still on the old release)

1. `git -C /srv/argus status --porcelain` shows only `M config/access.json`.
2. `git -C /srv/argus diff config/access.json` changes only `effective`, `lastAppliedAt` and `lastError` of existing
   workloads. STOP if `desired`, `urls`, `states` or the workload set differ: that needs a reviewed PR first.
3. Record `stat` of `config/access.json`, `runtime/argus/m1/*` and `runtime/cloudflare-activation/*`. If the evidence
   files are not readable by the operator account, make them 0644 (step 9 does this from now on).
4. `argus m1 verify`, `scripts/argus-doctor --host --json` and `scripts/argus-access-reconcile --offline --json` are green.
5. `runtime/argus/m1/access-journal.jsonl` has no `PREPARED` record without a `COMMITTED` or `ABORTED` one
   (the migrate script refuses otherwise).
6. An unauthenticated `curl -sI` of every public hostname shows the Cloudflare Access redirect. Record it.
7. Back up into `runtime/migration-backups/<stamp>/`: `cp -p` of `config/access.json`, `sqlite3 .backup` of
   `runtime/argus/m1/state.sqlite3` and `runtime/argus/audit.sqlite3`, the journal and the evidence directory.

## Migrate

1. Merge the D028 PR; CI must be green.
2. Stop every writer:

   ```bash
   sudo systemctl stop argus-control-api argus-domain-agent-legacy-rootful 'argus-domain-agent@*'
   ```

3. `git -C /srv/argus pull --ff-only` as the checkout owner. It succeeds because the PR does not touch
   `config/access.json`.
4. With no overlay yet the new code reads the dirty file, so the merged view is unchanged. Doctor's
   "tracked access baseline never holds a Cloudflare effective state" failure is expected until step 6.
5. Dry run as the `access.json` owner and group. The plan must name only the workloads you saw in pre-check 2:

   ```bash
   sudo -u oreo -g argus-control /srv/argus/scripts/argus-access-effective-migrate
   ```

6. Apply. It backs up the working-tree file to `runtime/migration-backups/`, writes the overlay, checks the merged
   view, restores the reviewed bytes and checks again:

   ```bash
   sudo -u oreo -g argus-control /srv/argus/scripts/argus-access-effective-migrate --apply
   ```

7. `git -C /srv/argus status --porcelain` is empty.
8. Install the sealed release of the merged sha ([root-owned-release.md](root-owned-release.md)).
9. Reconcile ownership and modes (overlay oreo:argus-control 0664, evidence 0644):

   ```bash
   sudo /srv/argus/scripts/argus-m5-runtime-permissions
   ```

10. Start the units again:

    ```bash
    sudo systemctl start argus-control-api argus-domain-agent-legacy-rootful 'argus-domain-agent@*'
    ```

## Verify

- `git -C /srv/argus status --porcelain` is empty.
- `argus m1 verify` passes with no `m1 sync`: the merged view equals the old file.
- `scripts/argus-doctor --host`, `scripts/argus-access-reconcile --offline` and smoke are green.
- The dashboard shows each workload's access as before the split.
- `config/access.effective.json` is oreo:argus-control 0664.
- The unauthenticated `curl -sI` still shows the Cloudflare Access redirect.

## Rollback (in this order; the old release install needs a clean tree)

1. Stop the units (Migrate step 2).
2. Capture the current merged view before anything changes, and keep a copy of the overlay:

   ```bash
   cd /srv/argus && sudo -u oreo -g argus-control python3 -c \
     'import json, sys; sys.path.insert(0, "scripts"); from argus_access_state import load_access; from pathlib import Path; print(json.dumps(load_access(Path("config")), indent=2))' \
     > runtime/migration-backups/<stamp>/access.merged.json
   cp -p config/access.effective.json runtime/migration-backups/<stamp>/
   ```

3. `git -C /srv/argus checkout <previous sha>`.
4. Reinstall the previous release ([root-owned-release.md](root-owned-release.md)).
5. Restore `config/access.json` as the owner, keeping its mode:
   - If `runtime/argus/m1/access-journal.jsonl` has no record newer than the backup stamp (no access write since the
     split), `cp -p` the backed-up `access.json`. This is the old dirty state and the old projection parity holds.
   - Otherwise the backup is stale: an activation, rollback or re-apply since the split is only in the overlay and the
     projection. Write `access.merged.json` from step 2 instead. Never answer a parity failure with `m1 sync` from
     the stale backup; that writes the older state into the projection.
6. Delete `config/access.effective.json` (its copy from step 2 stays in the backup directory).
7. `argus m1 verify` passes with no `m1 sync`.
8. Start the units (Migrate step 10).

Nothing at the Cloudflare edge needs undoing.

## From now on

- Every Cloudflare activation or rollback ends with `scripts/argus-m5-runtime-permissions` from a root shell, so the
  root-written overlay, journal, databases and evidence stay readable by the operator-run gates.
- `access.apply` (dashboard, API, CLI) only re-applies the reviewed desired state. Changing desired access, including
  raising it to `cloudflare-public` before the public stage or lowering it after a rollback, is a pull request.
