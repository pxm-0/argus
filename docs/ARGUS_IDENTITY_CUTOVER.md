# Argus identity cutover

This runbook completes the project rename after the implementation PR and the
GitHub repository rename have landed. It changes names only: no workload
Compose project, route, listener, firewall rule, mount, or exposure policy is
changed.

## Preflight

Run on `oreochiserver` from the existing checkout:

```bash
cd /srv/oreo-cloud
git fetch origin main
git switch main
git pull --ff-only origin main
sudo ./scripts/argus-identity-cutover --preflight
```

## Apply

```bash
cd /srv/oreo-cloud
sudo ./scripts/argus-identity-cutover \
  --apply \
  --acknowledge-argus-identity-cutover
cd /srv/argus
```

The script backs up legacy systemd and Caddy state under
`/var/lib/argus/identity-backups`, moves the checkout, installs and preserves
the prior enabled/active state of renamed units, installs renamed operator
links, validates Caddy before reload, retires legacy identities, and runs the
M1 and M4 verification gates.

## Rollback

If the cutover stops before verification, use the backup path printed by the
script. Stop the new `argus-*` units, move `/srv/argus` back to
`/srv/oreo-cloud`, restore the saved unit and Caddy files, run
`systemctl daemon-reload`, and start only the units recorded as active in
`old-unit-state.txt`. Do not change routes or workload Compose project names.
