# Argus M5 Operations Control Plane

## Problem

Argus provides estate topology, workload evidence, health visibility, and
partially implemented controls. The dashboard renders restart, backup, privacy,
and access actions, but workloads outside `legacy-rootful` correctly remain
disabled because no domain-local execution or identity-backed capability flow
exists.

The current administrator model relies on a reusable bearer token stored in
browser `sessionStorage`. Long-running operations execute synchronously, have no
durable progress record, and cannot safely survive browser disconnects or API
restarts.

Argus needs a functional workload-management UI without weakening trust-domain
containment. Protected-public access must remain a separate, curated, read-only
projection.

## Users

- Primary: the Argus owner/operator.
- Secondary: authenticated protected-public viewers of explicitly allowlisted
  portfolio entries.
- Automated participants: the management-plane API, operation worker, policy
  engine, capability issuer, and domain-local agents.

## Product decisions

- Deliver two independently functional phases.
- Phase 1 supports routine operations and private access management.
- Phase 2 adds deployment, restore, rollback, migration, and protected-public
  viewing.
- Management requires verified Tailscale identity plus a short-lived Argus
  operator session.
- Every workload domain executes mutations through a domain-local
  typed-operation agent.
- The management plane holds no workload Docker socket and no domain
  capability-signing key.
- Mutations use a durable SQLite operation ledger with one active mutation per
  workload.
- Public mode is an explicit portfolio allowlist, not a redacted copy of the
  operator topology.
- Public routes contain no mutation code, live topology, private identifiers,
  or management API path.

## Phase 1: private routine operations

### Operator authentication

Replace browser-held bearer-token administration with:

1. A private operator route served through Tailscale Serve.
2. Verified Tailscale identity passed through an allowlisted trusted-proxy
   boundary.
3. Explicit Argus operator authentication.
4. A short-lived server-side session.
5. An `HttpOnly`, `Secure`, `SameSite=Strict` cookie containing only an opaque
   session identifier.
6. CSRF protection on every state-changing request.
7. Session expiry, logout, revocation, and step-up reauthentication.

The API must reject management requests unless both the verified tailnet
identity and Argus session are valid. UI visibility is never authorization.

The existing control token may be used only as a bootstrap credential for
creating the first operator session. It must not remain in `sessionStorage`,
HTML, URLs, logs, or operation records.

### Phase 1 operations

For every policy-eligible workload:

- Refresh health and runtime evidence.
- Preview sanitized logs.
- Preview and apply restart.
- Preview and apply backup.
- Preview and apply `none`, `local`, and `tailnet` access states.
- Show why an operation is unavailable.
- Show expected blast radius, health checks, and rollback behavior before
  approval.
- Show durable progress and terminal outcome.
- Resume operation status after browser refresh.

Cloudflare states remain unavailable in Phase 1.

### Domain-local execution

Add one policy-enforcing agent per active workload trust domain. The central API
sends only typed requests:

```text
health.refresh
logs.preview
workload.restart
backup.create
access.apply
```

Agents must not accept arbitrary shell, arbitrary Compose arguments, raw Docker
API requests, or untyped command strings.

Each apply request requires:

- operator identity;
- workload and trust-domain IDs;
- operation type and exact approved parameters;
- canonical-state revision and preview digest;
- policy version;
- expiry and nonce;
- idempotency key;
- short-lived domain-scoped capability.

The agent independently verifies policy, target domain, revision, digest,
expiry, nonce, and capability scope before execution. Replayed, stale,
mismatched, or cross-domain requests fail closed.

A compatibility agent may execute approved legacy operations, but it must use
the same typed request and capability contract.

### Durable operation model

Add a SQLite operation ledger containing at minimum:

```text
operation_id
idempotency_key
workload_id
trust_domain
operation_type
requested_by
preview_digest
expected_revision
policy_version
state
created_at
approved_at
started_at
finished_at
error_class
redacted_summary
rollback_operation_id
```

Allowed states:

```text
planned
awaiting-approval
queued
running
succeeded
failed
rollback-running
rolled-back
denied
expired
indeterminate
```

