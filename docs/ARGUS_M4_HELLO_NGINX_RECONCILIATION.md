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

## Remaining gate

This reconciliation does not close M4. Before the personal-sandbox pilot is an
accepted checkpoint, server evidence must verify daemon and workload recovery
after service restart and host reboot, repeat the isolation checks, and resolve
or explicitly accept the observed rootless cgroup warning. No additional
workload should move into the cell before that gate passes.

Run the read-only gate on `oreochiserver` after the required host reboot:

```bash
cd /srv/oreo-cloud
sudo python3 scripts/argus-m4-hello-nginx-persistence-verify
```

The command emits boolean-only evidence and exits nonzero unless every gate
passes, including the delegated `cgroupfs` driver and a boot newer than the
recorded cutover.
