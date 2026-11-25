# Three splits: sandbox, staging, prod — threat model, phases and rollback

Decision: [D030](ARGUS_V1_DECISIONS.md). Like the D027 and D029 documents, this
one describes controls and failure modes, not live weaknesses.

## Before and after

| Cell | Before | After (role) |
|---|---|---|
| `legacy-rootful` | legacy kind; default label for anything unclassified; holds the quarantined rootful runtime (#345) | role `quarantine`, outside the three splits; unclassified stays admission-denied |
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
| Leftover state in the reused cell reaches dev runs | Phase 0 audited the cell; phase 2 removes the retired workload's firewall policy, wipes the Docker data root and re-bootstraps the cell before any dev run uses it. |
| Unreleased staging code reaches live data | `kadath` and `hastur` leave the staging cell. Staging then holds only staging workloads and loses its egress. |
| A dev or staging image ends up in prod | Promotion accepts only staging to prod, checked against the registry roles in `argus promote` and in the privileged lifecycle agent. Prod images still come only through `argus-image-import` by pinned digest; dev images are never pinned. |
| Code drifts from the registry, so a firewall or guard skips a cell | Every domain list reads the registry, and a test fails when any list, schema, sudoers entry or unit template disagrees with it. |
| An operator confuses a role with a cell ID (`work-sandbox` is the sandbox) | Operator views, doctor and CLI output print `role (cell)` together. Sudoers and firewall code take the cell from the registry, never from a typed role. |
| An unclassified workload lands somewhere by default | Unclassified workloads are placed in quarantine with `admission: denied`, so no agent will run them. |
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

Runbook: [`RUNBOOKS/d030-phase2-cell-reset.md`](RUNBOOKS/d030-phase2-cell-reset.md).
First give the prod cell its own namespace and firewall helper files and
point its units at them, without a restart. Before eaabe55 the bootstrap gave
it helpers under the sandbox cell's name, and the full bootstrap refuses the
prod cell because its inner policy is workload-managed. Then remove the
retired workload's inner policy, wipe the sandbox cell's Docker data root,
re-apply its bootstrap and restart its agent and collectors. There is nothing
to re-key: every cell shares the one issuer key.

- **Verify:** prod units run only prod helpers, and prod's guard, namespace
  and inner table are unchanged with `nodens-production` at 200; the sandbox
  bootstrap exits 0 including its `hello-world` gate; the sandbox cell has its
  host guard, named namespace and inner table, and its RootlessKit child is
  not in the host namespace; the pairwise matrix shows the cell reaches
  nothing.
- **Rollback:** restore prod's two unit files from the runbook backup and
  reload systemd; the sandbox cell holds no workload, so stop it again or use
  the bootstrap `--rollback`, then restore its two `.nft` files.

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

### Phase 4: move `kadath` to prod (code + server) (#450)

Runbook: [`RUNBOOKS/d030-rehome.md`](RUNBOOKS/d030-rehome.md). It re-homes the
accepted cutover (spec domain, runtime files, volume, accepted state) and
lets the cutover script's own `--reconcile` start and verify the target,
instead of a new tool. The volume is copied with a tar stream through
rootless containers on both sides, so in-namespace ownership survives the
different subordinate-ID maps, and is compared by a per-file manifest.

No existing tool moves state between two sealed cells.
`argus-m5-workload-cutover` moves workloads from the legacy rootful daemon
only. The privileged agent's sealed-domain move fences the source and starts
the target's Compose project, but it does not copy named volumes, so the
target would start empty. This phase therefore first builds a fenced
cell-to-cell move for one workload, as its own reviewed PR:

1. Preflight: source healthy, target project absent, enough capacity, and a
   fresh verified backup (`argus-m5-workload-db-backup` for `kadath`).
2. Fence the source (restart policy `no`, writers stopped) and journal each
   step before it runs, as the legacy cutover does.
3. Copy state through a logical dump and restore (Postgres for `kadath`),
   never a raw volume copy across different subordinate-ID maps. Then compare
   the restore fingerprint.
4. Rebuild the root-owned runtime files for the prod cell's identity, move
   the ingress socket to `managed-ingress/`, start the target, and require
   health.
5. Re-point the tailnet Serve port to the new socket, retarget the reconcile
   timer, cutover evidence and database backup spec, and leave the source
   stopped, with its volume kept until acceptance.

The same PR updates `config/workloads.json`, the classification
(`stage: production` in the managed zone) and the manifest.

- **Verify:** health 200 through the unchanged tailnet URL; the restore
  fingerprint matches; the prod cell's firewall verify shows `kadath` without
  egress; the backup timer writes from the new cell.
- **Rollback:** before the target starts, restore the source and unfence it.
  After that, follow D018: the source stays fenced, and writes made in prod
  are reconciled by hand before the source is ever restarted.

### Phase 5: move `hastur` to prod (code + server) (#451)

Use the same tool as phase 4. Before cutover, add `hastur`'s bridge-scoped
HTTPS egress to the prod cell's declared egress and host guard. Its named data
volume moves through a stopped-writer archive restored as the prod cell's
identity, plus a content checksum. After cutover, remove the HTTPS allowance
from the staging cell's host guard and inner firewall. Correct the backup
docs, which still describe `hastur` as running under the rootful runtime.

- **Verify:** `hastur` health 200 and its outbound HTTPS works; outbound
  HTTPS from `nodens-production` and `kadath` fails; staging has no egress.
- **Rollback:** as in phase 4, then restore the staging egress allowance
  and remove the prod one.

### Phase 6: model cleanup (code only) (#452)

Remove the `work` realm and `work-managed` from the registry, state,
schemas, validators and bootstrap guards. Workloads may target only the
staging and prod cells. `legacy-rootful` keeps the persisted kind `legacy`
and carries the role `quarantine`; unclassified workloads already get
`admission: denied` there, so they cannot run anywhere by default.

- **Verify:** full CI; the drift test proves the work realm and
  `work-managed` are gone and that schemas allow only staging and prod
  targets. The server state store was checked first and holds no `work`
  realm records.
- **Rollback:** revert the PR.

### Out of scope

Resolving the quarantined rootful runtime (#345) and then retiring the
quarantine cell. Renaming cells. A separate public cell (see residual risks).