Rules:

- Apply returns `202 Accepted` with an operation ID.
- Only one mutating operation may hold a workload lock.
- The same idempotency key returns the existing operation.
- Conflicting operations return `409 Conflict`.
- API or browser restarts do not erase operation state.
- An operation with an unknown post-crash outcome becomes `indeterminate`; it
  is never silently retried.
- Audit intent persists before dispatch.
- Audit outcome persists before reporting success.

### Phase 1 API

Add or normalize:

```text
POST /api/session/exchange
POST /api/session/logout
GET  /api/session

POST /api/workloads/<id>/operations/preview
POST /api/workloads/<id>/operations
GET  /api/operations/<operation-id>
GET  /api/workloads/<id>/operations
POST /api/operations/<operation-id>/approve
POST /api/operations/<operation-id>/cancel
```

Existing action-specific endpoints may remain temporarily as compatibility
wrappers, but must use the same operation ledger and authorization path.

### Phase 1 UI

The private workload inspector shows:

- current health and evidence freshness;
- declared, observed, and effective access;
- trust domain and agent availability;
- eligible operations and disabled-operation reasons;
- preview digest and canonical revision;
- expected availability impact and rollback path;
- typed confirmation;
- live durable operation progress;
- redacted audit outcome.

Controls must remain usable by keyboard and screen reader. Risk, drift, and
operation state cannot rely on color alone.

### Phase 1 acceptance criteria

- [ ] Operator management requires verified Tailscale identity and a valid
  Argus session.
- [ ] No reusable control credential is stored in browser storage.
- [ ] CSRF, expiry, revocation, logout, and step-up tests pass.
- [ ] Every non-legacy mutation executes through its domain-local agent.
- [ ] The management plane mounts no workload Docker socket.
- [ ] Every mutation is previewed, revision-bound, policy-bound, confirmed,
  idempotent, and audited.
- [ ] One workload cannot run two conflicting mutations concurrently.
- [ ] Browser and API restarts do not lose operation progress.
- [ ] Wrong-domain, stale, replayed, expired, or mismatched capabilities are
  denied.
- [ ] Health, logs, restart, backup, and `none/local/tailnet` access controls
  work for eligible workloads.
- [ ] Ineligible operations explain the exact blocking policy.
- [ ] Full smoke passes on `oreochiserver` with no new public listener or route.

## Phase 2: full lifecycle and protected-public view

### Additional operation types

Add typed preview, apply, and rollback flows for:

```text
workload.deploy
backup.restore
workload.stop
workload.start
migration.preflight
migration.cutover
migration.rollback
access.cloudflare-protected.plan
access.cloudflare-protected.apply
```

Each operation requires an explicit manifest capability and workload-specific
rollback contract.

Restore, deployment, and migration previews show:

- exact workload and environment;
- source and target revision;
- backup prerequisite and artifact identity;
- storage and mount impact;
- route impact;
- expected downtime;
- health gates;
- rollback steps;
- whether rollback restores data or only runtime state.

Restore and migration require step-up reauthentication and exact typed
confirmation. Operations without a verified backup and restore contract remain
disabled.

### Protected-public view

Generate a separate immutable portfolio artifact from entries with:

```json
{
  "publicViewAllowed": true,
  "displayName": "Approved display name",
  "description": "Approved description",
  "coarseHealth": true,
  "publicDemoUrl": ""
}
```

The artifact may expose only:

- approved display name and description;
- coarse state: `available`, `degraded`, or `unavailable`;
- optional approved public demo URL;
- artifact generation timestamp.

It must not expose:

- internal workload IDs;
- hostnames, private URLs, or ports;
- trust domains or topology;
- desired or effective private access;
- backup paths;
- audit or operation history;
- raw error messages;
- runtime types, container names, mounts, or volumes;
- management links, API paths, session endpoints, or mutation JavaScript.

The protected-public route may use Cloudflare Access only after hostname
validation, authentication verification, explicit provider enablement, preview,
typed confirmation, post-activation reachability tests, proof that operator
endpoints are absent, and automatic rollback when validation fails.

