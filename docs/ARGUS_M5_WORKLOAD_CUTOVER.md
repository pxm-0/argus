# M5 Retained Workload Cutover

This phase moves the five retained Compose projects from the legacy rootful
daemon into the sealed rootless sandboxes. It consumes a new final stage
created after each workload's declared writers are stopped.

## Fixed placement

| Workload | Sandbox | Compose project | Private endpoint |
| --- | --- | --- | --- |
| Hastur | `personal-sandbox` | `hastur` | tailnet HTTPS `8445` |
| Kadath | `personal-sandbox` | `kadath-live` | tailnet HTTPS `8443` |
| Nodens | `personal-sandbox` | `nodens` | tailnet HTTPS `8444` |
| LociGraph | `personal-sandbox` | `locigraph` | tailnet HTTPS `443` |
| Intake OS | `work-sandbox` | `intake-os` | tailnet HTTPS `8446` |

The target Compose network remains `internal: true`. A Caddy sidecar on that
network listens on a sandbox-owned Unix socket. Tailscale Serve connects
directly to the socket. The cutover does not publish a Docker port, start
Funnel or Cloudflare, create DNS, or alter router rules.

The sandbox firewall permits forwarding only between Docker bridge
interfaces inside the same trust domain. Input, output, cross-domain, and
slirp/tap egress remain default-deny.

## Fenced flow

For one workload:

1. Confirm every source container is running and healthy, the target Compose
   project is empty, the immutable ingress image is present, and staging has
   enough capacity.
2. Capture the live containers' runtime environment in memory. Values are
   never printed, backed up, or committed. Root constructs the runtime files
   atomically below a no-follow, root-owned anchor. Files remain root-owned,
   mode `0640`, and are only group-readable by the sandbox identity.
3. Stop the workload's declared writers.
4. Run a final logical/content restore drill while those writers remain
   stopped.
5. Stop the remaining source services.
6. Verify the root-only stage checksums and target-Compose digest, rerun the
   staging security validator, then write the root-owned target runtime
   Compose file with mode `0640`, group-readable by the sandbox identity.
7. Start the target with the original Compose project name and no published
   ports.
8. Require every target container to be running, every configured healthcheck
   to pass, and the Unix-socket HTTP probe to succeed.
9. Switch only that workload's Tailscale Serve port to the Unix socket and
   verify the tailnet HTTPS endpoint.

The root-owned runtime leaf uses a deterministic short digest of the stage ID
so every host-side ingress socket stays below Linux's Unix-socket pathname
limit. The full stage ID remains in cutover evidence.

The final stage also proves that each workload image can be unpacked by the
rootless daemon. If an OCI layer is incompatible with the daemon's UID map,
staging creates a stopped container from the immutable source image, exports
that pristine image filesystem, imports it into the target, reconstructs
supported operational image configuration through Compose, and proves the
imported image can unpack. It never exports the live workload container.
Environment comes from the separately captured live container configuration
and never appears in import arguments. The root-only rootfs artifact,
source/target image mapping, and checksums are recorded in stage evidence.
Images that declare volumes or unsupported runtime metadata are refused rather
than flattened.

A root-only phase journal is fsynced before every mutation. Source restart
policies are fenced to `no` before writers stop, so a reboot cannot
automatically start the legacy writers beside a target.
If pre-authority recovery is needed, the existing stopped source containers
are restarted directly—already-healthy dependencies are preserved and stopped
dependencies precede writers—so captured configuration is preserved and
Compose interpolation cannot replace credentials with blanks.

Target containers also use restart policy `no`. Each accepted cutover enables
a root-owned, retrying systemd timer that reconciles only the authoritative
target. Reconciliation waits for the rootless Docker socket, verifies the
source fence, prepares the private socket directory, starts the preserved
Compose project, re-locks the socket directory, and rechecks the tailnet
endpoint. The periodic retry also handles a sandbox-daemon-only restart. This
prevents daemon-restart races from starting both source and target writers.

For stateful workloads, authority is durably committed immediately before
the target starts. Failures before that boundary restore the previous
firewall and restart policies and may restart the source only after target
absence is proven. Failures after that boundary keep the source stopped and
require manual target-authority recovery; stale source data is never started
automatically. Nodens is stateless and retains the explicit rollback
operation.

## Sealed credentials

Staging excludes workload credential directories, so any credential a sandboxed
workload needs is delivered from `/etc/argus/workload-credentials/<workload>/`
as a read-only bind rendered by cutover. Never a `/home/oreo` bind.

Provision before preflight (hastur example, `personal-sandbox`):

