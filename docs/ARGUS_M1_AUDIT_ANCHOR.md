# Argus M1 Off-Host Audit Anchor

The M1 audit ledger is hash-chained on `oreochiserver`. An off-host anchor is
a small, secret-safe checkpoint containing only the latest sequence and hash.
It proves that a future server ledger cannot silently rewrite the history that
preceded the checkpoint.

The checkpoint exporter refuses an absent, empty, or tampered ledger. It does
not create a ledger, contact a network service, or copy files off-host.

## Export on oreochiserver

After the M1 mutation service has produced at least one accepted audit event:

```bash
cd /srv/argus
sudo python3 scripts/argus-m1-audit-checkpoint
```

Before exporting, verify the canonical entity store, both writer projections,
and the hash-chained ledger together. The command prints only counts and
digests; it does not disclose workload data or host details.

```bash
sudo python3 scripts/argus-m1-verify
```

After an onboarding PR (`scripts/argus-workload-onboard`) merges and the
server has pulled it, register the new active workloads in private M1 before
any retirement reconcile; the retirement reconcile refuses while an active
workload is missing from M1. Registration is insert-only: it adds, at revision
1, only workloads that are active in reviewed config, absent from M1, and not
listed as retired, to the entity store and both writer projections. It never
updates or deletes a row and refuses any present row that differs from config,
any undeclared stale row, and any row that would be overwritten. The preview
returns counts only. Apply checkpoints both SQLite stores under
`runtime/argus/m1/onboarding-backups/` first and records a hash-chained audit
intent and outcome. `argus-m1-verify` passes afterwards only once no declared
retired rows remain, so run the retirement reconcile next when one is pending.

`sudo argus m1 sync` runs both reconciles in one pass: it prints the plan and
a digest, and `--apply --confirm <digest>` passes the acknowledgements
internally only when the digest matches the freshly recomputed plan.

```bash
sudo python3 scripts/argus-m1-reconcile-onboarded-workloads
sudo python3 scripts/argus-m1-reconcile-onboarded-workloads \
  --apply --acknowledge-onboarded-workload-registration
```

If a workload is formally retired from the active inventory, reconcile its
private M1 rows only through the retirement registry. The preview returns
counts only. Apply refuses any missing or undeclared stale record, checkpoints
both SQLite stores first, and records a hash-chained audit intent and outcome.
It removes only declared retired rows and reprojects an already-present active
row only to the exact reviewed configuration.

```bash
sudo python3 scripts/argus-m1-reconcile-retired-workloads
sudo python3 scripts/argus-m1-reconcile-retired-workloads \
  --apply --acknowledge-retired-workload-reconciliation
sudo python3 scripts/argus-m1-verify
```

`config/argus/retired-workloads.json` is the explicit deletion allowlist for
that operation. It is not an admission mechanism and cannot remove an active
workload or alter routes, runtime, or configuration.

If verification reports missing explicit legacy quarantine records, reconcile
only those missing records from the existing denied default, then rerun the
legacy import and verification. This does not admit a workload or alter its
runtime, access, routes, or classification beyond explicit legacy quarantine.

```bash
sudo python3 scripts/argus-m1-reconcile-legacy-classifications --apply --acknowledge-quarantine-reconciliation
sudo python3 scripts/argus-m1-import-legacy
sudo python3 scripts/argus-m1-verify
```

The private `runtime/argus/audit-checkpoint.json` file is mode `0600` and
contains no credentials, addresses, paths, or workload data.

## Copy and verify on the operator PC

Create an operator-managed directory on the PC and copy the checkpoint there.
Do not place the copy under the server checkout or a server-mounted directory.
Because the exported server file is intentionally root-owned mode `0600`, stage
a temporary owner-readable copy first. The checkpoint contains only its sequence
and hashes, but remove this staging file immediately after copying it.

```bash
sudo install -o argus -g argus -m 0600 \
  /srv/argus/runtime/argus/audit-checkpoint.json \
  /home/oreo/argus-m1-audit-checkpoint.json
```

```powershell
New-Item -ItemType Directory -Force C:\Users\Admin\Argus\audit-anchors
scp oreo@oreochiserver:/home/oreo/argus-m1-audit-checkpoint.json C:\Users\Admin\Argus\audit-anchors\audit-checkpoint.json
```

From the PC's repository checkout, verify the copied file before recording the
private anchor receipt:

```bash
python3 scripts/argus-m1-audit-checkpoint --verify /mnt/c/Users/Admin/Argus/audit-anchors/audit-checkpoint.json
```

Keep prior checkpoint files; do not overwrite them. The PC copy is the
independently managed off-host anchor for M1.

After the PC verification succeeds, remove only the temporary server copy:

```bash
rm /home/oreo/argus-m1-audit-checkpoint.json
```
