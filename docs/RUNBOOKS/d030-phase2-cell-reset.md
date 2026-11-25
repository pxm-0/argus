# D030 phase 2: split prod's cell helpers, then reset the sandbox cell

Decision: [D030](../ARGUS_V1_DECISIONS.md), phase 2 of
[`TRUST_SPLITS.md`](../TRUST_SPLITS.md), issue #448. Run as root on
`oreochiserver` from the installed release. Part A must finish before part B.

## Why the order matters

Before eaabe55, the cell bootstrap gave every cell except `personal-sandbox`
the helper prefix `argus-work-sandbox`. The `personal-managed` bootstrap
therefore wrote its namespace and firewall helpers under
`/usr/local/lib/argus/argus-work-sandbox-{netns,firewall}`, and its units still
run those paths. Re-bootstrapping `work-sandbox` first would rewrite files the
prod cell's units depend on. Part A gives prod its own helper files without
restarting anything; part B can then rebuild `work-sandbox` freely.

The full bootstrap refuses the prod cell on purpose (its inner policy is
workload-managed), so part A is a file copy and unit edit, not a bootstrap.

## Part A: give prod its own helpers (no restart)

```text
B=/var/lib/argus/bootstrap-backups/personal-managed-helper-split-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$B"
cp -a /usr/local/lib/argus/argus-work-sandbox-netns /usr/local/lib/argus/argus-work-sandbox-firewall \
  /etc/systemd/system/argus-personal-managed-namespace.service \
  /etc/systemd/system/argus-personal-managed-firewall.service "$B"/
# Both helpers must name only personal-managed before they are reused.
! grep -q work-sandbox /usr/local/lib/argus/argus-work-sandbox-netns /usr/local/lib/argus/argus-work-sandbox-firewall
install -o root -g root -m 0755 /usr/local/lib/argus/argus-work-sandbox-netns /usr/local/lib/argus/argus-personal-managed-netns
install -o root -g root -m 0755 /usr/local/lib/argus/argus-work-sandbox-firewall /usr/local/lib/argus/argus-personal-managed-firewall
sed -i 's#/argus-work-sandbox-netns #/argus-personal-managed-netns #' /etc/systemd/system/argus-personal-managed-namespace.service
sed -i 's#/argus-work-sandbox-firewall$#/argus-personal-managed-firewall#' /etc/systemd/system/argus-personal-managed-firewall.service
systemctl daemon-reload
/usr/local/lib/argus/argus-personal-managed-netns ensure   # idempotent: reloads the same guard and policy
```

Verify:

- `systemctl show -p ExecStart -p ExecStop` on both prod units names only
  `argus-personal-managed-*` helpers, and both units stay active.
- `nft list tables` still lists `argus_personal_managed_host_guard`;
  `/run/netns/argus-personal-managed` exists; the prod RootlessKit child still
  holds `argus_personal_managed`.
- `nodens-production` answers 200 on its tailnet URL.

Rollback: copy the two unit files back from `$B`, `systemctl daemon-reload`,
and delete the two `argus-personal-managed-*` helpers. Nothing was restarted.

## Part B: reset and re-bootstrap the sandbox cell

Preconditions: part A verified; the cell's daemon, domain agent and
collectors are stopped (phase 0 stopped them); the cell holds no containers
or volumes.

```text
B=/var/lib/argus/bootstrap-backups/work-sandbox-reset-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$B"
cp -a /etc/argus/argus-work-sandbox.nft /etc/argus/argus-work-sandbox-host-guard.nft "$B"/
# The installed inner policy is the retired workload's; the bootstrap installs the default.
rm -f /etc/argus/argus-work-sandbox.nft
# Wipe the docker data root; phase 0 showed only the bootstrap gate image in it.
rm -rf --one-file-system /var/lib/argus/work-sandbox/docker-data /var/lib/argus/work-sandbox/rootlesskit
/opt/argus/current/scripts/argus-m5-sandbox-bootstrap --domain work-sandbox --apply --acknowledge-sandbox-cell
systemctl enable --now argus-domain-agent@work-sandbox.service \
  argus-rootless-docker-collector@work-sandbox.service \
  argus-user-schedules-collector-work-sandbox.service
```

The capability replay store stays: it holds only replay records, and every
cell shares the one issuer key, so there is nothing cell-specific to re-key.

Verify:

- The bootstrap exits 0, including its `hello-world` gate.
- `nft list tables` lists `argus_work_sandbox_host_guard`;
  `/run/netns/argus-work-sandbox` exists.
- The cell's RootlessKit child is not in the host network namespace, holds
  `argus_work_sandbox`, and has no listeners.
- Part A's prod checks still pass, and `nodens-staging` answers 200.

Rollback: the cell holds no workload. Stop the daemon and units again, or
restore the bootstrap's own backup with its `--rollback` mode, then restore
the two `.nft` files from `$B`.
