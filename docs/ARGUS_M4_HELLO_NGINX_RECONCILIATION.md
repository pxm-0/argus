# Argus M4 hello-nginx Reconciliation

The first physical M4 cutover completed on `oreochiserver` on 2026-07-20. The
stateless `hello-nginx` service moved from the legacy rootful runtime into the
sealed `personal-sandbox` rootless runtime.

Sanitized server evidence established that:

- the legacy source was fenced;
- the target container started and remained running;
- the nginx configuration validated inside the target;
- the target has no published host ports or host mounts;
- the sandbox namespace has no TCP listener;
- the legacy loopback endpoint was retired; and
- the cutover evidence record validated as JSON.

The tracked M4 placement overlay now classifies `hello-nginx` as
`personal-sandbox`. The M0/M1 legacy classification remains as the immutable
import/quarantine baseline and is explicitly reported as superseded by M4.

Compatibility access and workload registries no longer advertise the retired
loopback endpoint. Direct health, logs, restart, and access actions are disabled
until a domain-local typed agent can perform them without giving the central
control plane the sandbox Docker socket.

After pulling this reviewed change on `oreochiserver`, reconcile the Git-deployed
compatibility entry into the private M1 SQLite projection through the exact,
journaled writer transform, then verify M1 parity:

```bash
cd /srv/argus
sudo python3 scripts/argus-m4-hello-nginx-reconcile-deployed
sudo python3 scripts/argus-m1-verify
```

The transform refuses any JSON or projection state other than the reviewed
before/after pair and requires the successful private cutover evidence.

## Accepted persistence checkpoint

The personal-sandbox pilot passed its persistence checkpoint on
`oreochiserver` after a controlled host reboot on 2026-07-21. The dedicated
user manager restored the rootless daemon with the cgroup v2 `systemd` driver,
and the root-owned oneshot unit restored the default-drop firewall inside the
verified RootlessKit child network namespace.

Post-reboot evidence verified all of the following:

- the daemon and `hello-nginx` recovered automatically;
- the target remained healthy and the source remained fenced;
- the RootlessKit namespace differed from the host and had no TCP listener;
- the namespace firewall unit was enabled and completed successfully;
- the target retained no published ports or host mounts; and
- the private M1 projection retained audit and entity parity for 10 entities.

Run the read-only gate on `oreochiserver` after the required host reboot:

```bash
cd /srv/argus
sudo python3 scripts/argus-m4-hello-nginx-persistence-verify
```

The command emits boolean-only evidence and exits nonzero unless every gate
passes, including the delegated `systemd` driver and a boot newer than the
recorded cutover. The accepted post-reboot result was `verified: true` with an
empty `failedChecks` list.