Tailscale Funnel, unauthenticated public control routes, router-port changes,
and public API exposure remain forbidden.

### Phase 2 acceptance criteria

- [ ] Deploy, stop/start, restore, migration, and rollback use the durable
  operation contract.
- [ ] Restore and migration remain disabled without verified backup and rollback
  evidence.
- [ ] Failed cutovers stop safely and expose a clear rollback operation.
- [ ] Protected-public output is generated only from explicit allowlisted
  fields.
- [ ] Public artifact tests prove forbidden fields and mutation code are absent.
- [ ] Public requests cannot reach session, operation, topology, or management
  endpoints.
- [ ] Operator access still requires tailnet identity plus Argus session.
- [ ] Cloudflare-protected activation is policy-gated and independently
  reversible.
- [ ] No Funnel, DNS, router, database, cache, Docker socket, or control API
  exposure is introduced.
- [ ] Full production smoke and negative-authorization suites pass on
  `oreochiserver`.

## Failure and degraded-mode behavior

- Missing canonical state: deny mutations and retain the last verified
  read-only state.
- Stale observation: deny mutation preview until evidence refresh succeeds.
- Agent unavailable: block the operation or mark it `indeterminate`; never
  reroute through the management plane.
- Audit database unavailable: deny all applies.
- Policy mismatch: require a new preview.
- Session expiry during approval: require reauthentication and do not dispatch.
- Browser disconnect: continue the operation and retain queryable state.
- Worker restart: resume queued operations; mark unknown running operations
  `indeterminate`.
- Health failure after mutation: execute only the operation's approved rollback.
- Rollback failure: stop automation, mark the operation `indeterminate`, and
  surface operator recovery evidence.
- Public artifact failure: retain the last verified artifact or serve none;
  never fall back to the operator UI.

## Explicitly out of scope

- Arbitrary shell or Compose arguments.
- Raw Docker API proxying.
- Central mounting of workload-domain Docker sockets.
- Public operator UI or control API.
- Unauthenticated public workload inventory.
- Tailscale Funnel.
- Router-port changes.
- Direct public PostgreSQL or Redis exposure.
- Automatic migration without approved M4 evidence.
- Generic multi-user roles beyond the initial operator identity.
- Mobile-native management applications.

## Required test layers

- Unit tests for policy, sessions, CSRF, capabilities, replay, revisions,
  redaction, and operation transitions.
- API tests for authentication, authorization, idempotency, conflicts, expiry,
  and recovery.
- Agent contract tests for wrong-domain and stale-capability cases.
- Browser tests for preview, confirmation, progress recovery, keyboard use, and
  public/operator separation.
- Crash tests during queued, running, succeeded, and indeterminate transitions.
- Server tests on `oreochiserver` for agent isolation, listener state,
  backup/restore, restart persistence, rollback, and full smoke.
- Public artifact scans for identifiers, paths, ports, topology, secrets, API
  routes, and mutation code.

## Delivery gates

1. Land Phase 1 through reviewed PRs and verify it on `oreochiserver`.
2. Keep Phase 2 mutation endpoints absent until every Phase 1 negative-
   authorization and crash-recovery test passes.
3. Land Phase 2 through reviewed PRs.
4. Activate no protected-public route until the generated artifact passes its
   disclosure scan and operator-route isolation test.

## Implementation contract

### Existing code touchpoints

Phase 1 extends these existing components:

| Component | Current responsibility | Required change |
|---|---|---|
| `control-plane/api/server.py` | Loopback HTTP API and bearer-token checks | Session middleware, CSRF enforcement, operation resources, and compatibility wrappers |
| `control-plane/dashboard/generate_dashboard.py` | Static operator shell and synchronous controls | Session-aware operator shell, operation drawer, durable progress polling, and public-code exclusion |
| `scripts/argus_actions.py` | Synchronous legacy logs/restart/backup actions | Typed preview builders and legacy-agent handlers; no direct execution from HTTP handlers |
| `scripts/argus_m5_topology.py` | Allowlisted read-only topology | Agent availability, evidence revision, freshness, and operation eligibility projection |
| `scripts/argus_state.py` | Audited canonical-state support | Stable canonical revision and policy revision helpers |
| `runtime/argus/audit.sqlite3` | Durable audit evidence | Remains the audit sink; operation state uses a separate database |
| `systemd/` | Argus services and timers | API, worker, issuer, legacy agent, and domain-agent units |

