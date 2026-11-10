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

LociGraph was retired before this retained-workload cutover. See
[`RETIRED_LOCIGRAPH.md`](RETIRED_LOCIGRAPH.md) for the destruction evidence.
Intake OS was retired after cutover and `work-sandbox` now holds no workload;
see [`RETIRED_INTAKE_OS.md`](RETIRED_INTAKE_OS.md).

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
endpoint. A source that was explicitly retired may be absent: the accepted
evidence must still record `sourceStopped=true`, a positive source container
count, and zero resurrection schedules. The periodic retry also handles a
sandbox-daemon-only restart. This prevents daemon-restart races from starting
both source and target writers.

Historical accepted records created before the resurrection-schedule field are
upgraded only while the source project is still inspectable and the live
schedule sweep is empty. Reconcile writes a root-only copy of the prior record
before binding that zero-schedule observation; an already absent source with
missing evidence remains refused.

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

On an accepted sandbox, update that outer guard through the host-only path:

```bash
sudo ./scripts/argus-m5-sandbox-bootstrap \
  --domain personal-sandbox \
  --apply-host-guard \
  --acknowledge-host-egress
```

This path backs up and validates the guard, proves the inner policy and workload
inventory did not change, and does not restart the sandbox daemon. A full
bootstrap refuses to overwrite a workload-managed inner policy; changing the
inner policy still requires the separately acknowledged `--apply-egress` flow.

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

An accepted workload image may be replaced only when its service, immutable
image ID, source repository, revision, and offline syntax checks are declared in
the workload spec. `--refresh` verifies the target daemon has that exact image,
checks its OCI provenance labels, verifies the declared source-file digests, and
runs every syntax check with `--network none` before stopping the accepted container. The previous Compose is
retained for automatic recovery, and named volumes are never removed.

For Hastur, revision `82e5f437e6858763b37f561bf9094e41920fab05`
includes the in-process scheduler and indexes crawl history by `finished_at`.
Without that index, the growing `raw_json` history spills its newest-first sort
to temporary storage; this rootless overlay rejects the spill with `EOVERFLOW`,
which Node reports as SQLite error 14. Both the workload replacement and its
Caddy 2.11.4 ingress sidecar are flat-rootfs images because their accepted
layered images cannot be instantiated again by the current rootless storage
driver. Refresh proves both pinned images can unpack before stopping the
accepted project. SSH export remains retired in the sandbox: no private key is
delivered, and `AUTO_EXPORT_ON_STORAGE_THRESHOLD=false` prevents a scheduled
crawl from triggering a knowingly unusable export path.

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

## Nodens staging (sandbox) and production (managed)

