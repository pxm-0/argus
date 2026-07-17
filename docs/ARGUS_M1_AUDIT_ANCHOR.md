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
cd /srv/oreo-cloud
sudo python3 scripts/argus-m1-audit-checkpoint
```

The private `runtime/argus/audit-checkpoint.json` file is mode `0600` and
contains no credentials, addresses, paths, or workload data.

## Copy and verify on the operator PC

Create an operator-managed directory on the PC and copy the checkpoint there.
Do not place the copy under the server checkout or a server-mounted directory.

```powershell
New-Item -ItemType Directory -Force C:\Users\Admin\Argus\audit-anchors
scp oreo@oreochiserver:/srv/oreo-cloud/runtime/argus/audit-checkpoint.json C:\Users\Admin\Argus\audit-anchors\audit-checkpoint.json
```

From the PC's repository checkout, verify the copied file before recording the
private anchor receipt:

```bash
python3 scripts/argus-m1-audit-checkpoint --verify /mnt/c/Users/Admin/Argus/audit-anchors/audit-checkpoint.json
```

Keep prior checkpoint files; do not overwrite them. The PC copy is the
independently managed off-host anchor for M1.