Add these modules and entry points:

```text
scripts/argus_auth.py
scripts/argus_capabilities.py
scripts/argus_operations.py
scripts/argus_operation_worker.py
scripts/argus_domain_agent.py
scripts/argus_public_projection.py
scripts/argus-m5-bootstrap
systemd/argus-operation-worker.service
systemd/argus-capability-issuer.service
systemd/argus-legacy-agent.service
```

Domain-agent units and configuration are generated by
`scripts/argus-m5-bootstrap`; they are not hand-authored per workload.

### Identity and session protocol

The operator route uses Tailscale Serve to proxy to a dedicated loopback Caddy
listener. The public route never proxies to this listener.

The trusted proxy must:

- remove any client-supplied `Tailscale-*` and `X-Argus-*` headers;
- accept traffic only from the local Tailscale Serve upstream;
- pass the verified Tailscale login in `X-Argus-Tailnet-Login`;
- add a root-owned, randomly generated proxy marker from
  `/etc/argus/operator-proxy-token`;
- proxy operator requests only to the loopback API.

The API trusts the identity headers only when the peer address is loopback and
the proxy marker matches using a constant-time comparison. Direct requests with
identity headers are rejected.

`config/operators.json` is a tracked allowlist:

```json
{
  "schemaVersion": 1,
  "operators": [
    {
      "tailnetLogin": "operator@example.invalid",
      "role": "owner",
      "enabled": true
    }
  ]
}
```

The committed template uses only `.invalid` example identities. The real
server-local file is mode `0600`, excluded from Git, and backed up before edits.

Session exchange:

```http
POST /api/session/exchange
Content-Type: application/json
X-Argus-CSRF-Bootstrap: <random request nonce>

{"bootstrapToken":"<existing control token>"}
```

Requirements:

- request must carry a trusted, enabled tailnet login;
- bootstrap token comparison is constant-time;
- successful exchange rotates any prior session for that login;
- response sets `argus_session`, an opaque 256-bit random identifier, as
  `HttpOnly; Secure; SameSite=Strict; Path=/`;
- response sets `argus_csrf`, a separate 256-bit random value, as
  `Secure; SameSite=Strict; Path=/`, readable by the browser;
- only SHA-256 hashes of both values are stored;
- normal session lifetime is 30 minutes of inactivity and 8 hours absolute;
- step-up lifetime is 5 minutes;
- logout and operator disablement revoke the session immediately.

Every mutating request must present the CSRF value in both the `argus_csrf`
cookie and `X-Argus-CSRF` header. Missing or unequal values return `403`.
Cross-origin requests are denied. `Origin` must equal the configured private
operator origin.

Step-up reauthentication repeats the bootstrap-token check inside an existing
session and records `step_up_at`. Restore, deploy, migration cutover, migration
rollback, and protected-route activation require a step-up age of at most five
minutes.

### Session database

Store sessions in `/var/lib/argus/control/session.sqlite3`, owned by the API
service identity and mode `0600`:

```sql
CREATE TABLE sessions (
  session_hash TEXT PRIMARY KEY,
  csrf_hash TEXT NOT NULL,
  tailnet_login TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role = 'owner'),
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  absolute_expires_at TEXT NOT NULL,
  step_up_at TEXT,
  revoked_at TEXT
);
CREATE INDEX sessions_login_active
  ON sessions(tailnet_login, revoked_at, expires_at);
```

Schema migrations use SQLite `PRAGMA user_version`, execute inside
`BEGIN IMMEDIATE`, and back up the database before increasing the version.
Downgrade is unsupported; startup refuses a newer unknown version.