Operator decision (#322, BRIDGE §7.2): `personal-sandbox` is the staging
environment and `personal-managed` the production environment for every
Nodens project. `nodens-staging` runs in `personal-sandbox` (realm `personal`,
zone `sandbox`, stage `staging`); `nodens-production` runs in
`personal-managed` (zone `managed`, stage `production`). Each has its own
trust domain, Compose project, network, ingress socket, and tailnet route
(BRIDGE §7.7). Both run the same image ID; production never receives a
rebuilt artifact (BRIDGE §7.6).

`nodens-staging` is a typed-deploy, image-pinned workload: it is not
`sandboxReconcileOnly`, has no `argus-m5-workload-*` reconcile timer, and is
never built from source. The legacy sandbox `nodens` workload (`:8444`) is
separate and is retired on its own after staging is verified.

The reviewed runtime is the tracked `workloads/<id>/source/compose.yml`
(`security.trackedByArgusGit: true`); the rest of `source/` stays ignored.
Neither domain publishes ports and both deny default egress, and deploys use
`--pull never`, so images reach a domain only through `argus-image-import`.
The two Compose files may differ only in workload name, image pin,
ingress path, and pinned bridge name.

### Typed-deploy projects in the sandbox firewall

The domain firewall (`argus-sandbox-firewall`, cutover `--apply-egress` and
re-runs, `argus-m5-egress-verify`, reconcile `egressPolicyDrift`) counts two
kinds of project (#354):

- **Cutover projects**: `lifecycle: active` with
  `migration.targetTrustDomain` equal to the domain. Each must be running.
  Rules, egress, connectivity, and the probe matrix are unchanged for them.
- **Typed-deploy projects**: classification `trustDomain` equal to the
  domain, `actions.sandboxReconcileOnly` not true, and manifest
  `operations.deploy.allowed: true`. The manifest must declare
  `runtime.compose.bridge` (`argus-` prefix, at most 15 characters), and the
  Compose network must pin the same name in
  `driver_opts.com.docker.network.bridge.name`. A typed project with no bridge
  declaration refuses the whole domain.

A typed project is optional at runtime. Its bridge always renders exactly one
own-traffic rule, for example
`iifname "argus-ndns-stg" oifname "argus-ndns-stg" accept;`, so the persisted
policy does not change when staging is stopped or deployed. It gets no
egress (an egress declaration naming it is refused), no cross-project
connectivity (a policy naming it is refused), and it is not in the probe
matrix. Discovery still refuses any project that is neither kind, any typed
project on a bridge other than its declared one, and any missing cutover
project.

| Workload | Bridge |
| --- | --- |
| `nodens-staging` | `argus-ndns-stg` |
| `nodens-production` | `argus-ndns-prd` (not yet deploy-enabled) |

After this lands, regenerate and apply the `personal-sandbox` policy once (the
only change is the `argus-ndns-stg` rule); until then reconciles report
`egressPolicyDrift: true`.

| Workload | Trust domain | Compose project | Ingress socket | Tailnet route |
| --- | --- | --- | --- | --- |
| `nodens-staging` | `personal-sandbox` | `nodens-staging` | `/var/lib/argus/sandbox-ingress/nodens-staging/upstream.sock` | `:8450` |
| `nodens-production` | `personal-managed` | `nodens-production` | `/var/lib/argus/managed-ingress/nodens-production/upstream.sock` | `:8451` |

Routes are tailnet-only. Never Funnel, Cloudflare, or a public listener.

### One-time host setup

`route_contract` accepts only loopback HTTP targets, so Argus cannot apply a
Serve mapping to a Unix socket. Create each ingress directory, owned by its
domain's identity, and the Serve mappings by hand, once:

```bash
sudo install -d -m 0711 -o root -g root /var/lib/argus/sandbox-ingress
sudo install -d -m 0700 -o argus-personal-sandbox -g argus-personal-sandbox \
  /var/lib/argus/sandbox-ingress/nodens-staging
sudo install -d -m 0711 -o root -g root /var/lib/argus/managed-ingress
sudo install -d -m 0700 -o argus-personal-managed -g argus-personal-managed \
  /var/lib/argus/managed-ingress/nodens-production
for domain in personal-sandbox personal-managed; do
  sudo ./scripts/argus-image-import --domain "$domain" \
    --image docker.io/library/caddy@sha256:<caddy-digest>
done
sudo tailscale serve --bg --https=8450 \
  unix:/var/lib/argus/sandbox-ingress/nodens-staging/upstream.sock
sudo tailscale serve --bg --https=8451 \
  unix:/var/lib/argus/managed-ingress/nodens-production/upstream.sock
tailscale serve status   # 8450 and 8451, tailnet only
tailscale funnel status  # must be empty
```

Pin the Caddy ID the import prints as the `argus-ingress` image in both
Compose files; it must be the same ID in both domains.

Onboarding changes only tracked config. Once, after an onboarding PR is
pulled on the server, register new workloads in private M1 (insert-only,
audited, checkpointed; see `docs/ARGUS_M1_AUDIT_ANCHOR.md`) before any
retirement reconcile:

```bash
sudo python3 scripts/argus-m1-reconcile-onboarded-workloads
sudo python3 scripts/argus-m1-reconcile-onboarded-workloads \
  --apply --acknowledge-onboarded-workload-registration
```

M1 entity and projection rows derive from the legacy classification, privacy,
and access registries, not from `workload-classification.json`, so moving a
workload between trust domains leaves M1 converged.
`sudo python3 scripts/argus-m1-reconcile-retired-workloads` must report
`alreadyApplied: true` with every count `0`.

### Release flow

The CLI automates steps 1, 2, 6 and 7: `argus release pin nodens-staging
--image ghcr.io/pxm-0/nodens@sha256:<D>` imports the digest into the sandbox
domain, rewrites only the `image:` line, runs `argus check`, and opens the pin
PR (`--dry-run` prints the diff). `argus promote nodens-staging
nodens-production` imports the same digest into the production domain, requires
the same image ID, checks that a staging deploy of that ID succeeded and that
the two Compose files differ only in workload name, compose project, bridge,
ingress path and secret refs, then opens the promotion PR. Neither deploys;
steps 3, 4, 5, 8 and 9 stay manual. The numbered steps below are the manual
equivalent.

1. **Import into staging.** After nodens CI publishes
   `ghcr.io/pxm-0/nodens@sha256:<D>`:
   `sudo ./scripts/argus-image-import --domain personal-sandbox --image ghcr.io/pxm-0/nodens@sha256:<D>`.
   It prints `imageId`, the ID the domain reports. Pin that ID, never `<D>`:
   they can differ. Test that a container can be created from it, to catch a
   rootless EOVERFLOW unpack failure:
   `sudo runuser -u argus-personal-sandbox -- docker --host unix:///var/lib/argus/personal-sandbox/docker.sock create --name argus-import-probe sha256:<ID>`,
   then `... rm argus-import-probe`.
2. **Pin PR.** Set `image: sha256:<ID>` for `nodens` in
   `workloads/nodens-staging/source/compose.yml`. Merge it.
3. **Pull on the server.** `git -C /srv/argus pull --ff-only`. Never edit
   `/srv/argus` by hand.
4. **Deploy staging.** The dashboard has no `workload.deploy` button; use the
   session API from the signed-in dashboard tab's browser console, where
   `app.js` defines `apiPost` (adds the CSRF header and `Idempotency-Key`) and
   `ensureStepUp` (approval needs a step-up session; enter the bootstrap
   credential in the operator field first). Create the preview only after the
   pull, or it is `revision-stale`:

   ```js
   const w = "nodens-staging", operationType = "workload.deploy";
   const parameters = { targetRevision: "sha256:<ID>" };
   const p = (await apiPost(`/api/workloads/${w}/operations/preview`, { operationType, parameters })).payload;
   console.log(p.trustDomain, p.allowed, p.reason, p.confirmationPhrase);
   // stop unless trustDomain === "personal-sandbox" && allowed === true
   const c = await apiPost(`/api/workloads/${w}/operations`, {
     operationType, parameters, previewDigest: p.previewDigest,
     expectedRevision: p.expectedRevision, policyVersion: p.policyVersion });
   await ensureStepUp();
   const a = await apiPost(`/api/operations/${c.payload.operation_id}/approve`,
     { confirmation: p.confirmationPhrase });  // "deploy nodens-staging sha256:<ID>"
   console.log(c.status, a.status, a.payload);
   ```

   Poll `GET /api/operations/<operation_id>` until `succeeded`.
   `argus-domain-agent@personal-sandbox` refuses any revision that is not an
   exact line of `docker compose config --images`, then runs
   `up -d --pull never` and waits up to 60s for domain health.

   Staging may run or be stopped without affecting sandbox egress tooling;
   see [Typed-deploy projects in the sandbox firewall](#typed-deploy-projects-in-the-sandbox-firewall).
5. **Verify staging.** `curl -fsS https://oreochiserver.tail0a3a58.ts.net:8450/healthz`
   succeeds, and the operation ledger records the deploy as succeeded.
6. **Import the same image into production.**
   `sudo ./scripts/argus-image-import --domain personal-managed --image ghcr.io/pxm-0/nodens@sha256:<D>`.
   The printed `imageId` must equal the staging `<ID>`; stop if it differs.
   Run the same container-create probe against the `personal-managed` socket.
7. **Promotion PR.** Pin the same `sha256:<ID>` in
   `workloads/nodens-production/source/compose.yml`. On the first promotion,
   also allow `deploy`, `start`, `stop`, and `health` in that manifest's
   `operations` (every capability starts denied, `operation-not-capable`).
   Merge, then pull on the server.
8. **Deploy production.** Repeat step 4's API sequence with
   `w = "nodens-production"` and the same `targetRevision`; the preview must
   show `trustDomain` `personal-managed` and `allowed` `true`.
9. **Verify production.** `curl -fsS https://oreochiserver.tail0a3a58.ts.net:8451/healthz`.

### Rollback

Open a PR that reverts the affected pin to the previous ID, which is still
loaded in that domain. Merge it, pull on the server, and run
`workload.deploy` (step 4's API sequence) for that workload with the previous
ID. Check that `:8450` (staging) or
`:8451` (production) serves the previous build. Do not prune images in
`personal-sandbox` or `personal-managed` while their IDs are still rollback
targets. To take staging down without a revision change, run
`workload.stop` for `nodens-staging` the same way (`parameters: {}`; the
preview's `confirmationPhrase` is the approval text).