```bash
sudo install -d -o root -g argus-personal-sandbox -m 0750 \
  /etc/argus/workload-credentials/hastur
sudo install -o root -g argus-personal-sandbox -m 0640 \
  /path/to/threads-storage.json \
  /etc/argus/workload-credentials/hastur/threads-storage.json
```

Preflight and apply refuse to continue unless the directory is root-owned
`0750`, grouped to the sandbox identity, and contains only root-owned `0640`
regular files. The mount target and any workload-specific runtime environment
(hastur: `CRAWL_SCHEDULE_ENABLED=true`, `CRAWL_SCHEDULE_MECHANISM=internal`)
live in that workload's cutover spec.

## Declared egress

Egress is a declared protocol, not an ad-hoc firewall edit. Every workload spec
must carry an `egress` key; `None` means sealed on purpose and renders no rules.

```python
"egress": {
    "resolver": "10.0.2.3",
    "allow": (("tcp", 443),),
    "reason": "threads.net crawl",
}
```

Rules are derived from the declaration only: a forward allowance scoped to that
workload's bridge, the matching return path, a resolver allowance on 53, and a
nat masquerade for that bridge. A workload without a declaration cannot acquire
a hole, and the bridge is pinned to `argus-<workload>` so a rule names one
interface instead of Docker's non-deterministic `br-<id>`.

RootlessKit translates container connections into host connections owned by the
sandbox identity. The host guard therefore needs a second, coarser allowance for
the `argus-personal-sandbox` UID on TCP/443. `argus_host_guard.py` renders that
allowance before the UID's default drop; the inner firewall remains the gate that
restricts it to Hastur's pinned bridge. The `work-sandbox` host guard receives no
allowance and stays fully sealed. Applying the sandbox bootstrap backs up the
installed guard before replacing it and validates that workload and volume
inventory did not change.

The nft table is per trust domain, so applying policy installs every
declaration in that domain:

```bash
sudo ./scripts/argus-m5-workload-cutover \
  --workload hastur \
  --apply-egress \
  --acknowledge-m5-egress-policy
```

Reconcile reports `egressPolicyDrift` but never installs policy on a timer.
Converging automatically is a deliberate later step, not a side effect.

Verify after any policy change or cutover:

```bash
sudo ./scripts/argus-m5-egress-verify --domain personal-sandbox
```

Each workload is probed in both directions: declared destinations must be
reachable, undeclared destinations must fail closed, and a hung probe counts as
a failure rather than a pass. Exit status is non-zero when any expectation or
the drift check fails.

## Refreshing an accepted target

A stateful cutover is one-way. `--apply` refuses while the target is present
and the source is fenced, `--rollback` is gated for stateful workloads, and
`--reconcile` deliberately reuses the accepted Compose byte for byte. So a
declaration added to a spec *after* acceptance cannot reach the running
workload.

Hastur hit all three at once: sealed credentials, the `CRAWL_SCHEDULE_*`
overlay, and a declared egress policy each landed after it was cut over, so
the running project had no `/app/auth` mount, no schedule variables, and a
non-deterministic `br-<id>` bridge that no declared rule could name.

`--refresh` rewrites the accepted Compose in place and recreates the project:

```bash
sudo ./scripts/argus-m5-workload-cutover \
  --workload hastur \
  --refresh \
  --acknowledge-m5-workload-refresh
```

It requires accepted cutover evidence and a still-fenced source, and it
validates credentials before touching anything. The runtime directory, ingress
binds, socket path, and Serve mapping are unchanged, so only container and
network identity move — which is what renames the bridge. `down` never
receives `-v`, so named volumes carrying workload state survive; for hastur
that is `argus_stage_hastur__app_data` mounted at `/app/data`.

The previous Compose is kept beside it as `docker-compose.json.before`. If any
verification fails, that file is restored and the known-good project is brought
back up. The source stays fenced either way: stale data is never started
automatically.

Refreshing with no spec drift is a no-op and reports `"refreshed": false`
rather than bouncing a healthy workload. Each accepted refresh increments
`refreshGeneration` in the cutover evidence.

## Commands

```bash
sudo ./scripts/argus-m5-workload-cutover --workload nodens --preflight
sudo ./scripts/argus-m5-workload-cutover \
  --workload nodens \
  --apply \
  --acknowledge-m5-workload-cutover
```

Stateless rollback:

```bash
sudo ./scripts/argus-m5-workload-cutover \
  --workload nodens \
  --rollback \
  --acknowledge-m5-workload-cutover-rollback
```

Run workloads sequentially. The global lock refuses overlapping cutovers.
Do not delete the stopped source containers or final stage artifacts until
the final acceptance checkpoint is approved.