### Agent transport and ownership

Each trust domain owns one Unix socket:

```text
/run/argus/domains/<trust-domain>/agent.sock
```

Socket requirements:

- created by the domain-agent systemd unit;
- mode `0660`;
- owned by the domain identity and the dedicated `argus-control` group;
- removed when the service stops;
- accepts length-prefixed canonical JSON, maximum 64 KiB;
- request deadline is 10 seconds for preview and dispatch acknowledgement;
- operation execution continues independently after acknowledgement.

The agent runs as the domain runtime identity and may access only that domain's
runtime socket. The management API and operation worker may access the agent
socket but never the runtime socket.

The legacy compatibility agent runs as a dedicated service with an explicit
allowlist of Compose project names and script paths. It rejects any operation
whose target path or Compose project differs from canonical state.

Agent discovery is deterministic: canonical classification maps a workload to
one trust domain, and the socket path derives from that domain. Missing socket,
unexpected owner/mode, or failed `agent.status` marks the agent unavailable and
denies mutation.

### Capability issuer

`argus-capability-issuer.service` is a separate local service. It:

- listens on `/run/argus/capability-issuer.sock`, mode `0660`, group
  `argus-control`;
- owns the Ed25519 private key at
  `/etc/argus/capability-issuer/ed25519.key`, mode `0600`;
- exposes only `capability.issue`;
- signs only requests whose persisted approval, preview digest, expected
  revision, policy version, operator identity, and target domain match;
- refuses expiry greater than 60 seconds;
- logs the capability ID but never the private key or full signed envelope.

The API and worker do not read the private key. Agents receive the issuer public
key at `/etc/argus/domains/<domain>/issuer.pub`.

The signed canonical JSON envelope is:

```json
{
  "schemaVersion": 1,
  "capabilityId": "uuid",
  "operationId": "uuid",
  "idempotencyKey": "uuid",
  "operator": "tailnet-login",
  "workloadId": "workload-id",
  "trustDomain": "personal-managed",
  "operationType": "workload.restart",
  "parametersDigest": "sha256:...",
  "previewDigest": "sha256:...",
  "expectedRevision": "sha256:...",
  "policyVersion": "sha256:...",
  "issuedAt": "RFC3339 UTC",
  "expiresAt": "RFC3339 UTC",
  "nonce": "256-bit base64url"
}
```

The detached Ed25519 signature is transmitted beside the envelope. Canonical
serialization is UTF-8 JSON with sorted keys, no insignificant whitespace, and
no floating-point values.

Agents persist consumed `capabilityId` and nonce values in their domain-local
SQLite database before execution. Reuse returns `409 replayed-capability`.
Consumed records are retained for 24 hours after expiry. Issuer-key rotation
supports current and previous public keys for a 10-minute overlap; issuance
stops if distribution is incomplete.

### Canonical definitions

- **Canonical revision:** SHA-256 of canonical JSON containing the selected
  workload's records from `workloads.json`, `privacy.json`, `access.json`,
  classification, manifest, policy, and route configuration.
- **Policy version:** SHA-256 of canonical `policy.json` plus the workload's
  operation and security manifest sections.
- **Preview digest:** SHA-256 of the complete redacted preview response excluding
  `previewDigest`, timestamps, and presentation-only strings.
- **Policy-eligible:** manifest allows the operation, classification admission
  is not denied, agent is available, evidence is fresh, and operation-specific
  prerequisites pass.
- **Fresh evidence:** agent status and runtime observation are no older than 30
  seconds for restart/access, 60 seconds for backup, and 10 seconds for
  deploy/restore/migration.
- **Conflict:** any nonterminal mutating operation already holds the workload
  lock.
- **Verified backup contract:** manifest names all protected sources, backup
  artifact checksum verification passed, restore rehearsal passed for the same
  workload schema and runtime major version, and evidence is no older than 30
  days.

### Operation database

Store operations in `/var/lib/argus/control/operations.sqlite3`, owned by the
worker identity, group `argus-control`, mode `0660`.

