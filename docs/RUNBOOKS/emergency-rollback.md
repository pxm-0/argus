# Emergency Rollback

Server-side runbook for undoing a bad change. Git/PR stays the source of truth
for reviewed config: revert in Git first, then bring the server to match. All
steps are deterministic shell; none needs an AI or external service.

## 0. Snapshot before any risky change

```bash
sudo /srv/argus/scripts/argus-backup-snapshot --reason before-<change>
sudo /srv/argus/scripts/argus-backup-snapshot --verify /var/backups/argus-snapshots/<file>
sudo /srv/argus/scripts/argus-backup-snapshot --restore-plan <file>   # prints steps only
```

The snapshot holds consistent SQLite copies (SQLite backup API, never `cp`) of
the M1 state, entity store, audit ledger, operations, session, and per-domain
capabilities databases; `/etc/argus` (keys and tokens); M1 journals and
`audit-checkpoint.json`; and the git HEAD/status, `nft list ruleset`,
`tailscale serve status --json`, and `argus-*` unit list. A `manifest.json`
carries a sha256 per member; `--verify` re-reads the archive and checks every
hash and each database's `integrity_check`. Output is only paths and
fingerprints, never secret values.

- Archives are mode 0600 root in `/var/backups/argus-snapshots/<UTC>-<reason>.tar`.
- When an age recipient file is configured (`--recipient-file` or
  `ARGUS_SNAPSHOT_AGE_RECIPIENTS`, public keys only) the file is
  `.tar.age`; verify it with `--identity <private key file>`. Without a
  recipient file the command refuses unless `--allow-plaintext` is given,
  because the archive would contain `/etc/argus`.
- Retention keeps the newest 14 plus any archive with a sibling
  `<archive>.pinned` file (`touch <archive>.pinned`).
- The age private key must live off the server. Copy snapshots off-host before
  a change that could lose the disk.

## 1. Bad Argus merge

1. Revert the PR on GitHub (`gh pr revert <n>`) and merge the revert, or note
   the last known-good sha: `git -C /srv/argus log --oneline -5`.
2. On the server: `git -C /srv/argus fetch origin` then
   `git -C /srv/argus merge --ff-only <previous-sha-or-main-with-revert>`.
   Moving a checked-out bad commit backwards (`reset --hard`) is an operator
   decision; prefer the reviewed revert.
3. Diff the units against what is installed:
   `diff -ru /srv/argus/systemd /etc/systemd/system | grep argus`. If a unit
   changed, install the previous unit files and run `systemctl daemon-reload`.
4. Restart in order (section 3) and smoke: `argus doctor`,
   `/srv/argus/scripts/argus-m1-verify`, `/srv/argus/scripts/smoke-test`.

Schema compatibility: migrations are forward-only. If the bad merge migrated a
store (operations or session database), older code may refuse the newer
schema. The restore point is the `*.pre-vN.bak` file written next to the
database before the migration (for example
`/var/lib/argus/control/operations.sqlite3.pre-v3.bak`), or the pre-change
snapshot. Stop the services, move the migrated database aside, copy the
`.pre-vN.bak` back with the same owner and mode, then roll back the code and
start. Changes written after the migration are lost; check the audit ledger.

## 2. Bad deploy pin

1. Revert the pin PR (the one that changed the workload image digest) and merge.
2. Pull on the server: `git -C /srv/argus pull --ff-only`.
3. Import the previous digest if it is no longer present:
   `sudo ./scripts/argus-image-import --domain <domain> --image <repo>@sha256:<previous>`.
4. Redeploy through the normal deploy path and confirm workload health.
   Do not edit the pin on the server by hand.

## 3. Wedged domain agent

Restart bottom-up so dependents never see a half-started dependency:

```bash
sudo systemctl restart argus-capability-issuer
sudo systemctl restart argus-control-api         # requires argus-operation-worker
sudo systemctl restart argus-operation-worker
sudo systemctl restart 'argus-domain-agent@*'    # then legacy-rootful if used
journalctl -u 'argus-*' -n 100 | cat
```

Check `systemctl list-units 'argus-*'` for failed units before moving on. If an
operation is stuck, use `argus operation show <id>` and
`argus operation recover <id>`.

## 4. M1 store corruption

1. Confirm: `sudo ./scripts/argus-m1-verify` fails, or
   `sqlite3 <db> 'PRAGMA integrity_check'` is not `ok`.
2. Stop services (reverse of section 3's order), pick the newest verified
   snapshot, and follow `--restore-plan <file>`. Keep the corrupt database as
   `<name>.pre-restore.<UTC>`.
3. Restore `db/m1-state.sqlite3`, `db/entity-store.sqlite3`,
   `db/audit.sqlite3`, and the journals together; never a subset.
4. Verify against the independent checkpoint:
   `./scripts/argus-m1-audit-checkpoint --verify <restored audit-checkpoint.json>`
   and `./scripts/argus-m1-verify`. Audit entries after the snapshot are lost;
   if the live checkpoint is newer, keep it for the incident record.

## 5. Issuer or domain key loss

- Archive exists: restore only the affected `etc-argus/capability-issuer/` or
  `etc-argus/domain-keys/` members from the verified snapshot, keeping the
  recorded owner and mode, then restart the issuer and agents.
- No archive: regenerate the key with the domain bootstrap
  (`argus-m5-capability-issuer` / `argus-m4-personal-sandbox-bootstrap`),
  re-enrol the domain agents, and treat every capability issued under the lost
  key as revoked. Rotate any token that may have been exposed.

## 6. Firewall or Tailscale lockout (break-glass)

Use the host console or provider recovery shell; SSH over the tailnet may be
gone.

1. Open the console as root. Extract `state/nft-ruleset.nft` and
   `state/tailscale-serve.json` from the newest verified snapshot (stage it as
   in `--restore-plan` step 2).
2. Firewall: `nft -c -f <ruleset>` to syntax-check, then `nft -f <ruleset>`.
   If the snapshot's ruleset file is empty or fails `-c`, reload the reviewed
   files in `/etc/argus/*.nft` instead (see `sandbox-firewall-remediation.md`).
   Do not `nft flush ruleset`: it drops sandbox egress isolation, the host
   guard and the Docker/Tailscale chains, leaving the sandbox fail-open. Only
   as a last resort, stop the sandbox domain agents and workloads first and
   reapply the host guard rules immediately after the flush.
3. Tailscale: `systemctl restart tailscaled`, `tailscale status`; reapply the
   serve config with `tailscale serve reset`, then recreate the routes from the
   saved JSON (`TAILSCALE_ACCESS_STANDARD.md`).
4. Confirm the dashboard answers on the tailnet and the host guard rules are
   back (`nft list ruleset`), then record what broke and revert the PR.
