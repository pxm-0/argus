# Three splits: sandbox, staging, prod — threat model, phases and rollback

Decision: [D030](ARGUS_V1_DECISIONS.md). Like the D027 and D029 documents, this
one describes controls and failure modes, not live weaknesses.

## Before and after

| Cell | Before | After (role) |
|---|---|---|
| `legacy-rootful` | legacy kind; default label for anything unclassified; holds the quarantined rootful runtime (#345) | `quarantine` kind, outside the roles; unclassified fails closed |
| `personal-sandbox` | `nodens-staging`, `kadath-staging`, `kadath`, `hastur`, D029 dev runs | **staging**: `nodens-staging`, `kadath-staging` |
| `personal-managed` | `nodens-production` | **prod**: `nodens-production`, `kadath`, `hastur` |
| `work-sandbox` | provisioned, empty (its only workload was retired) | **sandbox**: `argus-dev` runs only |
| `work-managed` | schema only | removed |

Cell IDs, Unix users, sockets, firewall tables, units and keys keep their
names. `config/argus/domains.json` maps each cell to its role and kind, and is
the only list code may read.

## Assets and actors

- **Assets:** prod data (`kadath`'s database, `hastur`'s data), the public
  route (D027), staging workloads and their server-local secrets, the host and
  the tailnet.
- **Untrusted input:** everything inside a dev image; unreleased staging
  images; anything reaching the public route.
- **Trusted:** the operator, the reviewed root-owned release, the rootless
  Docker and RootlessKit runtime.

## Threats and controls

| Threat | Control |
| --- | --- |
| A dev run escapes its container and takes over staging | Dev runs move to their own cell. An escape lands as the sandbox cell's user, which holds no workloads, no secrets and no egress. The D029 firewall carve-out leaves the staging cell. |
| Leftover state in the reused cell reaches dev runs | Phase 2 audits and wipes the cell's storage, volumes and capability store, and issues new issuer keys before any dev run uses it. |
| Unreleased staging code reaches live data | `kadath` and `hastur` leave the staging cell. Staging then holds only staging workloads and loses its egress. |
| A dev or staging image ends up in prod | Promotion accepts only staging to prod, checked against the registry roles in `argus promote` and in the privileged lifecycle agent. Prod images still come only through `argus-image-import` by pinned digest; dev images are never pinned. |
| Code drifts from the registry, so a firewall or guard skips a cell | Every domain list reads the registry, and a test fails when any list, schema, sudoers entry or unit template disagrees with it. |
| An operator confuses a role with a cell ID (`work-sandbox` is the sandbox) | Operator views, doctor and CLI output print `role (cell)` together. Sudoers and firewall code take the cell from the registry, never from a typed role. |
| An unclassified workload lands somewhere by default | Unclassified fails closed instead of defaulting into the quarantine cell. |
| Prod egress for `hastur` is used by another prod container | The inner firewall grants HTTPS egress only to `hastur`'s pinned bridge, as it does in staging today. `nodens-production` and `kadath` keep no egress; the phase 5 check proves it from each of them. |
| Dropping the work realm lets work and personal data mix | No work workloads exist. Any work workload needs a new decision and its own cell before it is onboarded. |

## Residual risks

- **Prod shares one daemon between the public site and live data.** A
  container escape from `nodens-production`, the only public workload, would
  reach `kadath`'s and `hastur`'s data in the same cell. Accepted because the
  site is static with no accounts, forms or secrets, it sits behind the D027
  tunnel, and no escape reaches another cell. The trigger to revisit is any
  dynamic feature on the public site; the fix then is a separate public cell
  built by the same bootstrap.
- **The prod host guard opens HTTPS egress for the whole cell user.** The host
  guard sees only RootlessKit's UID, so the bridge scoping lives in the inner
  firewall alone. This is the same arrangement the staging cell has today.
- **Cell names no longer match roles.** Accepted to avoid re-provisioning live
  identities; mitigated by always printing role and cell together.
- **Stateful moves need reconciliation on rollback.** Writes made in prod
  after a D018 cutover are not copied back automatically.

## Phases

Every phase is its own issue and PR. Phases marked **server** change
`oreochiserver` only after the operator approves that phase, and end with
doctor and online smoke green. Phases that change a cell also attach the
pairwise trust-domain matrix.

### Phase 0: read-only audit (server, no changes) (#446)

List what the reused cell still holds: storage, images, volumes, capability
store, issuer keys, sudoers entries, schedules. Confirm where every running
workload lives.

- **Verify:** an acceptance summary of the inventory; nothing written.
- **Rollback:** none needed.

### Phase 1: role registry (code only) (#447)

Add `config/argus/domains.json` (cell, role, kind) and its loader. Point the
hard-coded lists at it: topology order, sandbox firewall, host guard, M4
bootstrap, manifest validator, collector deploy, server-sim provisioning, the
bash bootstrap guards and both schemas. Add the drift test. Make `argus
promote`, `validate-manifests` and the privileged lifecycle agent check
staging to prod by role. Show `role (cell)` in views.

- **Verify:** full CI; the drift test fails on a deliberately mismatched list;
  promote refuses a same-role and a prod-to-staging move.
- **Rollback:** revert the PR. Nothing on the server reads the registry until
  the next release install.

### Phase 2: reset the sandbox cell (server) (#448)

Stop the reused cell's agent and collectors, wipe its storage and capability
store after the phase 0 inventory confirms nothing needs keeping, re-apply the
cell bootstrap, and issue new issuer keys through the capability issuer.

- **Verify:** bootstrap apply exits 0, including its `hello-world` gate;
  issuer preflight is green; the pairwise matrix shows the cell reaches
  nothing.
- **Rollback:** the cell holds no workload, so rollback is the bootstrap
  `--rollback` from its backup and re-issuing the previous issuer state from
  the issuer's own backup.

### Phase 3: move dev runs to the sandbox cell (code + server) (#449)

`argus-dev-sandbox` and the firewall dev carve-out take their cell from the
registry's sandbox role instead of a hard-coded name. Import the preview
Caddy image into the sandbox cell through `argus-image-import`, re-render
sudoers, create the dev slot directories, and point the two tailnet preview
routes at the new slots. Then remove the dev carve-out from the staging cell.

- **Verify:** the `DEV_ENV_PROTOCOL.md` smoke run (test and preview);
  `argus-sandbox-firewall --verify` for both cells with a preview running; a
  dev container started in the staging cell now fails firewall discovery.
- **Rollback:** `argus-dev purge`, revert the PR, install the previous
  release, and point the preview routes back at the staging cell's slots.

### Phase 4: move `kadath` to prod (server) (#450)

D018 fenced migration: fence writes, take and verify a backup, restore into
the prod cell, compare the database fingerprint, switch its tailnet ingress
socket, move its database backup spec to the prod cell.

- **Verify:** health 200 through the unchanged tailnet URL; restore
  fingerprint matches; the prod cell's firewall verify shows `kadath` without
  egress; the backup timer writes from the new cell.
- **Rollback:** the D018 procedure: re-point ingress to the staging cell,
  unfence the source, and reconcile any writes made in prod by hand.

### Phase 5: move `hastur` to prod (code + server) (#451)

Same procedure as phase 4. Before cutover, add `hastur`'s bridge-scoped HTTPS
egress to the prod cell's inner firewall and its host guard. After cutover,
remove the HTTPS allowance from the staging cell's host guard and inner
firewall. Correct the backup docs, which still describe `hastur` as running
under the rootful runtime.

- **Verify:** `hastur` health 200 and its outbound HTTPS works; outbound
  HTTPS from `nodens-production` and `kadath` fails; staging has no egress.
- **Rollback:** the D018 procedure, then restore the staging egress allowance
  and remove the prod one.

### Phase 6: model cleanup (code only) (#452)

Remove the `work` realm and `work-managed` from state, schemas, validators
and fixtures. Turn `legacy` into the `quarantine` kind and make unclassified
workloads fail closed.

- **Verify:** full CI; admission refuses an unclassified workload instead of
  placing it in quarantine.
- **Rollback:** revert the PR.

### Out of scope

Resolving the quarantined rootful runtime (#345) and then retiring the
quarantine cell. Renaming cells. A separate public cell (see residual risks).