```sql
CREATE TABLE operations (
  operation_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  workload_id TEXT NOT NULL,
  trust_domain TEXT NOT NULL,
  operation_type TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  parameters_json TEXT NOT NULL,
  parameters_digest TEXT NOT NULL,
  preview_json TEXT NOT NULL,
  preview_digest TEXT NOT NULL,
  expected_revision TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  approved_at TEXT,
  started_at TEXT,
  heartbeat_at TEXT,
  finished_at TEXT,
  error_class TEXT,
  redacted_summary TEXT NOT NULL DEFAULT '',
  rollback_operation_id TEXT REFERENCES operations(operation_id)
);
CREATE UNIQUE INDEX one_mutation_per_workload
  ON operations(workload_id)
  WHERE state IN (
    'awaiting-approval', 'queued', 'running', 'rollback-running',
    'indeterminate'
  );
CREATE TABLE operation_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_id TEXT NOT NULL REFERENCES operations(operation_id),
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  redacted_detail TEXT NOT NULL DEFAULT ''
);
```

The database uses WAL mode, `synchronous=FULL`, a five-second busy timeout, and
foreign keys. State change and event insertion occur in one `BEGIN IMMEDIATE`
transaction.

Allowed transitions:

```text
planned -> awaiting-approval | denied | expired
awaiting-approval -> queued | denied | expired
queued -> running | denied | expired
running -> succeeded | failed | rollback-running | indeterminate
failed -> rollback-running | indeterminate
rollback-running -> rolled-back | indeterminate
```

Terminal states never transition. Cancellation is allowed only from
`awaiting-approval` or `queued`, and records `denied` with reason
`operator-cancelled`. Running operations cannot be force-cancelled.

The worker claims queued operations inside `BEGIN IMMEDIATE`, writes
`started_at`, and sends the signed request. Agents heartbeat every five seconds.
After worker restart:

- queued work remains queued;
- running work with a fresh agent heartbeat is reattached;
- running work without a heartbeat for 30 seconds becomes `indeterminate`;
- no operation is automatically re-dispatched after acknowledgement.

Operation events are retained for 365 days. Session rows are deleted 30 days
after expiry. Maintenance runs from a daily timer and never deletes audit rows.

### Typed operation parameters

All payloads reject unknown keys.

```json
{"type":"health.refresh","parameters":{}}
{"type":"logs.preview","parameters":{"maxLines":100}}
{"type":"workload.restart","parameters":{"healthTimeoutSeconds":30}}
{"type":"backup.create","parameters":{"planRevision":"sha256:..."}}
{"type":"access.apply","parameters":{"desired":"none|local|tailnet"}}
{"type":"workload.start","parameters":{}}
{"type":"workload.stop","parameters":{"healthTimeoutSeconds":30}}
{"type":"workload.deploy","parameters":{"sourceRevision":"git-sha","healthTimeoutSeconds":120}}
{"type":"backup.restore","parameters":{"artifactId":"opaque-id"}}
{"type":"migration.cutover","parameters":{"planDigest":"sha256:..."}}
{"type":"migration.rollback","parameters":{"cutoverOperationId":"uuid"}}
{"type":"access.cloudflare-protected.apply","parameters":{"planDigest":"sha256:..."}}
```

`logs.preview` is non-mutating, capped at 100 lines, 65,536 bytes, and 600
characters per line, using the existing sanitizer. Every other listed type is
mutating and requires the workload lock.

### Operation API schemas

Preview:

```http
POST /api/workloads/<id>/operations/preview
X-Argus-CSRF: <token>
Idempotency-Key: <uuid>

{"type":"workload.restart","parameters":{"healthTimeoutSeconds":30}}
```

Success returns `200`:

```json
{
  "allowed": true,
  "workloadId": "workload-id",
  "trustDomain": "personal-managed",
  "operationType": "workload.restart",
  "parameters": {"healthTimeoutSeconds": 30},
  "expectedRevision": "sha256:...",
  "policyVersion": "sha256:...",
  "previewDigest": "sha256:...",
  "requiresConfirmation": true,
  "confirmationPhrase": "workload-id",
  "impact": {"availability":"brief-interruption","data":"none"},
  "rollback": {"available":true,"operationType":"workload.restart"}
}
```

