# Rootless data-root primary-GID recovery

<!-- sudoers: root-shell-runbook (one-time maintenance-window steps; run from a root shell, not the narrowed operator allowlist) -->

Use this runbook when a sandbox rootless Docker daemon is API-active but a
real local container fails with `EOVERFLOW`, `operation not permitted`, or an
equivalent unmapped-ownership error after the sandbox account's primary GID
changed. This is a private runtime metadata migration. It does not alter
network policy, publish ports, or activate any public provider.

The recovery is intentionally separate from PostgreSQL volume ownership.
Repair the rootless namespace-root mapping first; then run the workload's
narrow database ownership repair.

## Read-only plan

Resolve the current account and subordinate mappings, then supply the reviewed
historical host GID explicitly:

```text
id argus-personal-sandbox
grep '^argus-personal-sandbox:' /etc/subuid /etc/subgid
sudo scripts/argus-m5-rootless-gid-repair \
  --domain personal-sandbox \
  --plan \
  --from-gid 981
```

The plan prints counts only. It refuses if the selected GID is root, the
current primary GID, a subordinate GID, or owns any selected entry under a UID
other than the exact sandbox UID. It stays on the Docker data-root filesystem
and does not follow symlinks or active mounts.

Before apply, stop workload reconciliation timers for the selected domain and
confirm no cutover is running. The tool also takes the global M5 cutover lock,
so contention fails closed.

## Apply

This operation stops only the selected domain's rootless Docker daemon. All
containers in that domain are briefly unavailable. The tool records the exact
running-container, named-volume, and Compose-project inventory; stops the
daemon; rescans the boundary; writes a root-only checksum-bound path manifest;
and changes only the selected entries' group. UID, mode, bytes, named volumes,
and Compose project names are preserved. Containers are explicitly quiesced
before the daemon stops, and restart policies that could bypass this sequence
are rejected. After the daemon returns, the domain's inner firewall is
reapplied and verified before any workload container is restored.

```text
sudo scripts/argus-m5-rootless-gid-repair \
  --domain personal-sandbox \
  --apply \
  --from-gid 981 \
  --acknowledge-rootless-gid-repair
```

Success requires all of the following:

- the daemon becomes API-ready;
- the vendored `hello-world` image runs with `--network none`;
- the exact pre-running container set is restored;
- container IDs, named volumes, and Compose project names are unchanged.

The sanitized result names a summary below
`/var/lib/argus/rootless-gid-repair/<domain>/`. The manifest and summary are
root-owned mode `0600`; neither contains workload data, environment values, or
credentials.

Before Docker is restarted, an apply failure restores the manifested GIDs and
the exact pre-running set. Starting Docker is the forward-recovery boundary:
the daemon may update engine metadata immediately, so a later firewall,
container-probe, or workload failure never rewrites the accepted GIDs back to
the stale group. The tool retries bounded runtime recovery and otherwise writes
a root-only `recovery-required` summary with stable failure classes while
leaving the migrated metadata in place.

Resume that exact forward recovery only from its root-owned summary:

```text
sudo scripts/argus-m5-rootless-gid-repair \
  --domain work-sandbox \
  --recover /var/lib/argus/rootless-gid-repair/work-sandbox/<timestamp>/repair-summary.json \
  --acknowledge-rootless-gid-recovery
```

Recovery revalidates the manifest, requires zero remaining stale-GID entries,
binds the current container/volume/Compose inventory to the pre-migration
digest, and restores the exact pre-running container IDs. Containers start in
their declared Compose dependency order, including health-gated dependencies;
the command never recreates a container or named volume.

Accepted ingress sidecars need an additional lifecycle step. Two bind layouts
are accepted, and any other `/run/argus-ingress` source fails closed:

| Layout | Bind source | Accepted directory state |
| --- | --- | --- |
| Cutover runtime | `/var/lib/argus/migration-runtime/<domain>/<workload>/<stage>/ingress` | `root:root` `0711` (root-locked) |
| Typed-deploy ingress, including production `personal-managed` (`nodens.dev`) | `/var/lib/argus/<kind>-ingress/<workload>`, where `<kind>` is the domain suffix (`managed`, `sandbox`) | the domain identity's own UID and primary GID, `0700` or `0710` |

Every directory above the bind leaf must be a real, root-owned directory; a
symlink anywhere in the chain is refused. Because both sandbox domains share
`sandbox-ingress`, the leaf owner check is what stops one domain from
touching the other's directory. The repair records each bind directory's
owner and mode, temporarily hands only those exact directories to the domain
identity at `0700`, removes only a stale `upstream.sock` owned by that
identity, starts the recorded containers, waits for the replacement sockets,
and then restores the recorded owner and mode. Cutover runtimes are therefore
root-locked again, while typed-deploy directories keep their domain owner so
later releases can restart the sidecar. A failed restart restores every
prepared directory before reporting recovery required.

## Explicit rollback

Rollback is for a reviewed post-migration regression. It restores only the
manifested group metadata; it never removes containers, images, volumes, or
files.

```text
sudo scripts/argus-m5-rootless-gid-repair \
  --domain personal-sandbox \
  --rollback /var/lib/argus/rootless-gid-repair/personal-sandbox/<timestamp>/repair-summary.json \
  --acknowledge-rootless-gid-rollback
```

Rollback requires an accepted `succeeded` summary and an exact manifest
checksum. It preflights every path before the first change, stops only that
domain's daemon, restores the prior GID, restarts the daemon, and restores the
running set observed immediately before rollback. Because the prior mapping
may itself be degraded, verify the daemon and workloads before deciding to
retain a rollback.

## Workload acceptance after repair

Re-enable the domain reconciliation timers only after all affected workloads
pass workload-specific checks. For a PostgreSQL workload, require both
`pg_isready` and a real `SELECT 1`, application readiness, a custom-format
`pg_dump`, and `pg_restore --list`. Run the exact scheduled Argus smoke service
and require zero failures and zero warnings. Keep Funnel, Cloudflare tunnels,
DNS changes, router ports, public routes, PostgreSQL exposure, and Docker-socket
exposure disabled.

The installed scheduled smoke service runs the same vendored, no-network
container probe for both domains as root-only `ExecStartPre` commands. It
writes those commands against a root-owned executable and fixture under
`/usr/local/lib/argus`, never the operator-writable checkout. It then
writes sanitized mode-`0644` status below
`/run/argus-rootless-runtime-probe/`; the unprivileged scheduled runner can
read those results but never receives either Docker socket. Missing, failed,
or stale probe evidence fails the scheduled smoke. Any ordinary smoke warning
also makes the scheduled run fail, enforcing the zero-warning acceptance gate.
