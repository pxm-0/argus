# Argus V1 Decision and Viability Log

- **Status:** Accepted architecture decisions
- **Date:** 2026-07-14
- **Architecture issue:** [#130](https://github.com/pxm-0/argus/issues/130)
- **Draft PR:** [#136](https://github.com/pxm-0/argus/pull/136)

## Logging Boundary

This repository is public. This log records decisions, generalized conclusions, evidence gaps, and follow-up issues. It must not contain credentials, tokens, environment files, raw logs, private source, workload data, backups, addresses, ports, secret paths, sensitive topology details, or active containment weaknesses that would improve reconnaissance.

Server evidence is collected read-only unless a linked `server-required` issue explicitly authorizes a change. A statement is not treated as verified when the required privileged evidence was unavailable.

## Decisions

### D001: Keep ownership, operating class, and release maturity independent

**Decision:** Model `realm`, `zone`, and `stage` as separate fields.

```text
realm: unclassified | personal | work
zone: legacy | sandbox | managed
stage: none | dev | staging | production
```

**Reason:** Work/personal and sandbox/deployment are independent boundaries. Combining them into environment names makes policy inconsistent and cannot represent managed development separately from ad hoc experiments.

**Constraint:** `unclassified` is allowed only with `zone: legacy`. Sandbox and legacy use `stage: none`. Managed environments require a classified realm and a managed stage.

### D002: Quarantine current resources before classification

**Decision:** Import current resources into `legacy-rootful` as `legacy-unclassified`, not automatically into `lab`.

**Reason:** Current runtime state contains unclassified resources and violations of target containment controls. Calling it `lab` would turn uncertainty into a false maturity claim.

**Follow-up:** [#131](https://github.com/pxm-0/argus/issues/131)

### D003: Use four target trust domains

**Decision:** Target these enforced runtime cells:

```text
personal-sandbox
personal-managed
work-sandbox
work-managed
```

**Reason:** Both ownership and operational maturity require containment. A shared sandbox would allow work and personal credentials or data to mix. A shared managed runtime would weaken the same boundary for durable deployments.

**Follow-up:** [#133](https://github.com/pxm-0/argus/issues/133)

### D004: Use rootless runtime separation on the current host

**Decision:** Give each target trust domain its own Unix identity, rootless Docker daemon, socket, network namespace, host-firewall policy, egress allowlist, storage root, networks, volumes, credentials, routes, backup scope, and systemd units.

**Reason:** The host already has rootless Docker tooling and sufficient baseline capacity. Hardware virtualization is not currently available to the operating system.

**Trust ceiling:** This contains ordinary container, application, credential, network, and per-domain Docker-daemon failures. It does not protect domains from host-root access, a host-kernel compromise, physical access, or host failure.

### D005: Keep the central control plane off raw domain Docker sockets

**Decision:** Domain-local collectors emit normalized observations. Separately authenticated, narrowly scoped domain agents perform approved operations. The central Argus process mounts zero trust-domain Docker sockets and holds no domain capability-signing key.

**Reason:** A central process with unrestricted access to all runtime sockets would collapse the trust-domain boundary it is supposed to enforce.

**Compatibility:** Health, sanitized logs, restart, backup, access, rollback, preview, confirmation, and audit remain available through constrained agent operations.

### D006: Implement two views as three deployments

**Decision:** Ship:

1. a private live operator deployment;
2. a private no-route portfolio mirror;
3. a public static portfolio deployment.

**Reason:** View-only behavior must be architectural. Hiding operator controls in the same live application would leave private data and mutation code inside the public trust boundary.

### D007: Export an allowlisted immutable public artifact

**Decision:** Generate the portfolio from an explicit public snapshot schema. Validate the exact immutable artifact in the no-route mirror, then promote the same digest to the public origin.

**Reason:** A denylist scrub can miss newly added private fields. A live API creates an ongoing path back to the operator estate. Rebuilding after mirror validation breaks artifact provenance.

**Excluded categories:** Internal hostnames, addresses, ports, paths, logs, audit actors, security findings, backup locations, credentials, private project names, and live resource identifiers.

**Follow-up:** [#134](https://github.com/pxm-0/argus/issues/134)

### D008: Give the public origin one ingress route and no return route

**Decision:** The portfolio needs one public route to serve static assets. It has no control API, live Argus client, shared volume, shared secret, or network path back to the primary host or a workload trust domain.

**Requirement:** Host the static portfolio independently so it remains available during home-server downtime and creates no public ingress dependency on the operator host.

### D009: Treat compliance as evidence, not certification

**Decision:** Argus reports whether named controls are declared and observed as effective. It does not claim regulatory, contractual, or third-party certification without a configured standard and independent assessment.

**Reason:** Same-host controls can produce useful audit evidence while still sharing host-root, kernel, hardware, and physical trust.

### D010: Migrate one workload at a time

**Decision:** Classify and move workloads only after the containment baseline, trust-domain model, and target runtime exist. Preserve logical Compose and volume identity while recording the new physical volume and runtime mapping.

**Reason:** Stateful workloads require copy, validate, cut over, health check, and rollback. A big-bang rehome would mix infrastructure redesign with application recovery risk.

**Follow-up:** [#135](https://github.com/pxm-0/argus/issues/135)

### D011: Use SQLite behind a repository boundary

**Decision:** Use SQLite as the canonical Argus V1 entity store. Existing JSON registries remain migration inputs and compatibility outputs. All model consumers use a storage-neutral repository interface.

**Reason:** Argus needs transactions, constraints, indexed relationship queries, and atomic reconciliation. SQLite fits the single-host scope, requires no exposed database service, and is available through Python's standard library on the target host.

**Follow-up:** [#132](https://github.com/pxm-0/argus/issues/132)

### D012: Enforce network isolation outside Docker

**Decision:** Rootless Docker and separate Docker networks are not treated as an inter-domain firewall. Every trust domain receives a network namespace and host-firewall policy that denies host, LAN, Tailscale, legacy-runtime, and cross-domain destinations unless explicitly allowlisted. Host-published ports are prohibited except for approved ingress targets.

**Reason:** Containers attached to separate daemons can still attempt to reach host and routed network addresses. The trust boundary must be enforced where traffic crosses the host network stack.

**Follow-up:** [#133](https://github.com/pxm-0/argus/issues/133)

### D013: Make resource separation non-waivable

**Decision:** A graph relationship records topology but never grants access. Docker sockets, credentials, bind mounts, volumes, and Docker networks cannot cross personal/work or sandbox/managed trust domains. Cross-domain dependencies use only explicitly approved service protocols through authenticated gateways with least-privilege identities.

**Reason:** Allowing generic policy approval to waive resource isolation would collapse the boundary and make compliance evidence meaningless.

### D014: Fail mutations closed

**Decision:** Deny mutations when policy, canonical state, agent authorization, evidence freshness, observation completeness, reconciliation, or durable audit persistence is unavailable, malformed, stale, mismatched, or timed out.

**Break glass:** Recovery uses a separately authorized command that durably writes intent before execution and appends outcome afterward. Reconciliation closes abandoned or indeterminate intent after a crash. Break glass cannot bypass non-waivable isolation or public-exposure rules.

### D015: Use a single-writer journaled store cutover

**Decision:** The repository adapter remains the only writer while JSON is authoritative. Every mutation uses a crash-atomic write-ahead record, synced atomic JSON replacement, and durable commit marker. Recovery reconciles transaction IDs idempotently. The adapter imports a snapshot into shadow SQLite, replays the journal, validates record and semantic parity, pauses writes for a final replay, and atomically switches the adapter. JSON becomes generated read-only compatibility output after cutover.

**Reason:** Independent writers or an undefined dual-write period could lose mutations or make declared and effective state disagree during migration.

**Rollback:** Retain the snapshot and journal through the rollback window and verify parity before reopening writes on either backend.

### D016: Constrain the management plane and agent protocol

**Decision:** Run Argus management in its own trust domain. The central process has no raw runtime sockets, arbitrary shell transport, or long-lived domain mutation credentials. Each operation uses a short-lived, domain-scoped capability bound to the actor, target, operation, expected state revision, policy version, preview digest, approval digest, nonce, and expiry.

**Agent enforcement:** The domain-local agent authenticates the capability, rejects replay, re-evaluates local policy, enforces idempotency, accepts only typed operations, and redacts output. A credential issued for one domain cannot operate another.

### D017: Require identity-backed mutation approval

**Decision:** The current bearer token remains a temporary legacy compatibility mechanism only. It cannot authorize trust-domain operations, portfolio publication, or compliance-grade approvals. Domain mutations require an identity-backed operator session, sensitive-operation re-authentication, and short-lived domain credentials with rotation and revocation.

**Reason:** A shared bearer token cannot provide actor attribution or safe authority across work and personal domains.

### D018: Fence stateful workload migration

**Decision:** Stateful cutover quiesces the source, acquires a migration fence, snapshots data, translates UID/GID ownership for the target rootless identity, copies into a new physical target volume, verifies checksums, starts the target, and validates health and data before release.

**Invariant:** Source and target cannot write concurrently. Rollback stops and fences the target before the source is reopened. Compose and volume logical identity remain stable in Argus while physical runtime identifiers change explicitly.

### D019: Make audit history tamper-evident

**Decision:** Audit records include actor and session identity, request and correlation IDs, trust domain, target, typed operation, policy version, preview and approval digests, declared and observed revisions, before and after digests, sequence, outcome, and denial/error details.

**Integrity:** Records form an append-only hash chain whose checkpoints are replicated and anchored off-host under retention policy. Evidence bundles carry provenance and signatures. Host-root can still forge future events, but cannot silently rewrite already anchored history.

### D020: Validate public values and artifact contents

**Decision:** Public-schema allowlisting is necessary but not sufficient. Public fields also have value constraints, synthetic-by-default data, length and format checks, and denied-pattern scanning. The artifact uses a file allowlist, forbids source maps and debug metadata, scans final bytes, carries provenance, and has its digest reverified at the public origin.

### D021: Gate four-cell rollout on a disposable pilot

**Decision:** Treat rootless trust-domain viability as conditional until one disposable cell proves subordinate-ID allocation, cgroup delegation, user lingering, storage-driver compatibility, networking and firewall behavior, socket permissions, port strategy, backup access, restart recovery, and sustained resource overhead.

**Reason:** Installed tooling and spare capacity prove feasibility, not production readiness.

### D022: Provision privileged host controls out of band

**Decision:** A root-owned, versioned, idempotent bootstrap bundle run directly by the host administrator creates Unix identities, subordinate IDs, namespaces, firewall policy, cgroup delegation, lingering, and systemd units.

**Boundary:** The bootstrap bundle is not a network service, has no dashboard execution path, accepts configuration rather than arbitrary commands, touches no workload runtime socket, backs up and validates every host change, supports rollback, and emits signed redacted evidence for audit import.

### D023: Restrict mutations during the store rollback window

**Decision:** Until the JSON rollback window closes, reject any mutation that cannot be represented in both schemas. Every permitted journal operation has a versioned reverse transform and passes forward-cutover and rollback parity tests. Entity-model-only mutations begin only after legacy rollback is disabled.

### D024: Give trust domains an explicit kind

**Decision:** Trust domains use `kind: management|legacy|workload`. Management has no realm, zone, workload environment, or runtime socket. Legacy requires `realm: unclassified` and `zone: legacy`. Workload domains require `realm: personal|work` and `zone: sandbox|managed`.

### D025: Keep capability issuance out of central Argus

**Decision:** Central Argus transports requests but holds no capability-signing key. A user-held authenticator signs a challenge bound to domain, request and preview digests, and expiry. A domain-local issuer verifies the assertion against bootstrap-provisioned operator public credentials and issues a one-request domain capability.

**Rotation:** Verification keys use an audited overlap window and revocation reaches every domain before old credentials are rejected. A domain issuer or credential cannot authorize another domain.

### D026: Make legacy writes crash-atomic

**Decision:** Each legacy mutation writes and syncs a `PREPARED` journal record, atomically replaces JSON with transaction ID and revision, then writes and syncs `COMMITTED`. Recovery reconciles prepared, applied, and committed IDs and replays idempotently.

**Verification:** Inject crashes at every write, flush, rename, marker, snapshot, replay, cutover, and rollback boundary.

## Viability Evidence

Evidence was collected read-only from the primary host on 2026-07-14. Detailed output remains in the private task transcript and must be recollected under the server-required issue before it is used as acceptance evidence.

### Host capability

- The Linux host had sufficient observed CPU, memory, and storage headroom for a disposable pilot at observation time.
- The current Docker runtime is rootful and uses standard Linux container security options.
- Rootless Docker setup tooling is installed.
- Hardware-backed VM isolation was not available to the observed host configuration.
- OS-container tooling exists but no corresponding service was observed active.

**Conclusion:** The first rootless trust-domain pilot passed D021 on 2026-07-21. The personal-sandbox cell proved subordinate-ID allocation, cgroup v2 delegation through a lingering user manager, rootless overlay storage, a no-port RootlessKit namespace with a boot-restored default-drop firewall, private socket ownership, daemon restart recovery, and host reboot recovery. This accepts the pilot architecture; it does not authorize automatic rollout to additional trust domains or workloads without their own reviewed classification, capacity, migration, and rollback evidence.

### Current containment gaps

- Multiple services have broader host reachability than the target policy allows.
- Existing resources violate target containment controls and require remediation.
- Current containers share a rootful runtime and operator-owned host tree.
- Legacy resource and registry/runtime identity drift exists.
- Tailscale protects intended operator ingress but does not by itself isolate containers, mounts, credentials, data stores, or local-network listeners.

**Conclusion:** The host is viable for Argus, but existing resources must remain quarantined until [#131](https://github.com/pxm-0/argus/issues/131) closes the containment and evidence gaps.

### Evidence gap

The unprivileged session could observe reachability indicators but could not verify privileged firewall policy. Firewall behavior therefore remains unknown rather than assumed safe.

**Required resolution:** Capture privileged firewall and Docker-forwarding evidence under [#131](https://github.com/pxm-0/argus/issues/131) before declaring the containment baseline complete.

## Read-only Commands Used

The following command classes informed the architecture. Outputs were reviewed locally and only sanitized conclusions are retained here.

```text
repository and GitHub state inspection
selected container/runtime inventory commands
managed and legacy root metadata checks
private-ingress status inspection
host capacity and virtualization capability checks
listener and unprivileged firewall-policy inspection
```

## Delivery Ledger

Status snapshot: 2026-07-14. Follow the linked GitHub items for current state.

| Item | Tracking | State |
|---|---|---|
| Trust-domain and portfolio architecture | [#130](https://github.com/pxm-0/argus/issues/130) | In progress in [PR #136](https://github.com/pxm-0/argus/pull/136) |
| Legacy quarantine and containment baseline | [#131](https://github.com/pxm-0/argus/issues/131) | Planned; server required |
| Trust-domain model, policy, and evidence | [#132](https://github.com/pxm-0/argus/issues/132) | Planned |
| Isolated runtime cells and scoped agents | [#133](https://github.com/pxm-0/argus/issues/133) | Planned; server required |
| Portfolio export, mirror, and public origin | [#134](https://github.com/pxm-0/argus/issues/134) | Planned |
| Workload classification and migration | [#135](https://github.com/pxm-0/argus/issues/135) | Planned; server required |

## Change Protocol

New architecture decisions append a numbered entry. A reversal must name the superseded decision, explain why the evidence changed, and link the PR or issue authorizing the change. Runtime observations are timestamped and never silently promoted from observed to declared state.

## Required Adversarial Verification

Containment evidence must include a pairwise trust-domain matrix. From every source domain, tests attempt access to every other domain's runtime socket, storage root, host, LAN, private-overlay, legacy-runtime and cross-domain network destinations, volumes, credentials, routes, and scoped operation agent. Every undeclared path must fail, including after daemon restart and host reboot.

Portfolio fixtures must deliberately include nested denied fields, secret markers, internal addresses, source maps, embedded metadata, live API references, mutation code, and unexpected schema fields. The mirror must block publication when a fixture survives export, the artifact digest changes after validation, or the public origin can reach the operator estate.
