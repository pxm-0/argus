# M5 Sealed Sandbox Runtimes

M5 migration uses two independent rootless Docker cells:

| Trust domain | Unix identity | Storage and socket |
| --- | --- | --- |
| `personal-sandbox` | `argus-personal-sandbox` | `/var/lib/argus/personal-sandbox` |
| `work-sandbox` | `argus-work-sandbox` | `/var/lib/argus/work-sandbox` |

Each cell receives a distinct subordinate UID/GID allocation, user-owned
storage, rootless Docker daemon, RootlessKit network namespace, named
administrative namespace, and default-drop nftables table. The rootless port
driver is disabled. A host egress guard for the sandbox UID is installed before
the lingering user manager can start, so daemon/firewall startup cannot create
an outbound network gap. Bootstrap does not import, deploy, stop, or expose a
workload.

Review the plan before applying either cell:

```text
scripts/argus-m5-sandbox-bootstrap --domain personal-sandbox --plan
scripts/argus-m5-sandbox-bootstrap --domain work-sandbox --plan
```

Apply only from the reviewed server revision:

```text
sudo scripts/argus-m5-sandbox-bootstrap \
  --domain work-sandbox \
  --apply \
  --acknowledge-sandbox-cell
```

An already-active rootless daemon is not restarted by an idempotent reapply.
`systemctl is-active` only proves the process is running — a 2026-07-30 outage
left a daemon reporting active while unable to create a container at all
(`EOVERFLOW` on `containerd-mount`, root cause never identified). Every apply
now also runs `docker run --rm hello-world` through the cell's own socket and
refuses to report success if that fails, whether or not the daemon was just
restarted. This is the rebuild-and-verify gate: run apply against a rebuilt
cell and trust the exit code, not just `daemonRestarted` in its output.

The bootstrap backs up subordinate-ID files and every affected unit, helper,
firewall file, and prior service state beneath
`/var/lib/argus/bootstrap-backups/`. Any failed apply automatically restores
that state. Before a workload is staged, an operator can explicitly restore a
successful apply:

```text
sudo scripts/argus-m5-sandbox-bootstrap \
  --domain work-sandbox \
  --rollback /var/lib/argus/bootstrap-backups/work-sandbox-<timestamp>-<id> \
  --acknowledge-sandbox-rollback
```

Rollback validates the root-owned backup and requires the container, image,
volume, and staged-path inventory to match the pre-apply digest. An unchanged
existing workload such as the accepted personal-sandbox pilot does not block a
config rollback. For a newly created cell, run this rollback before activating
its capability issuer/domain agent; the bootstrap refuses to remove an active
agent identity. After agent activation, roll back the issuer boundary first.

After both runtimes exist, activate the reviewed issuer/domain-agent boundary:

```text
sudo scripts/argus-m5-capability-issuer --preflight
sudo scripts/argus-m5-capability-issuer \
  --apply \
  --acknowledge-m5-capability-issuer
```

Acceptance requires distinct subordinate-ID ranges and network namespaces,
active rootless daemons/firewalls/domain agents, empty target namespaces before
staging, rootful Docker-socket denial, a disabled Funnel, and online smoke with
zero failures and warnings.

## Resolver

The sandbox netns inherits the host stub resolver at `127.0.0.53`, where nothing
listens inside the namespace, so container DNS dead-ends regardless of firewall
policy. The rootless daemon is therefore started with `--dns $CELL_RESOLVER`,
defaulting to `10.0.2.3` — the address slirp4netns serves DNS on over the
domain's uplink. Override with `ARGUS_SANDBOX_RESOLVER` when a domain needs a
different resolver.

The resolver grants nothing on its own: queries still traverse the sandbox
firewall, which only allows port 53 to the resolver named in a declared egress
policy. A sealed workload stays sealed. See `docs/ARGUS_M5_WORKLOAD_CUTOVER.md`
for the declaration format.

Changing this value takes effect when the daemon unit is reinstalled and the
daemon restarts, which stops every workload in that domain. Treat it as a
maintenance-window change, not a live edit.
