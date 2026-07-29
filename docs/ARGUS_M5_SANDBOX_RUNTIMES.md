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