Create:

```http
POST /api/workloads/<id>/operations
X-Argus-CSRF: <token>
Idempotency-Key: <same uuid>

{
  "previewDigest":"sha256:...",
  "expectedRevision":"sha256:...",
  "policyVersion":"sha256:...",
  "confirmation":"workload-id"
}
```

Success returns `202` with:

```json
{
  "operationId":"uuid",
  "state":"awaiting-approval",
  "statusUrl":"/api/operations/uuid"
}
```

Approval requires the same session, a current CSRF token, and an unexpired
preview. Preview validity is 60 seconds. Revision or policy drift returns `409`
and requires a new preview. Authentication returns `401`, authorization and CSRF
failures return `403`, unknown targets return `404`, conflicts return `409`,
expired previews return `410`, and validation failures return `422`.

The UI polls the status URL every two seconds while visible and every ten
seconds while backgrounded. Polling stops at a terminal state. Server-sent
events are out of scope for M5.

### Public artifact pipeline

`scripts/argus_public_projection.py` reads only
`config/argus/public-portfolio.json` and a coarse health input generated by the
metrics collector. It performs an explicit field-by-field projection and writes
an immutable static directory under `runtime/argus/public-view/<digest>/`.

The artifact contains only:

```text
index.html
style.css
portfolio.json
checksums.sha256
```

No operator dashboard JavaScript is copied. A disclosure scanner rejects:

- `/api/`, session, operation, topology, or management strings;
- RFC1918, loopback, tailnet, or host addresses;
- port-shaped URLs;
- filesystem paths;
- internal workload IDs;
- trust-domain names;
- environment, mount, volume, container, audit, or backup fields;
- secret-shaped keys or values.

Cloudflare activation may publish only a checksum-verified artifact directory.
It never reverse-proxies to the operator UI or API. Activation first creates a
plan, validates the protected hostname and Access policy, publishes, fetches the
artifact as an unauthenticated and authenticated client, proves management paths
return `404`, and then records effective state. Failure restores the prior
artifact pointer and route configuration.

### Ownership and rollout

- API/session work: `control-plane/api/`, `scripts/argus_auth.py`.
- Ledger and worker: `scripts/argus_operations.py`,
  `scripts/argus_operation_worker.py`.
- Issuer and agents: `scripts/argus_capabilities.py`,
  `scripts/argus_domain_agent.py`, `systemd/`.
- Operator UI: `control-plane/dashboard/generate_dashboard.py`.
- Public artifact: `scripts/argus_public_projection.py`.
- Server bootstrap and evidence: `scripts/argus-m5-bootstrap`,
  `docs/ARGUS_M5_*`.

Each area lands through a separate PR linked to issue #197. No PR may combine
session issuance, capability issuance, agent execution, and public activation.

### Executable verification gates

Every PR runs:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q control-plane scripts tests
python3 scripts/validate-manifests
python3 scripts/smoke-test --offline
git diff --check
```

Server gates on `oreochiserver`:

```bash
sudo ./scripts/argus-m5-bootstrap --preflight
sudo ./scripts/smoke-test
sudo ss -H -ltnp
sudo systemctl --no-pager --full status \
  argus-control-api.service \
  argus-operation-worker.service \
  argus-capability-issuer.service
```

Phase 1 cannot close unless:

- full smoke reports zero failures and zero warnings;
- replay, stale revision, wrong domain, expired session, CSRF, operation
  conflict, worker crash, and unavailable-agent tests pass;
- no workload runtime socket appears in the API or worker process mounts;
- no listener or route becomes public.

Phase 2 cannot activate protected-public viewing unless:

- disclosure scan reports zero forbidden fields;
- unauthenticated public management-path probes all return `404`;
- authenticated public requests still cannot reach operator endpoints;
- route rollback rehearsal passes;
- full smoke remains zero failures and zero warnings.
