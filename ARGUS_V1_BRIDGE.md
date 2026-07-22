# Argus V1 Bridge

## From Argus to Argus

- **Status:** Accepted architecture; implementation pending
- **Target:** Argus V1
- **Predecessor:** Argus
- **Scope:** Single-host infrastructure control plane and topology model
- **Primary host:** private single-host deployment
- **Tracking:** [#130](https://github.com/pxm-0/argus/issues/130)
- **Decision log:** [`docs/ARGUS_V1_DECISIONS.md`](docs/ARGUS_V1_DECISIONS.md)
- **Decision date:** 2026-07-14

---

## 1. Purpose

This document defines the transition from Argus into Argus V1.

Argus began as a private, Git-tracked control plane for workloads running on the primary host. Its original purpose was to make existing Docker workloads visible, safer to operate, and harder to expose accidentally.

Argus preserves that foundation while expanding the system from:

> a workload control dashboard for one server

into:

> a living model of projects, environments, deployments, infrastructure resources, and their relationships.

Argus V1 is not a rewrite.

It is a structural migration that keeps Argus’s working operational machinery and introduces a more expressive infrastructure model underneath it.

---

## 2. Current State

Argus already provides a substantial operational foundation.

Its current capabilities include:

- a neutral workload registry
- privacy classification
- desired and effective access state
- route and exposure records
- host and Docker monitoring
- workload discovery
- workload registration
- health checks
- sanitized log previews
- confirmation-gated restarts
- backup contracts
- migration planning
- Cloudflare exposure planning
- audit events
- private Tailscale access
- local-only control API
- smoke testing and operational validation

The current architecture uses a Tailscale-bound Caddy dashboard, a loopback-only Python control API, JSON configuration registries, scheduled metrics collection, and generated static dashboard assets.

The workload registry currently stores runtime identity, Compose configuration, paths, network details, health checks, permitted actions, and migration state. Privacy, access, policy, routes, exposure, and monitoring are stored separately.

The control API already supports discovery, registration, access changes, privacy changes, logs, restart operations, backup operations, metrics, and audit events. Mutations require authentication through a local bearer token.

The monitoring collector gathers host CPU, load, memory, disk, network, process, temperature, Docker container, and Docker resource information.

These capabilities are retained.

---

## 3. Why the Transition Is Needed

Argus models most operational reality through one central object:

```text
Workload
```

A workload currently represents several concepts at once:

```text
project
runtime
service
deployment
network endpoint
health configuration
data resources
backup policy
security classification
migration state
operations
```

This model has reached its natural limit.

The existing workload records are useful for operating known services, but they cannot adequately describe:

- multiple environments for one project
- staging and production separation
- deployment history
- shared and isolated infrastructure resources
- service dependencies
- domain and route chains
- identity-provider relationships
- application inheritance contracts
- the effect of one failure on dependent systems
- declared state versus observed runtime state

Relationships currently exist as nested strings, paths, URLs, and identifiers rather than explicit graph edges.

Argus introduces the missing ontology.

---

## 4. Argus V1 Mission

Argus V1 will become the authoritative operational map of the server.

It will continuously answer four questions:

1. **What exists?**
2. **How is it connected?**
3. **What should be running?**
4. **What is actually running?**

Argus V1 will model the current server as a container platform rather than a loose collection of workloads.

Its central abstraction becomes:

```text
Project
→ Environment
→ Service
→ Deployment
→ Runtime Instance
```

Infrastructure resources exist alongside that hierarchy:

```text
Host
Container
Compose Project
Image
Network
Volume
Database
Endpoint
Domain
Route
Tunnel
Repository
Health Check
Identity Provider
Policy
Contract
```

---

## 5. Design Principles

### 5.1 Preserve operational truth

Argus must describe the infrastructure that actually exists.

It must not invent staging, production, ownership, dependencies, or release processes that are not yet real. Current resources enter Argus as:

```text
realm: unclassified
zone: legacy
stage: none
trust_domain: legacy-rootful
```

`legacy-unclassified` is a quarantine state, not an environment maturity claim. A resource remains there until its ownership, durability, routes, data, backup contract, and runtime identity are known.

Argus separates three concepts that the previous `lab` label conflated:

```text
realm = who owns the system
zone  = how the system is operated
stage = where a managed release is in its lifecycle
```

Environment maturity is earned through actual isolation and operational evidence, not labels alone.

---

### 5.2 Declared, observed, and effective state

Argus generalizes Argus’s existing desired-versus-effective access model.

For every managed entity, Argus distinguishes:

#### Declared state

What the repository or operator says should exist.

Example:

```text
Locigraph staging should run image abc123.
```

#### Observed state

What discovery sees on the host.

Example:

```text
Container locigraph-staging-api is running image xyz789.
```

#### Effective state

Argus’s reconciled understanding.

Example:

```text
Locigraph staging is running, but the deployed image differs from the declared release.
```

Argus already applies this principle to access state by separating desired and effective values.

Argus extends it across the entire infrastructure.

---

### 5.3 Private by default

Argus retains Argus’s existing security posture:

```text
private first, public never by accident
```

The following remain prohibited unless deliberately enabled through policy:

- public PostgreSQL exposure
- public Docker socket exposure
- public SSH exposure
- public control API exposure
- accidental `.env` or secret exposure
- automatic Cloudflare publication
- mutation without authentication
- mutation without explicit policy approval

The Argus operator surface is never publicly exposed. Tailscale remains its remote-access boundary.

When a managed project is deliberately published, its ingress connector belongs to that trust domain and joins only a dedicated edge network shared with the approved frontend origin. It cannot join database or backend-only networks, mount host paths, use host networking, or access a Docker socket. Work and personal ingress credentials remain separate.

The public Argus portfolio is a separate static deployment. It receives an allowlisted immutable export and has no route back to the operator, host, or workload estate.

The current trust boundaries and blocked targets remain valid.

---

### 5.4 Projects remain sovereign

Argus manages deployments and infrastructure relationships.

It does not own application domain data.

Each project retains ownership of:

- its database
- its migrations
- its business logic
- its application roles
- its backups
- its release rules
- its standalone deployment path

Argus may record and validate project-owned operational contracts without taking over their execution.

The current Nodens workload already demonstrates this distinction: Nodens owns its application backup and restore process, while Argus records and validates the contract.

---

### 5.5 Containers are runtime instances, not projects

A container is temporary.

A project is persistent.

Argus must not confuse the two.

```text
Project: Locigraph
└── Environment: personal-managed/dev
    └── Service: API
        └── Deployment: dep-0042
            └── Container: locigraph-personal-dev-api-1
```

Containers may be replaced without destroying the identity of the service, environment, or project.

---

### 5.6 Composition over platform dependence

Applications may adopt Argus-compatible operational contracts, but they must remain functional without Argus.

A project may expose:

```text
/health/live
/health/ready
/version
/metadata
```

Argus can consume these endpoints, but the application does not require Argus to operate.

Likewise, a project may run:

- inside Nodens
- as an independent deployment
- on another host
- on another domain
- under another identity provider

Argus integration is additive.

---

### 5.7 Containment and compliance evidence

Argus provides both operational containment and evidence that the declared controls are effective.

On one physical host, separate Unix identities and rootless Docker daemons can contain ordinary application, credential, network, and Docker-daemon failures between trust domains. They do not protect one domain from host-root access, a host-kernel compromise, or physical host failure.

Argus may report compliance against its own named controls. It must not claim third-party certification or contractual compliance unless the governing standard and its required evidence are explicitly configured and independently assessed.

---

## 6. Core Entity Model

### 6.1 Project

A persistent software product or operational system.

Examples:

```text
Nodens
Locigraph
Hastur
Argus
Intake OS
```

A project may contain multiple environments.

Suggested fields:

```yaml
id:
name:
description:
repository:
lifecycle:
steward:
standalone_capable:
```

---

### 6.2 Environment

A deployment context belonging to a project. Realm, zone, and stage are independent classifications.

Suggested fields:

```yaml
id:
project_id:
name:
realm:
zone:
stage:
trust_domain_id:
durability:
exposure:
criticality:
host_placement:
```

Example:

```yaml
id: locigraph-personal-dev
project_id: locigraph
name: Personal Development
realm: personal
zone: managed
stage: dev
trust_domain_id: personal-managed
durability: disposable
exposure: private
criticality: low
```

Allowed values are:

```text
realm: unclassified | personal | work
zone: legacy | sandbox | managed
stage: none | dev | staging | production
```

`unclassified` is allowed only with `zone: legacy`. Sandbox and legacy environments use `stage: none`. Managed environments require `realm: personal|work` and `stage: dev|staging|production`.

Environment must be a first-class entity rather than a string attached to deployments.

---

### 6.3 Service

A logical runtime component within an environment.

Examples:

```text
web
api
worker
scheduler
database
reverse-proxy
```

Suggested fields:

```yaml
id:
environment_id:
name:
kind:
health_contract:
runtime_contract:
identity_contract:
```

---

### 6.4 Deployment

A release event for one or more services.

Suggested fields:

```yaml
id:
environment_id:
repository:
commit:
image:
version:
deployed_at:
deployed_by:
status:
rollback_target:
```

A deployment is not the same as a container restart.

A deployment answers:

```text
What version was released?
When was it released?
What artifact was used?
Did it become healthy?
What can it roll back to?
```

---

### 6.5 Runtime Instance

The observed process or container currently realizing a service.

Examples:

```text
Docker container
systemd service
local process
Compose service
```

Suggested fields:

```yaml
id:
service_id:
runtime_type:
runtime_identifier:
host_id:
status:
started_at:
observed_image:
```

---

### 6.6 Infrastructure Resource

A resource used by one or more services.

Initial supported resource types:

```text
host
container
compose-project
image
network
volume
database
port
endpoint
domain
route
tunnel
repository
health-check
backup-target
identity-provider
```

---

### 6.7 Relationship

An explicit connection between entities.

Initial relationship types:

```text
BELONGS_TO
RUNS_IN
RUNS_ON
REALIZES
DEPLOYED_FROM
USES_IMAGE
DEPENDS_ON
CONNECTS_TO
STORES_IN
EXPOSED_AS
RESOLVES_TO
ROUTES_TO
AUTHENTICATES_VIA
MONITORED_BY
BACKED_UP_TO
INHERITS
SUPERSEDES
MEMBER_OF_TRUST_DOMAIN
OBSERVED_BY
EXPORTED_AS
PROMOTED_TO
```

Example:

```text
locigraph-personal-dev-api
    DEPENDS_ON
locigraph-personal-dev-postgres
```

Example:

```text
locigraph.nodens.dev
    ROUTES_TO
locigraph-production-web
```

---

### 6.8 Trust Domain

An enforced runtime boundary containing environments and resources with the same ownership and operating class.

Suggested fields:

```yaml
id:
kind:
realm:
zone:
runtime_identity:
runtime_endpoint:
storage_root:
mutation_agent:
state:
```

Trust-domain constraints are:

```text
kind: management → realm: none, zone: none, no workload environments or runtime socket
kind: legacy     → realm: unclassified, zone: legacy
kind: workload   → realm: personal|work, zone: sandbox|managed
```

The V1 target domains are:

```text
argus-management
legacy-rootful
personal-sandbox
personal-managed
work-sandbox
work-managed
```

`argus-management` contains the private operator, repository adapter, policy engine, and audit writer but no workload runtime. The four workload domains use distinct Unix identities, rootless Docker daemons, sockets, network namespaces, firewall policies, storage roots, credentials, routes, and backup scopes. `legacy-rootful` is a temporary quarantine and cannot accept new managed deployments.

---

### 6.9 Public Snapshot

An immutable, allowlisted artifact generated from private Argus state for the portfolio.

Suggested fields:

```yaml
id:
schema_version:
source_revision:
generated_at:
content_digest:
policy_result:
mirror_validation:
published_at:
```

A public snapshot contains only fields explicitly present in its public schema. It is never a database replica, API proxy, or live view of the operator state.

---

## 7. Environment Model

Argus V1 uses realm, zone, and stage as orthogonal axes.

```text
primary-host
├── argus-management
├── legacy-rootful
├── personal-sandbox
├── personal-managed
│   ├── dev
│   ├── staging
│   └── production
├── work-sandbox
└── work-managed
    ├── dev
    ├── staging
    └── production
```

This provides runtime, configuration, database, network, volume, credential, route, release, and backup separation. It does not provide host-root, kernel, physical-host, or host-failure isolation. That limitation must remain visible in Argus.

### 7.1 Legacy quarantine

Current resources first enter `legacy-rootful` with `realm: unclassified`, `zone: legacy`, and `stage: none`.

Legacy resources remain operable but cannot be promoted, published, or called compliant. New workloads cannot be admitted to the legacy runtime. Exit requires explicit classification, containment checks, a migration plan, and rollback evidence.

### 7.2 Sandbox

Sandbox characteristics:

```text
private
mutable
disposable by default
debugging allowed
local builds permitted
no public routes
no managed credentials
no dependency on managed data stores
stage: none
```

Personal and work sandboxes are separate trust domains. A work sandbox cannot reuse personal secrets, networks, volumes, source mounts, or tunnel credentials.

### 7.3 Managed development

Managed development is reproducible but may remain mutable and disposable. It requires a declared deployment definition, isolated data resources, a known artifact or build input, health checks, and a recovery classification.

### 7.4 Staging

Staging is private or access-protected, production-like, uses separate databases and volumes, deploys a built release artifact, runs smoke tests, and uses disposable test data unless explicitly declared otherwise.

### 7.5 Production

Production uses durable data, immutable release artifacts, controlled deployment, required backup and rollback contracts, strict secret scope, and restricted mutation. Public reachability is optional and must be explicitly approved.

### 7.6 Promotion

The target release flow is:

```text
commit
→ build immutable artifact
→ deploy to managed dev
→ deploy same artifact to staging
→ validate
→ promote same artifact to production
```

Production must not receive a separately rebuilt artifact after staging validation.

### 7.7 Enforcement matrix

| Boundary | Enforcement |
|---|---|
| Personal vs work | Separate Unix identity, rootless Docker daemon, network namespace, host-firewall policy, storage root, credentials, routes, and backups |
| Sandbox vs managed | Separate trust domain and network policy; no shared networks, volumes, mounts, secrets, or data stores |
| Dev vs staging vs production | Separate Compose projects, networks, databases, volumes, secrets, routes, and deployment records |
| Legacy vs classified | Quarantine, deny new admission, and one-workload-at-a-time migration |

Trust-domain networking is default-deny for host, LAN, Tailscale, legacy-runtime, and cross-domain destinations. Each domain receives an explicit egress allowlist enforced through its network namespace and host-firewall rules keyed by interface, Unix identity, or cgroup. Host-published ports are prohibited except for approved ingress targets.

Typed relationships describe topology but do not grant connectivity. Docker sockets, credentials, bind mounts, volumes, and Docker networks are never shared across ownership or sandbox/managed boundaries. The only permitted cross-domain dependency is an explicitly enumerated service protocol through an authenticated gateway using least-privilege credentials.

---

## 8. Discovery Model

Argus currently discovers unregistered Docker Compose project names by comparing running Compose labels against registered workloads.

Argus V1 expands discovery into normalized observations.

Discovery remains read-only.

Initial discovery sources:

```text
Docker containers
Docker Compose labels
Docker images
Docker networks
Docker volumes
published ports
bind mounts
health status
running processes
systemd services
Caddy configuration
Tailscale Serve state
cloudflared state
Git repositories
known workload manifests
host metrics
```

Discovery outputs observations, not canonical truth.

Example:

```json
{
  "source": "docker",
  "type": "container",
  "observedId": "a81f...",
  "name": "locigraph-api-1",
  "labels": {
    "com.docker.compose.project": "locigraph"
  },
  "image": "locigraph-api:latest",
  "networks": ["locigraph_default"],
  "ports": ["0.0.0.0:8000->8000"]
}
```

A reconciliation layer then links the observation to known entities.

---

## 9. Registry Model

The existing JSON registries remain migration inputs.

They should not be deleted at the beginning of Argus V1.

Existing records are imported into the new entity model:

```text
workloads.json
privacy.json
access.json
policy.json
routes.json
exposure.json
monitoring.json
workloads/*/manifest.json
```

The current workload records already contain valuable information about paths, ports, volumes, runtime types, health endpoints, migration risks, and application ownership.

The migration must preserve that information.

---

## 10. Policy and Reconciliation

Argus retains the preview-and-apply model.

Every mutation should follow:

```text
request
→ preview
→ policy decision
→ confirmation when required
→ apply
→ observe result
→ reconcile effective state
→ audit
```

Mutation prerequisites are part of the transaction. Argus denies the operation when policy, canonical state, agent authorization, evidence freshness, observation completeness, reconciliation, or durable audit persistence is unavailable, malformed, stale, mismatched, or timed out.

Evidence freshness is operation-specific and recorded in policy. A separately authorized break-glass command may bypass availability failures only for documented recovery operations; it cannot weaken non-waivable trust-domain or public-exposure rules. It must persist durable intent before execution and append the outcome afterward. Reconciliation closes abandoned or indeterminate intents after crashes.

Policies may evaluate:

- privacy classification
- realm, zone, stage, and trust domain
- resource criticality
- public exposure
- operation type
- backup readiness
- restore readiness
- deployment drift
- route safety
- shared database risk
- shared volume risk
- wildcard host bindings
- mutable image tags
- missing health contracts
- unclassified resources
- cross-domain networks, volumes, mounts, secrets, routes, and dependencies
- raw Docker socket access
- public snapshot disclosure rules

Example warning:

```text
Locigraph staging and production reference the same PostgreSQL volume.
```

Example block:

```text
Production deployment denied because no tested restore contract exists.
```

V1 fail-closed rules are:

- unclassified resources stay in `legacy-rootful`
- sandboxes cannot receive public routes
- data stores cannot bind wildcard host interfaces
- no workload may mount the Docker socket or operator SSH material
- the central control plane holds zero raw trust-domain Docker sockets
- Docker sockets, credentials, bind mounts, volumes, and Docker networks never cross ownership or sandbox/managed boundaries
- cross-domain service calls require an explicit protocol, authenticated gateway, least-privilege identity, and typed relationship
- host, LAN, Tailscale, legacy, and cross-domain network access is denied unless explicitly allowlisted
- public export includes only schema-allowlisted fields
- publication requires a successful mirror validation of the same artifact digest
- an ingress connector may reach only its approved edge origin inside the same trust domain

### 10.1 Domain operation protocol

The operator never sends shell commands, Compose arguments, or raw Docker requests to a workload domain.

An approved request contains:

```text
request ID and correlation ID
actor and session identity
trust-domain and target IDs
typed operation and parameters
expected declared and observed revisions
policy version
preview and approval digests
single-use nonce and expiry
idempotency key
```

The central Argus process constructs and transports requests but holds no capability-signing key. The operator's user-held authenticator signs a challenge bound to the domain, request digest, preview digest, and expiry. A domain-local issuer verifies that assertion using allowlisted operator public credentials provisioned by the host bootstrap, then issues a short-lived capability valid for one approved request in that domain.

The domain agent authenticates the capability, rejects replay, re-evaluates local policy, compares state revisions and digests, executes only a fixed typed operation, and returns a bounded redacted result. A credential or issuer from one domain cannot operate another. Verification-key rotation uses an audited overlap window; revocation reaches every domain before the old credential is rejected.

---

## 11. Monitoring

The existing host metrics collector remains the host-observability component.

Argus V1 adds entity correlation.

Instead of only reporting:

```text
container locigraph-api uses 12% CPU
```

Argus should report:

```text
Project: Locigraph
Environment: personal-managed/dev
Service: API
Runtime: locigraph-api-1
CPU: 12%
Status: healthy
```

Monitoring initially covers:

```text
host health
container state
service health
resource usage
restart count
dependency availability
route availability
deployment drift
storage saturation
backup freshness
```

Monitoring should use topology to calculate impact.

Example:

```text
PostgreSQL unavailable

Affected:
- Locigraph API
- Locigraph worker
```

---

## 12. Logs and Events

Existing sanitized log-preview behavior remains.

Argus V1 attaches logs and events to entities.

Normalized event metadata should include:

```yaml
event_id:
correlation_id:
timestamp:
sequence:
actor_id:
session_id:
trust_domain_id:
project_id:
environment_id:
service_id:
deployment_id:
runtime_instance_id:
source:
severity:
action:
policy_version:
declared_revision:
observed_revision:
preview_digest:
approval_digest:
before_digest:
after_digest:
outcome:
error_code:
message:
previous_event_hash:
event_hash:
```

Audit events remain separate from application logs but may be viewed in the same timeline.

Mutation intent is durably appended before execution and its result or denial is appended afterward. After a crash, reconciliation closes an unmatched intent as abandoned or indeterminate before any retry. Audit records form a hash chain. Checkpoints and signed evidence bundles are replicated and anchored in off-host append-only storage under an explicit retention policy.

Secret-redaction rules must be retained. Host-root can forge future events but cannot silently rewrite history that was already anchored off-host; Argus reports that trust ceiling with every evidence bundle.

---

## 13. Authentication

The current local bearer token remains a temporary compatibility mechanism for legacy operations while the operator surface stays private and Tailscale-bound. It cannot authorize trust-domain operations, portfolio publication, break-glass recovery, or compliance-grade approvals.

The public portfolio has no operator authentication because it contains no private state or mutation capability. It is a separate static artifact and deployment, not an unauthenticated mode of the operator application.

Identity-backed operator authentication is required before domain agents accept mutations. Argus V1 uses Better Auth for allowlisted operator identity, session management, sensitive-operation re-authentication, rotation, revocation, and actor-bound approval.

The model is:

```text
Better Auth
├── operator identity
├── session management
├── Google OAuth
├── authorization hooks
├── sensitive-operation re-authentication
└── domain-scoped capability issuance
```

Domain capabilities are short-lived, single-request, revocable, and bound to the approved request digest. No long-lived domain mutation credential is stored in the central operator process. The legacy bearer token is rotated during migration and revoked when legacy mutation compatibility ends.

Application authentication remains project-owned.

Nodens-hosted applications may share identity through a hosted Better Auth configuration, while standalone deployments may run their own Better Auth instance.

Argus records these relationships but does not become the authentication provider for every project.

---

## 14. Contracts and Inheritance

Argus V1 introduces versioned operational contracts.

Contracts describe shared expectations without making applications dependent on Argus.

Initial contract types:

```text
runtime contract
health contract
deployment contract
logging contract
backup contract
identity contract
environment contract
```

Example:

```yaml
id: nodens-web-service-v1
version: 1.0.0

health:
  liveness: /health/live
  readiness: /health/ready

metadata:
  version: /version

runtime:
  graceful_shutdown: true

observability:
  structured_logs: true

deployment:
  immutable_image_required_for_production: true
```

An environment may inherit a contract:

```text
Locigraph Staging
    INHERITS
Nodens Web Service Contract v1
```

Standalone deployments may inherit another profile:

```text
Locigraph Standalone
    INHERITS
Standalone Web Service Contract v1
```

Inheritance is represented explicitly and remains inspectable.

---

## 15. User Interface and Deployment Surfaces

Argus has two user-facing views implemented as three deployments.

### Private operator

The current generated dashboard becomes the private operator view. It stays Tailscale-bound, reads live Argus state, and retains authenticated preview, apply, monitoring, backup, restart, access, and audit operations.

The operator includes:

### Estate

All projects, environments, and infrastructure resources.

### Project

Project environments, services, deployments, data resources, and routes.

### Environment

Declared, observed, and effective state.

### Topology

Entity and relationship graph.

### Operations

Existing workload actions, monitoring, backup, restart, access, and audit surfaces.

### Drift

Differences between declared and observed state.

### Rebuildability

What must survive or be recreated if the host is wiped.

### Public portfolio

The public portfolio is a separate static build. It demonstrates Argus concepts and selected project topology using synthetic or explicitly allowlisted snapshot data.

It contains no control API, mutation code, live operator client, host credentials, internal hostnames, IP addresses, ports, paths, logs, audit actors, security findings, backup locations, private project names, or live resource identifiers.

Allowed fields also enforce value formats, lengths, denied patterns, and synthetic-by-default content. The static artifact has an explicit file allowlist, forbids source maps and debug metadata, scans final bytes for internal identifiers and secret markers, records signed provenance, and is rejected if any unrecognized asset appears.

### No-route portfolio mirror

The mirror deploys the exact immutable portfolio artifact before publication. It has no public route and runs disclosure, schema, link, asset, and security checks.

Promotion changes only which validated artifact digest the public origin serves. It does not rebuild the artifact. The public origin verifies the digest and provenance again before serving it.

### Surface isolation

```text
private Argus state
    → allowlisted exporter
    → immutable public snapshot and static build
    → no-route mirror validation
    → promote same digest
    → public static origin
```

The public origin requires one ingress route to serve the site. It has zero routes back to Argus, the primary host, or workload trust domains. V1 hosts it independently so the portfolio remains available when the home server is offline and creates no public ingress dependency on the operator host.

---

## 16. Rebuildability

The current server has historically functioned as a private crashsite.

Argus should not attempt to eliminate that flexibility.

Instead, it should preserve sandbox flexibility while making every sandbox reconstructable and keeping it outside managed deployment trust domains.

Every managed environment should eventually answer:

```text
Is source available?
Is the deployment definition available?
Are secrets stored outside the host?
Which volumes are disposable?
Which data must survive?
Is a backup contract defined?
Has restore been tested?
Is the release command known?
Is rollback defined?
Are routes reproducible?
```

This becomes a first-class Argus view.

---

## 17. Migration Strategy

### Phase A: Rename and preserve

- Rename Argus to Argus.
- Preserve the current CLI, dashboard, API, monitoring, registries, scripts, and systemd units.
- Provide temporary compatibility command names.
- Avoid changing runtime behavior.

Example:

```text
argus-health → argus-health
argus-workloads → argus-projects
argus-events → argus-events
```

Old command names may remain as compatibility aliases during V1.

---

### Phase B: Introduce the entity store

Add a new model containing:

```text
projects
environments
services
deployments
resources
relationships
observations
contracts
trust_domains
public_snapshots
```

Argus V1 uses SQLite as its canonical entity store through a storage-neutral repository interface. SQLite provides transactions, constraints, indexed relationship queries, and atomic declared/observed/effective reconciliation while remaining single-host and available through Python’s standard library.

The repository adapter remains the only writer during migration. It initially writes the legacy JSON registries through a crash-atomic write-ahead protocol. No API, CLI, importer, or compatibility generator may write either store independently.

For every mutation, the adapter:

1. appends a `PREPARED` journal record containing transaction ID, expected revision, typed operation, and payload checksum;
2. flushes and syncs the journal and parent directory;
3. writes JSON state to a temporary file with the transaction ID and new revision, flushes it, atomically renames it, and syncs the parent directory;
4. appends and syncs a `COMMITTED` marker.

Recovery deterministically reconciles prepared, applied, and committed transaction IDs. Replay is idempotent. Crash-injection tests cover every write, flush, rename, marker, snapshot, replay, parity, cutover, and rollback boundary.

Cutover follows one transaction protocol:

1. snapshot and back up the legacy registries;
2. import the snapshot into a shadow SQLite store;
3. replay the durable mutation journal;
4. verify record counts, relationships, policy decisions, and semantic parity;
5. pause mutations, replay the final journal boundary, and verify parity again;
6. atomically switch repository reads and writes to SQLite;
7. generate JSON as read-only compatibility output;
8. retain the snapshot and journal until the rollback window closes.

During the rollback window, the repository adapter rejects mutations that cannot be represented in both the legacy and SQLite schemas. Rollback pauses mutations, switches the adapter to the retained checkpoint, replays only versioned reverse-compatible journal operations, and verifies parity before reopening writes. Forward-cutover and rollback tests must prove semantic parity for every permitted operation.

After the rollback window closes, legacy JSON rollback is disabled and entity-model-only mutations may begin. SQLite becomes canonical only after the atomic cutover succeeds.

---

### Phase C: Import existing workloads

Map each current workload into:

```text
Project
└── Environment
    ├── realm: unclassified
    ├── zone: legacy
    ├── stage: none
    └── trust domain: legacy-rootful
    └── Service
        └── Runtime observation
```

Example:

```text
Locigraph
└── legacy-unclassified
    ├── web
    ├── api
    ├── postgres
    └── redis
```

No sandbox, development, staging, or production classification should be generated until ownership and operational evidence support it.

---

### Phase D: Expand discovery

Replace Compose-name-only discovery with normalized observations.

Discover:

- containers
- services
- images
- networks
- volumes
- routes
- endpoints
- health state
- repositories
- host placement

Do not mutate infrastructure during discovery.

---

### Phase E: Reconciliation

Create mappings between:

```text
declared entities
observed resources
effective state
```

Add drift reporting.

Examples:

```text
unknown container
missing declared service
wrong image
unexpected public port
missing volume
shared environment database
route mismatch
unclassified resource
cross-domain mount
cross-domain network
public snapshot disclosure violation
```

---

### Phase F: Generate the existing dashboard from Argus state

The current workload dashboard should be generated from the Argus entity model.

This proves that the new model contains at least as much operational information as the old registries.

The old registries may then become generated compatibility outputs or be retired.

---

### Phase G: Prove and introduce trust-domain isolation

Before provisioning all cells, create one disposable pilot and verify:

- unique subordinate UID/GID ranges
- cgroup delegation and user lingering
- rootless storage-driver and filesystem compatibility
- network namespace and firewall behavior
- socket ownership and domain-agent authentication
- approved ingress and egress strategy
- backup access without cross-domain permissions
- daemon restart and host reboot recovery
- sustained CPU, memory, disk, and network overhead
- the complete pairwise reachability and operation-denial matrix

Privileged host setup is performed out of band by a root-owned, versioned, idempotent bootstrap bundle run by the host administrator. The bundle accepts configuration files, not arbitrary remote commands; backs up every host config before editing; validates subordinate IDs, namespaces, firewall, cgroups, systemd, and rollback; and emits a signed redacted result that Argus imports into the audit ledger. It has no network service, workload runtime socket, or dashboard execution path.

Only after the pilot passes may Argus provision the four target runtime cells:

```text
personal-sandbox
personal-managed
work-sandbox
work-managed
```

Each trust domain uses a separate Unix identity, rootless Docker daemon, network namespace, host-firewall policy, and egress allowlist. The central Argus process consumes normalized domain-local observations and invokes separately authenticated, narrowly scoped operation agents. It mounts zero trust-domain Docker sockets.

Within managed domains, each stage must use isolated:

- Compose project names
- networks
- database instances or databases
- volumes
- environment variables
- routes
- deployment records

Do this one project at a time.

---

### Phase H: Classify and migrate workloads

Classify one workload, declare its target domain and stage, and execute copy, validate, cut over, and rollback as a recorded operation.

Stateful migration requires:

1. health and restore prerequisites;
2. source quiescence and an exclusive migration fence;
3. data snapshot and checksum inventory;
4. UID/GID ownership translation for the target rootless identity;
5. copy into a new physical target volume with an explicit logical-to-physical mapping;
6. checksum, schema, permission, and application-level data validation;
7. target start, health checks, and bounded observation;
8. source fencing throughout the target write window;
9. rollback that stops and fences the target before reopening the source;
10. proof that source and target were never concurrent writers.

Preserving a logical Compose project or volume ID does not imply reusing the same physical Docker object across daemons.

---

### Phase I: Deployment history and promotion

Add release records and promotion workflows.

Track:

```text
commit
image digest
environment
deployment time
health result
rollback target
promotion source
```

Promotion should reuse the same built artifact.

---

### Phase J: Public portfolio pipeline

Add the allowlisted snapshot exporter, static portfolio build, private no-route mirror, disclosure checks, and explicit promotion of the same validated artifact digest to an independently hosted public origin.

The public pipeline must not create a live dependency or network path from the public site to the operator control plane.

---

## 18. Argus V1 Scope

Argus V1 includes:

- project entities
- environment entities
- service entities
- resource entities
- relationship model
- trust-domain model
- realm, zone, and stage classification
- declared state
- observed state
- effective state
- existing workload import
- expanded Docker discovery
- topology generation
- drift detection
- existing monitoring integration
- existing policy integration
- existing operations compatibility
- rebuildability status
- one-host environment support
- legacy quarantine
- domain-scoped observation and operation contracts
- isolated management trust domain and identity-backed mutation approval
- single-writer journaled migration from JSON to SQLite
- tamper-evident audit chaining with off-host anchoring
- allowlisted public snapshot format
- private operator, no-route mirror, and public portfolio surfaces

---

## 19. Argus V1 Non-Goals

Argus V1 does not include:

- Kubernetes
- multi-region infrastructure
- automatic public deployment
- automatic DNS mutation
- automatic Cloudflare publication
- automatic database migration
- arbitrary remote shell execution
- public multi-user hosting
- replacing application databases
- forcing shared application authentication
- moving production to another host
- full distributed tracing
- enterprise RBAC
- automatic dependency inference from network traffic
- mandatory staging for every project
- mandatory production deployment
- claiming third-party certification without an explicit standard and assessment
- protecting one trust domain from host-root or host-kernel compromise
- exposing live operator state through the public portfolio

---

## 20. Compatibility Requirements

During migration:

- current workloads must remain operable
- existing Tailscale access must remain functional
- existing control API operations must remain available
- current monitoring must continue working
- current backup and restore contracts must not be weakened
- current access policy must not be bypassed
- current audit events must remain readable
- existing workload manifests must remain valid until imported
- no service may become public as a side effect
- no stateful workload may be migrated without a rollback path
- source and target instances may never write state concurrently
- current resources must remain quarantined until explicitly classified
- no classification change may silently create a route or cross-domain relationship
- portfolio publication must use the artifact validated by the no-route mirror
- legacy bearer authentication may not authorize trust-domain operations
- audit intent and outcome records must survive every accepted mutation

---

## 21. Initial Data Mapping

The current Argus workload maps into Argus as follows:

| Argus field | Argus entity or field |
|---|---|
| workload ID | Project ID |
| lifecycle | Project lifecycle |
| runtime type | Runtime contract |
| Compose project | Runtime resource |
| service | Service |
| paths | Repository/source resource |
| local URL | Endpoint |
| internal port | Port resource |
| observed bindings | Runtime observations |
| health | Health contract |
| privacy | Policy binding |
| desired access | Declared route state |
| effective access | Effective route state |
| Cloudflare route | Route and tunnel relationship |
| backup | Backup contract |
| migration | Rebuildability and migration state |
| actions | Operation policy |
| audit event | Entity event |
| no existing field | Environment realm, zone, and stage |
| no existing field | Trust domain membership |
| no existing field | Public snapshot and promotion record |

---

## 22. Suggested Repository Structure

```text
argus/
├── config/
│   ├── legacy/
│   ├── policies/
│   └── contracts/
│
├── model/
│   ├── schema/
│   ├── migrations/
│   ├── importers/
│   └── trust-domains/
│
├── discovery/
│   ├── docker/
│   ├── compose/
│   ├── host/
│   ├── caddy/
│   ├── tailscale/
│   └── cloudflare/
│
├── reconciliation/
│   ├── matcher/
│   ├── drift/
│   └── effective-state/
│
├── control-plane/
│   ├── api/
│   ├── dashboard/
│   ├── topology/
│   ├── monitoring/
│   └── public-export/
│
├── operations/
│   ├── logs/
│   ├── restart/
│   ├── backup/
│   ├── deploy/
│   └── rollback/
│
├── runtime/
│   ├── observations/
│   ├── metrics/
│   ├── events/
│   ├── audit/
│   └── domain-agents/
│
├── portfolio/
│   ├── schema/
│   ├── mirror/
│   └── public/
│
├── workloads/
├── scripts/
├── systemd/
└── docs/
```

This structure may be introduced incrementally.

---

## 23. Acceptance Criteria

Argus V1 is complete when:

### Model

- Every registered Argus workload is represented as a project.
- Every current project has at least one legacy environment or an explicitly classified environment.
- Existing deployments initially map to `legacy-unclassified` unless classification evidence already exists.
- Realm, zone, stage, and trust-domain membership are first-class state.
- Invalid combinations fail closed.
- The repository adapter is the only writer during migration and switches atomically from legacy JSON to SQLite after journal replay and semantic parity checks.
- Services and runtime resources are separate entities.
- Explicit relationships exist between projects, environments, services, containers, networks, volumes, and endpoints.

### Discovery

- Argus discovers running Docker containers.
- Argus discovers Compose projects.
- Argus discovers Docker networks and volumes.
- Argus records observations without mutating infrastructure.
- Unknown resources appear as unregistered observations.
- Discovery identifies resources that violate target reachability, mount, or cross-domain policy without mutating them.

### State

- Declared state is distinct from observed state.
- Effective state is calculated.
- Drift is visible.
- Existing desired/effective access semantics remain intact.
- Unclassified and cross-domain drift is visible and policy-blocking.

### Operations

- Existing health, logs, restart, backup, monitoring, and access operations remain functional.
- Existing preview, confirmation, and audit behavior remains intact.
- No new public exposure is introduced.
- The central operator holds zero raw trust-domain Docker sockets.
- Mutations fail closed on policy, store, authorization, freshness, observation, reconciliation, or audit errors.
- Break-glass recovery is separately authorized, pre-audited, and cannot bypass non-waivable isolation or exposure rules.

### Interface

- The current workload operations dashboard can be generated from Argus state.
- A project view shows environments and services.
- An environment view shows declared, observed, and effective state.
- A topology view can display at least one complete project chain.
- The private operator and public portfolio are separate builds and deployments.
- A no-route mirror validates the exact public artifact before promotion.
- The public deployment has no live Argus API or network path back to the estate.

Example:

```text
Nodens
→ personal-managed/dev
→ web service
→ deployment
→ container
→ host
→ endpoint
→ Tailscale route
```

### Rebuildability

- Every project has an initial rebuildability assessment.
- Stateful resources are classified as disposable or durable.
- Backup ownership is explicit.
- Restore status is explicit.
- Missing recovery contracts are visible.

### Containment and compliance evidence

- Four target trust domains are modeled independently from managed stages.
- The management plane is a separate trust domain with no workload runtime, raw Docker socket, arbitrary-shell transport, or long-lived domain mutation credential.
- Cross-domain sockets, credentials, bind mounts, volumes, and Docker networks are non-waivable prohibitions across ownership or sandbox/managed boundaries.
- Cross-domain service dependencies use only explicitly approved authenticated gateways and least-privilege identities.
- Host, LAN, Tailscale, legacy-runtime, and cross-domain network access is denied unless explicitly allowlisted.
- Sandboxes cannot receive public routes.
- Wildcard bindings and prohibited mounts are visible as blocking findings.
- Evidence is timestamped, reproducible, redacted, and explicit about the shared-host trust ceiling.
- Argus does not claim certification without a configured standard and independent assessment.
- A server-side isolation matrix attempts socket, storage-root, host, LAN, Tailscale, legacy-runtime, cross-domain network, volume, credential, route, and scoped-agent access from every trust domain to every other domain and requires denial.
- Isolation checks pass after daemon restart and host reboot before a runtime cell is accepted.
- One disposable rootless pilot proves subordinate IDs, cgroup delegation, lingering, storage, networking, socket permissions, ingress/egress, backups, recovery, and resource overhead before four-cell rollout.
- Domain agents accept only typed, digest-bound, single-use operations and reject wrong-domain credentials, replay, stale state, and arbitrary arguments.
- Audit intent, denial, error, and outcome records are hash-chained and anchored off-host.

### Public portfolio

- Public data is generated from a schema allowlist rather than a denylist-only scrub.
- The static build contains no mutation code, operator credentials, live API client, or private topology identifiers.
- Publication records source revision, content digest, mirror result, publisher, and time.
- Negative fixtures cover nested denied fields, secret markers, internal addresses, source maps, embedded metadata, live API references, mutation code, and unexpected schema fields.
- Promotion fails on any denied fixture, artifact digest change after mirror validation, or detected network path from the public origin back to the operator estate.

---

## 24. First Implementation Milestone

The first milestone establishes safe ground truth before a new model or runtime is trusted.

### Argus M0: Legacy Quarantine and Containment Baseline

Tracked by [#131](https://github.com/pxm-0/argus/issues/131).

Deliver:

1. A complete read-only inventory of listeners, mounts, networks, volumes, Compose identities, routes, and firewall enforcement.
2. `legacy-unclassified` representation for current resources.
3. Remediation plans for every resource whose reachability violates target containment policy.
4. Removal or replacement plans for prohibited host-capability and operator-identity mounts.
5. A deny-new-admission rule for the rootful legacy runtime.
6. Health, rollback, and secret-safe evidence for each containment change.
7. No environment promotion, public route, or stateful migration.

M0 succeeds when Argus can answer:

```text
What is running on the legacy runtime?
Which resources are reachable, shared, sensitive, or unclassified?
Which findings block classification or migration?
Can every containment change be verified and rolled back safely?
```

The entity model follows in [#132](https://github.com/pxm-0/argus/issues/132), runtime cells in [#133](https://github.com/pxm-0/argus/issues/133), the portfolio pipeline in [#134](https://github.com/pxm-0/argus/issues/134), and workload migration in [#135](https://github.com/pxm-0/argus/issues/135).

---

## 25. Long-Term Direction

Argus may eventually become:

- the infrastructure registry for Nodens
- the deployment control plane for personal projects
- the containment and evidence control plane for work projects
- the topology engine for hosted and standalone services
- the operator interface for sandbox, development, staging, and production
- the record of deployment history and promotion
- the validator of application runtime contracts
- the impact-analysis engine for infrastructure failures
- the map through which the entire digital estate is understood

However, Argus V1 remains grounded in the present host.

It begins by making the current container workspace coherent, inspectable, and reconstructable.

Its public portfolio demonstrates that capability through a deliberately separate, static, sanitized artifact rather than exposing the operational estate.

---

## 26. Final Principle

Argus answered:

> What workloads are running on my server, and how can I operate them safely?

Argus answers:

> What systems exist, how are they connected, what state should they be in, and what state are they actually in?

The transition preserves the operator discipline already built into Argus.

The graph does not replace the control plane.

It gives the control plane a world model.
