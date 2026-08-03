<!-- /autoplan restore point: /home/oreochi/.gstack/projects/pxm-0-argus/p0-issue-remediation-plan-autoplan-restore-20260803-225058.md -->
# Argus Issue Remediation Plan

Status: approved for phased implementation on 2026-08-03
Parent tracking issue: `#197`
Planning branch: `p0/issue-remediation-plan`

## Goal

Bring Argus from a healthy but partly declarative control plane to a trustworthy
configured-estate operator experience. Complete the open P0 defects, fix the four
reported product gaps, reconcile stale GitHub trackers against real evidence,
and keep every mutation private, reviewed, reversible, and verified on
`oreochiserver`.

The operator-visible outcome is:

1. Refresh accounts for every configured estate source, not only running
   containers on one Docker socket, and exposes every stale, failed, excluded,
   or never-observed source.
2. A reviewed project can move between eligible trust domains through a typed
   preview, preflight, cutover, verification, and rollback workflow.
3. Reloading the dashboard preserves a valid operator session and explains
   exactly why restoration fails when it cannot succeed.
4. The dashboard has a real Argus favicon and a lower-density interaction model
   that keeps routine status visible while moving advanced controls into
   progressive disclosure.
5. Workloads sharing a trust domain cannot communicate across project bridges
   unless a reviewed relationship explicitly permits it.
6. Existing open P0 defects are either fixed and proven on the server or kept
   open with a precise remaining blocker.

## Premise Confirmation Gate

Status: **confirmed by the operator on 2026-08-03; Approach A below is the
approved current implementation path and Approach C is the gated strategic
horizon. The fully reviewed plan received final implementation approval on
2026-08-03.**

The CEO critique reframes the program around an evidence-backed operator loop:

```text
observe -> report completeness -> reconcile identity -> preview risk
        -> act through typed policy -> verify or recover
```

The proposed premises are:

1. Argus differentiates on private-by-default trust-domain policy,
   declared/observed/effective reconciliation, typed high-risk operations, and
   auditable evidence. Generic inventory and charts are replaceable plumbing.
2. "Configured estate" means every **configured source** is fresh, stale, failed, or
   intentionally excluded. Argus must never claim exhaustive knowledge of an
   open-ended host.
3. Discovery is useful only when it improves an operator decision. Unknown,
   stale, or conflicting observations must visibly lower completeness and block
   unsafe operations.
4. Discovery minimization happens inside each domain-local collector. Raw
   command lines, environment blocks, file contents, Git remotes, credentials,
   and arbitrary filesystem crawling never reach central storage.
5. Generic relocation begins as a durable migration kernel plus one real
   stateless pilot. Stateful moves stay blocked until a workload-specific
   backup and isolated restore contract is proven; generalization follows a
   second materially different migration.
6. The work ships as three programs with separate clocks: immediate safety,
   operator reliability, and lifecycle platform. The umbrella tracker preserves
   the complete outcome without making every item equally urgent.

### Strategic implementation alternatives

| Approach | Shape | Effort | Risk | Completeness |
| --- | --- | --- | --- | --- |
| A. Staged evidence platform | Contain security first; then reliability; then versioned source registry, typed collectors, and pilot-led migration kernel | L | Medium, bounded by child PRs | 9/10 |
| B. Patch symptoms | Fix isolation, refresh query, cookie behavior, density, and favicon independently | M | High long-term drift | 5/10 |
| C. Deterministic Argus kernel with a commodity observation/visualization companion | Keep Argus control workspace, policy, authorization, evidence, and typed operations; evaluate private commodity inventory or visualization behind one-way read-only adapters | XL | High integration and trust-boundary risk unless strictly contained | Unscored option-value hypothesis pending evaluation |

**Current implementation path:** Approach A. **Strategic horizon:** Approach C.
A fixes the reported problems now while creating the versioned, replaceable
source and presentation interfaces needed to evaluate C without rewriting or
weakening Argus's private control kernel. C is not authorized for implementation
in this remediation program; it requires a separate evidence-backed evaluation,
ADR, threat model, rollback plan, issue, and pull request after A's exit criteria
are met.

Approach C may supplement or replace commodity inventory and visualization
plumbing. The Argus control workspace remains authoritative and required for
every action. C may not own canonical policy, authorization, capability issuance,
operation confirmation, mutation dispatch, authority fencing, or acceptance
evidence. A candidate must run privately, support pinned/versioned deterministic
interfaces, export its state, tolerate removal, and integrate read-only without a
central Docker socket or broad host privilege. A candidate that requires public
control, opaque cloud state, autonomous action, AI reasoning, or write authority
is ineligible.

C-sourced data is classified as `external_advisory_observation`, not authoritative
observation. It never directly changes `permittedActions`. An
`advisory_conflict` requests a bounded Argus-native refresh; only fresh native
evidence, or an Argus-owned source made required by explicit canonical policy,
may resolve or block the operation. If native evidence remains unknown or
conflicting, the existing native fail-closed rule blocks it. Stale, absent,
malformed, corrupt, or removed C data remains visible but non-gating and cannot
change canonical or authority state or an authority-changing native-evidence
preview digest. Authority-critical absence, identity, placement, capacity,
health, route, and fence facts always require Argus-owned evidence or
a second independent Argus-owned native source governed by canonical source
policy. C observations never count as authority-critical corroboration.

Advisory-triggered native refresh requests are deduplicated by candidate,
source, and snapshot digest; rate-limited, coalesced, and constrained by cooldown
and concurrency budgets. Repeated failures trip a visible non-gating circuit
breaker. They cannot starve or disable normal operator/native refresh.

A C user interface receives no Argus cookie or session, cannot proxy the control
API, submit an operation, or encode approval/confirmation in a URL. It may link
only to an inert Argus resource route; Argus then acquires fresh native evidence,
builds a new preview, and performs its normal step-up and confirmation flow.
Each candidate uses exactly one separately reviewed direction: `C -> Argus`
advisory observation ingest or `Argus -> C` redacted presentation export. No
bidirectional bridge is permitted.

### Approach C evaluation gate

Evaluation begins only after D1 and D5 contracts are stable, D6 and PR 5B have
landed, and the three operator journeys have a recorded post-A baseline. Stable
means compatibility tests pass across at least two schema versions with no
breaking change during the declared observation window. The separate decision
must prove all of the following:

1. The candidate improves a measured inventory or operator workflow enough to
   justify its added deployment and upgrade surface.
2. It runs private/offline where required, is version-pinned, and needs no
   Funnel, public listener, public tunnel, DNS change, or router port.
3. Its Argus integration consumes or emits only versioned, bounded, deterministic,
   read-only data; ambiguous identity is reported as conflict, never guessed.
4. It receives no Argus control session, capability/signing key, mutation-agent
   socket, operation-ledger write access, or canonical-policy write access.
5. Installation, upgrade, export, disablement, and removal are rehearsed, and
   Argus continues safely when the candidate is absent or stale.
6. The result remains useful with all AI/autonomous features absent or disabled.
7. A predeclared commodity workflow improves by at least 30% in time/steps, or
   configured-source coverage improves by at least 20% versus functionality
   Argus would otherwise need to build. Cosmetic benefit does not qualify.
8. CPU, RAM, storage, refresh latency, upgrade effort, and incident burden remain
   inside recorded candidate budgets; disable/remove/re-enable completes inside
   its approved window with every Argus acceptance probe unchanged.
9. A vendor-neutral conformance harness and fixture-backed reference adapter
   prove add/remove without repository, policy, or UI-core changes.
10. Future-only evidence records candidate/adapter/version, the selected one-way
    direction, config/sanitization-policy/snapshot digests, last success,
    `advisory-stale`/`advisory-circuit-open`/`advisory-disabled` state, and removal
    proof. These fields and reason codes do not enter Approach A schemas.

### Program lanes and priority order

1. **Immediate safety release:** cross-project sandbox isolation (`#270`) and
   only its safe-deployment blockers.
2. **Operator reliability release:** diagnose/fix session restoration, define
   truthful configured-source completeness, reduce dashboard density, add the
   Argus icon, and reconcile already-implemented P0 trackers.
3. **Lifecycle platform program:** source-registry and collector slices,
   reconciliation UI, migration kernel, stateless pilot, rollback rehearsal,
   and later evidence-driven adapters.

Ordered dependency path:

```text
PR 0 plan -> PR 0B workflow/current-doc truth -> PR 1 isolation
  -> PR 6A canonical tests + Linux/macOS CI -> PR 6B stable CLI/docs contract
                                      |
                 +--------------------+-> PR 2A diagnosis -> PR 2B confirmed fix
                 +--------------------+-> PR 5A identity/state prototypes -> D1 -> D2/D3/D4 -> D5 -> D6
                                                   \-> M1 design -> M2 eligibility gate
                                                                  |
                                                        eligible --+-> M3 -> M4 -> M5
                                                        none ------+-> stop Epic M
                 +--------------------+-> PR 7 acceptance audit -> separate evidence-driven fixes

PR 5B follows stable D5/M1 contracts and the approved PR 5A prototypes.
```

Epic D and Epic M below are umbrella outcomes. After this gate is confirmed, each
will be decomposed into child issues and independently useful, reversible PRs;
they will not land as epic-sized pull requests.

### Execution prerequisites

- Approved operator access to `oreochiserver` is required for server discovery,
  firewall, migration, and workload acceptance. Without it, affected PRs remain
  draft and diagnostic-only.
- An authenticated browser path through the real Tailscale HTTPS origin is
  required before the session root-cause/fix issue leaves diagnosis.
- The migration pilot requires fresh evidence for an eligible same-realm source
  and target: installed agent, capacity, storage, UID/GID mapping, route plan,
  backup/rollback capability, and no target collision.
- macOS portability is accepted through a maintained macOS CI job. Until that
  job exists, reproducible operator-run evidence must record the OS/Python
  versions and exact standard-discovery command.

### Measurement procedure

Before each implementation slice, its regression fixture or safe live probe is
run three times and recorded in the linked issue/PR acceptance table. After the
change, the same probe is repeated. Session reloads use browser automation or an
operator transcript with secret-free status flags; refresh duration and source
states come from structured discovery summaries; workflow steps are counted
from the reviewed UI journey; migration and rollback timing comes from the
durable operation journal.

The initial thresholds are binary where safety is involved: zero false-complete
states, zero unrelated reachable project pairs, zero silent restoration
failures, and every operation failure has a stable documented reason code and
recovery state. Performance budgets are set from the three-run pre-change
baseline before implementation: the maximum refresh duration may not regress by
more than 20%; routine alert-to-cause interaction steps must fall
by at least 30%; and pilot rollback must complete inside the approved downtime
budget recorded at pilot selection.

### Umbrella-to-child delivery map

| Child slice | Independent outcome | Depends on |
| --- | --- | --- |
| D1a repository contract | Versioned vendor-neutral source registry, atomic collection-run schema, state model, threat model, retention, build-versus-integrate matrix, adapter conformance suite, and fixture-backed reference adapter | security release; PR 5A prototype |
| D1b collector protocol | Separate read-only collector socket, paged envelope, scheduler/bounds, and per-source execution contract | D1a |
| D2a rootful Docker collector | Rootful daemon reports running/stopped resources with local minimization | D1b |
| D2b rootless-domain collectors | Every configured rootless daemon reports through its own identity/socket | D2a contract, D1b |
| D3 host service/schedule collectors | Configured system/user systemd and cron sources report bounded evidence | D1b |
| D4 optional evidence sources | Processes/listeners, routes, cloudflared, and configured repository/manifest roots answer explicit operator questions | D1b; separately accepted source contracts |
| D5 reconciliation/API | Known, unknown, stale, conflicting, and gap summaries remain distinct from canonical truth | D2-D4 as available |
| D6 completeness UI | Operator sees source coverage and which gaps block an action | UI state prototype, D5 |
| M1 design contract | Existing ledger contract specifies preview/preflight/cutover/rollback phases and authority fencing without implementation | D5 freshness contract; PR 5A prototype |
| M2 pilot selection | Read-only evidence names the eligible workload and source/target pair, or stops Epic M because none is safe | M1 design contract |
| M3a coordinator schema/crash fixtures | Parent/child ledger, authority record/epoch, exclusive locks, and every crash transition are proven offline | M2 |
| M3b migration kernel and stateless pilot | Implement the minimum source/target adapters and move one reviewed workload with identity, route, health, and single-writer proof | M3a |
| M4 rollback rehearsal | The pilot returns safely within its recorded downtime budget | M3b |
| M5 relocation UI | Fixture-backed flow exposes blockers, confirmation, progress, evidence, and recovery | UI state prototype, M1-M4 |

The pilot workload and domain pair are intentionally not guessed from stale
inventory. M2 selects them from fresh sanitized server evidence. "Stateless"
means no durable application data, database, mutable bind mount, or external
writer; source identity can be recreated from reviewed configuration; route
cutover is reversible; and temporary unavailability stays within the approved
downtime budget.

### Discovery source state model

| Current state | Permitted next states | Cause |
| --- | --- | --- |
| `never_observed` | `fresh`, `failed`, `excluded` | first success, first failure, or explicit reviewed exclusion |
| `fresh` | `fresh`, `stale`, `failed`, `excluded` | successful refresh, freshness expiry, collection failure, or reviewed exclusion |
| `stale` | `fresh`, `failed`, `excluded` | recovered refresh, failed refresh, or reviewed exclusion |
| `failed` | `fresh`, `failed`, `excluded` | recovered refresh, repeated failure, or reviewed exclusion |
| `excluded` | `never_observed` | explicit re-enable; new evidence is required |

Every D1 source contract names its execution identity, exact command/API
allowlist, timeout, output bound, field allowlist/minimization rules, bootstrap
method, and rollback/removal method.

Only `fresh` contributes to the fresh-source numerator. `stale`, `failed`, and
`never_observed` reduce completeness and block operations that depend on that
source. `excluded` remains visible in the denominator report with its reviewed
reason, but does not masquerade as observed coverage.

## Hard Boundaries

- Keep the dashboard and control API private behind Tailscale Serve.
- Do not enable Funnel, Cloudflare tunnels, DNS, router ports, or public
  listeners.
- Do not expose PostgreSQL, Docker sockets, credentials, runtime files, source,
  backups, or private topology.
- Preserve Compose project names and workload identity during relocation.
- Keep management free of workload Docker sockets. Configured-estate observation
  uses typed, read-only domain collectors rather than central raw-socket access.
- Back up server configuration before edits and validate Caddy before reload.
- Land the plan and every implementation slice through a separate pull request
  linked to its matching issue.
- Keep the Argus decision and control path fully deterministic. No AI, LLM,
  learned model, probabilistic classifier, or autonomous agent participates in
  collection, normalization, reconciliation, policy, authorization, preview,
  confirmation, scheduling, mutation, migration, recovery, or evidence.
- AI is never a fallback for an unknown, stale, conflicting, or failed state.
  Those conditions remain explicit and fail closed.

The **Argus core boundary** comprises the `control-plane` package/processes,
Argus-owned `scripts`, collectors and mutation agents, canonical/observation/
operation repositories, the private API and generated dashboard, systemd units,
schemas, and every endpoint they own. Core dependencies and endpoints are
allowlisted and locked; CI records dependency metadata/SBOM, rejects model SDKs
and model endpoints, rejects undeclared dynamic plugin loading, checks explicit
outbound-network policy, and runs deterministic replay tests. A future Approach C
companion is outside this boundary and cannot extend its authority.

### Determinism contract and optional future AI boundary

Live acquisition is time-varying rather than reproducible: it is bounded,
versioned, timestamped, and captured as immutable pages with explicit deadlines
and result reasons. Source completion order cannot affect the committed normalized
snapshot; actual success, timeout, and failure outcomes become recorded inputs.

For a pinned Argus version, schema set, configuration, canonical input, captured
observation pages, and explicit clock value, the decision transformations must produce
byte-identical canonical JSON, reason codes, permitted-action set, and preview
digest. Input enumeration order, process scheduling, locale, and hash-map order
must not affect the result. Canonical serialization uses stable key ordering and
defined number/string and Unicode encodings. Wall-clock reads, nonces, generated IDs, and
timestamps are injected and recorded; they may identify an event but never
silently change its policy result. Ambiguity becomes a typed conflict or gap and
blocks dependent mutations instead of invoking a heuristic.

Any future AI experiment is a separate, default-disabled advisory system and is
not part of Argus's trust boundary. It must run in an isolated process or host
with no inbound control listener and, where practical, no network. Its only input
is a one-way export of an explicit allowlisted, redacted, immutable snapshot
exposed read-only inside a disposable boundary. It
receives no Docker socket, host filesystem, workload source/data, credentials,
session, control API, canonical database write access, operation-ledger write
access, mutation-agent socket, issuer/signing key, or route authority. Its output
is untrusted advice: it cannot become observed/canonical/effective state, approve
or confirm an operation, create a capability, issue a command, or count as
acceptance evidence. The Argus core has no advisory import module, watcher, API,
parser, or shared writable path. A human may view advice only as inert plain text
or sanitized static content on a separate origin/process without Argus credentials
or browser session; scripts, forms, embedded content, active/control URLs, and
operation or confirmation parameters are rejected. No advisory writable mount is
visible to Argus. Any subsequent action is independently recreated as a new
deterministic typed proposal through normal Argus controls. Model, runtime,
prompt/template, input digest, and output digest are provenance only—not proof of
correctness.

These clauses are acceptance conditions for a separate future ADR, not current
implementation scope. Approach A creates no AI export, process, UI, endpoint,
schema, import path, or advisory fixture. Its only AI-related work is proving the
Argus core dependency, endpoint, network, and deterministic-execution exclusions.

## Current Evidence

- `origin/main` is `c5c6793`; current `main` CI and the P0 PR guard pass.
- The private dashboard and API respond through the Tailscale HTTPS route.
- Five enabled workload health endpoints return HTTP 200; `hello-nginx` health
  is disabled.
- The live metrics document reports 12 containers from the collector's default
  Docker context, but Argus has active workloads across separate rootless trust
  domains.
- `scripts/argus-workload-discover` calls only `docker ps` and reads running
  Compose labels from the caller's default socket.
- `control-plane/monitoring/collect_metrics.py` has the same default-socket
  limitation.
- `scripts/argus-m5-workload-cutover` hard-codes five workloads and fixed target
  domains; it is not a reusable relocation operation.
- The deployed dashboard contains session restoration code and eight-hour
  Secure cookies, so reload logout is a runtime boundary failure that still
  needs an authenticated reproduction.
- The favicon is intentionally empty (`data:,`), and each workload card mixes
  status, evidence, history, and advanced operations in one dense surface.
- Open issue `#270` records cross-project bridge reachability inside a shared
  sandbox. It is the first implementation priority.
- Issues `#265` and `#266` describe workload functionality and backup gaps.
  Recent `main` commits add relevant remediation, but server acceptance and
  issue closeout remain unproven.
- Issues `#217`, `#218`, and `#219` describe Phase 1 capabilities that have
  merged implementations but remain open; they require acceptance-ledger
  reconciliation, not duplicate implementation.
- Baseline source/dependency search finds no AI SDK or model endpoint in the
  Argus core. The only non-plan model reference is privacy/manifest metadata for
  a managed workload, which is outside the named Argus core boundary and grants
  Argus no model dependency or access.

## CEO Review: Strategy and Scope

### Product thesis

Argus is not another container dashboard. Its durable advantage is a private,
single-host control plane that distinguishes declared, observed, and effective
state across isolated trust domains, then permits only typed, evidenced,
reversible operations. Commodity host and container inventory may be reused;
Argus owns policy, reconciliation, authorization, and the evidence trail.
The long-term product may place a replaceable commodity management surface around
that kernel, but the kernel remains deterministic, private, inspectable, and
independent of AI or opaque external control state.

### Existing-code leverage map

| Sub-problem | Existing foundation | Plan decision |
| --- | --- | --- |
| Domain-local observation | `ARGUS_V1_BRIDGE.md`, D005 in `docs/ARGUS_V1_DECISIONS.md`, bounded IPC framing | Add a separate read-only collector process/socket and share only schema/validation code; keep the mutation-agent protocol operation-ID-only. |
| Canonical versus observed state | `scripts/argus_state.py`, canonical repositories, fail-closed mutation gates | Add source completeness and observation provenance behind repository interfaces; do not make observations canonical. |
| Durable operations | operation ledger, worker, capability issuer, idempotency and audit contracts | Add migration phases as typed operations; do not create a second job or journal framework. |
| Migration staging | M4 planner/cutover modules and M5 stage/cutover scripts | Extract only proven common primitives after the stateless pilot; retain explicit workload adapters. |
| Sessions | `scripts/argus_sessions.py`, session boundary script, API cookie/CSRF handling, `restoreOperatorSession()` | Diagnose the deployed boundary first and patch the failing layer; do not replace the session model or extend lifetime blindly. |
| Dashboard | generated dashboard, inspector/history panels, operation-state rendering | Recompose existing information into overview and detail layers before adding components. |
| Discovery | `argus-workload-discover`, metrics collector, inventory/manifests | Preserve these as compatibility sources while introducing the source registry and normalized observations. |
| Isolation | M4/M5 sandbox bootstrap, nftables verification and rollback scripts | Replace wildcard bridge acceptance with generated project relationships inside the existing policy/apply/verify path. |

### Dream-state delta

```text
CURRENT
  container-biased refresh + dense dashboard + fixed migration scripts
      |
      v
THIS PROGRAM
  configured-source completeness + calm operator workflow
  + typed migration kernel/pilot + project-isolated bridges
      |
      v
12-MONTH IDEAL
  every configured source proves freshness and provenance
  -> reconciliation explains conflicts
  -> policy previews the safe action set
  -> durable operations verify or recover automatically
  -> replaceable read-only management adapters may improve inventory and UI
  -> the operator can reconstruct every decision without raw privileged access
```

This program reaches the trustworthy single-host operator loop. It deliberately
does not yet adopt a general management product, add multi-host orchestration,
automatic adoption, public exposure, AI reasoning, or a generic arbitrary-command
plane. It preserves the seams needed to evaluate the stronger Approach C later.

### Outcome baselines and stop conditions

Each program records a pre-change baseline and post-change result:

| Outcome | Measure | Required direction |
| --- | --- | --- |
| Isolation confidence | unrelated project pairs reachable | zero reachable pairs |
| Session reliability | authenticated reload and browser-restart success | 100% until declared expiry/revocation |
| Refresh truthfulness | fresh configured sources / configured sources | displayed exactly; never implied complete when below 100% |
| Discovery usefulness | unknown/conflicting observations and unsafe actions blocked | every unknown explained; unsafe operations denied |
| Operator efficiency | time/clicks from workload alert to cause and next action | materially lower than the recorded baseline |
| Migration safety | preview blockers, rehearsal time, rollback recovery time | all blockers explicit; pilot and rollback meet recorded budgets |
| Tracker integrity | open items with code-only completion claims | zero; every closure linked to acceptance evidence |

Collector expansion pauses if its first Docker-domain and host-service slices do
not improve completeness truthfulness or an operator decision. Migration
generalization pauses until a second materially different workload demonstrates
real shared behavior.

### CEO dual-voice result

The independent subagent raised twelve issues. Its critical findings were the
mixed urgency of the original program and the sensitive-data blast radius of
broad discovery. Both are incorporated through separate program clocks,
collector-side allowlists, configured roots, and local minimization. The Codex
CLI voice was attempted twice but returned no review body, so it is recorded as
unavailable rather than treated as agreement.

| Dimension | Independent subagent | Codex CLI | Primary decision |
| --- | --- | --- | --- |
| Premises valid | Reframe exhaustive scan as configured evidence | unavailable | confirmed with the operator |
| Right problem | Optimize operator confidence, not inventory breadth | unavailable | accepted |
| Scope calibration | Split security, reliability, and platform clocks | unavailable | accepted |
| Alternatives | Add build-versus-integrate comparison | unavailable | accepted for each discovery slice |
| Competitive risk | Do not compete as a generic dashboard | unavailable | product thesis added |
| Six-month trajectory | Add outcomes and stop conditions | unavailable | accepted |

### CEO section audit

| Review section | Result |
| --- | --- |
| Architecture | Existing typed agents, repository boundaries, and ledger are the correct spine; epic-sized discovery and migration work must be child PRs. |
| Error and rescue | Partial sources, stale evidence, lost session boundaries, authority-switch failures, and firewall rollback require explicit safe states; registry below covers them. |
| Security | Collector minimization must happen before central transport; no raw sockets, command lines, environments, file contents, or unconstrained crawling. |
| Data and UX | Configured-source completeness and operation blockers are first-class operator concepts, not backend diagnostics. |
| Code quality | Extract common migration behavior only after two concrete implementations; premature universal adapters are rejected. |
| Tests | Fixture, failure, concurrency, rollback, browser-origin, and server acceptance matrices are required per child PR. |
| Performance | Collectors are bounded, timed, paginated where needed, and return partial results; refresh must not serialize unrelated sources. |
| Observability | Safe reason codes, source freshness, operation phase, and evidence IDs are required; credentials and raw private topology remain excluded. |
| Deployment | Security containment ships first with backup/apply/rollback/reboot proof; later slices are independently deployable and reversible. |
| Long-term trajectory | Stable host/source identity and versioned schemas avoid a future destructive identity migration without adding multi-host scope. |
| Design | Prototype summary hierarchy and state tables before discovery/migration response contracts freeze. |

### Temporal decisions resolved before implementation

| When | Decision now locked |
| --- | --- |
| Foundation | One versioned observation envelope, one source registry, existing repository/agent/ledger boundaries. |
| Core logic | Freshness, conflict, and completeness are explicit enums/reason codes; incomplete evidence blocks mutation. |
| Integration | Each source owns minimization and timeout behavior; UI consumes stable summaries rather than collector internals. |
| Polish and tests | Every child PR supplies offline fixtures, negative paths, sanitized server evidence, and rollback proof proportional to risk. |

### CEO completion summary

- Mode: selective expansion, with Approach A confirmed now and Approach C set as
  the gated strategic horizon.
- Critical gaps found: two; both folded into the plan.
- Scope proposals accepted: configured-source boundary, collector threat model,
  product thesis, outcome baselines, pilot-led generalization, and pre-schema UI
  prototyping.
- Deferred: multi-host orchestration, automatic adoption, arbitrary filesystem
  search, universal stateful migration, and the separately evaluated Approach C
  management layer.
- Reversibility: 4/5; server mutation remains gated by backup, validation,
  preflight, typed apply, verification, and reviewed rollback.
- Unresolved CEO decisions: zero.

## Design Review: Operator Experience Contract

The current plan began at 5/10 design completeness: it named progressive
disclosure and accessibility, but did not lock the landing hierarchy, cross-
surface states, semantic vocabulary, navigation persistence, or mobile
transformation. The following contract raises it to 9/10 before implementation.
The remaining point is reserved for rendered live-browser validation.

No project `DESIGN.md` exists and the gstack visual designer is unavailable.
PR 5A therefore produces a fixture-backed HTML wireframe plus a concise
`DESIGN.md` token/component/state contract before D1 or M1 schemas freeze.

### Information architecture

```text
GLOBAL HEADER
  Argus | estate completeness/freshness | operator session | Refresh estate

OVERVIEW (exceptions first)
  1. Action-required exceptions
  2. Host / exposure / domain health
  3. Compact workload table grouped by trust domain

WORKLOAD DETAIL (route-backed responsive panel)
  Summary | Evidence | Operations | History

ESTATE COVERAGE
  Configured sources | freshness | gaps | exclusions | refresh progress

OPERATION CENTER
  Awaiting approval | running | failed/recovery | completed evidence
```

The landing view answers, in order: **Is the estate safe? Is this view complete
and fresh? What needs me? What exists?** Topology becomes an optional placement
view, not the first and largest surface. The duplicated full workload-card wall
is removed.

Deep links use durable route state equivalent to
`#/workloads/{id}?tab=evidence&operation={id}`. Back/forward, reload, links from
alerts, and focus return preserve the selected workload, tab, and operation ID;
secret input is never persisted.

### Density and action budgets

- Global header: one primary action (`Refresh estate`) and at most three compact
  utilities (session, monitor, theme).
- Workload overview row: identity, trust domain, health, effective access/drift,
  evidence freshness, and one contextual action.
- Default contextual action: investigate the highest-severity exception;
  otherwise open workload details.
- Workload detail: summary first; evidence, history, and advanced controls in
  separate tabs/sections; at most two active operations before `More operations`.
- Authentication never reveals every mutation control. Step-up is requested at
  the point of commitment inside workload detail.

### Interaction-state matrix

| Surface | Required visible states | Visible action/recovery contract |
| --- | --- | --- |
| App startup | loading shell, last-known-good unavailable/available, fatal load error | announce startup once; retain safe cached-free shell; retry state load |
| Operator session | checking, signed out, signed in, step-up required, expiring, expired, revoked, restore unavailable | dedicated session control; sign in/retry/logout; never present restore failure as voluntary logout |
| Estate refresh | idle, queued, running, partial, timed out, completed, failed, stale-after-failure | keep last completed evidence visible; show elapsed time and per-source counts; retry failed sources or open coverage |
| Source coverage | never observed, fresh, stale, failed, excluded, conflicting | show stable reason code, evidence time, owner, impact, and which actions are blocked |
| Workload detail | loading, ready, stale, conflict, unavailable, not found | preserve route; show last-known-good summary and recovery path |
| Operation preview | checking, allowed, blocked, stale preview, conflicting evidence | list impact/blockers; refresh evidence; no mutation controls when blocked |
| Confirmation | ready, step-up required, digest changed, session expired | real accessible dialog; type exact identity/digest only immediately before authority-changing cutover |
| Durable operation | queued, awaiting approval, running, cancellation requested, succeeded, failed-safe, failed-indeterminate, recovery required | announce phase changes; reload from operation ID; expose only safe cancel/retry/rollback actions allowed by journal state |
| Rollback | available, running, verified, failed-before-switch, failed-after-switch | state current authority explicitly and focus the next safe recovery action |
| Empty estate/filter | no configured sources, no workloads, no matches | distinguish configuration from filtering; give one relevant next action |

Every prototype state specifies visible copy, permitted and blocked actions,
focus target, live announcement, reload persistence, and recovery route. Last-
known-good evidence is never replaced by a spinner or incomplete refresh.

### Confirmation and panel semantics

- Workload details and command results are nonmodal complementary panels with
  unrestricted document focus and route state.
- Typed cutover confirmation is a real modal dialog with `aria-modal`, initial
  focus, contained tab order, Escape behavior, inert background, focus return,
  session-expiry handling, and a digest-change invalidation path.
- Dynamic announcements use dedicated concise status nodes. Replacing an entire
  inspector never triggers a verbose `aria-live` replay.
- Tabular comparison uses a semantic table. If a responsive record layout is
  used, each value retains a programmatic field label.

### Semantic visual system

PR 5A defines independent text/icon/color mappings for:

- health: healthy, degraded, down, unknown;
- freshness: fresh, stale, never observed;
- completeness: complete, partial, failed, excluded;
- policy: allowed, blocked, conflict;
- operation: queued, approval, running, succeeded, failed-safe,
  indeterminate, recovery;
- privacy: unclassified, internal, sensitive, restricted.

Focus, links, success, availability, privacy, and freshness do not share one
ambiguous color. State is never encoded by color alone. The visual language
removes decorative numbering, generic sci-fi copy, ornamental glow, and
unearned pill/box repetition; Argus identity communicates watchfulness,
reconciliation, and private control in plain operator language.

One stylesheet source becomes canonical. The unused embedded `CSS` string in
`generate_dashboard.py` is removed when `m5_style.py` is retained or replaced;
the plan will not maintain two competing systems.

### Argus identity asset family

One reviewed vector master produces `favicon.svg`, 16/32px PNG fallbacks, an
Apple touch icon, and standard/maskable web-app manifest icons. Tests cover
monochrome, 16px, light, and dark legibility. No external runtime asset or font
dependency is introduced; any bundled typeface must include a compatible
license, otherwise the design uses a carefully specified native fallback stack.

### Responsive and accessibility contract

- Breakpoints are validated at 320, 375, 768, 1024, and a wide desktop.
- Below the desktop table breakpoint, workloads become compact labeled records;
  primary status never depends on a horizontally scrolled 680px matrix.
- Workload detail becomes a full-width route-backed sheet/view on small screens.
- Interactive targets are at least 44x44 CSS pixels. Body copy remains readable,
  labels meet contrast requirements, zoom to 200% preserves operation access,
  and reduced motion removes nonessential transitions.
- Keyboard tests cover skip/navigation, row selection, tabs, panel close/focus
  return, modal tab loop/Escape, refresh progress, session expiry, and recovery.
- Navigation updates `aria-current`; startup/refresh use `aria-busy` plus concise
  status nodes; headings and landmarks remain ordered.
- Without JavaScript, the private route fails closed with Argus identity and
  `JavaScript required`; it renders no estate data, credentials, cached state,
  or mutation controls.

### Operator journey and measured tasks

```text
arrival -> calm confidence: private, session state, completeness, exceptions
exception -> focused concern: exact stale/conflicting source and blocked decisions
investigation -> orientation: workload, evidence age, reason, next action
preview -> informed caution: impact, blockers, authority boundary, rollback
commitment -> deliberate friction: step-up + exact digest confirmation
execution -> controlled attention: durable phases and safe recovery
completion -> proof: identity, route, health, and evidence verified
failure -> agency: current authority explicit, mutation fenced, next safe action
```

PR 5A baselines and prototypes three journeys: investigate stale discovery,
diagnose access drift, and recover a failed operation. Counting includes clicks,
keystrokes, panels opened, backtracking, and time-to-cause. PR 5B must reduce
routine interaction steps by at least 30% without hiding evidence or weakening
confirmation.

### Design-pass result

| Pass | Initial | After contract | Key resolution |
| --- | ---: | ---: | --- |
| Information architecture | 4/10 | 9/10 | exceptions-first overview and durable detail routes |
| Interaction states | 3/10 | 9/10 | unified startup/session/source/operation/recovery matrix |
| Journey/emotional arc | 5/10 | 9/10 | evidence-backed calm-to-recovery storyboard and task baselines |
| AI-slop risk | 5/10 | 9/10 | remove sci-fi ornament and encode operator meaning only |
| Design-system alignment | 4/10 | 9/10 | one canonical stylesheet plus semantic state contract |
| Responsive/accessibility | 6/10 | 9/10 | mobile record transformation, 44px targets, dialog/route semantics |
| Unresolved decisions | 8 open | 0 open | recommendations auto-decided under confirmed Approach A |

The independent design voice produced two P0 and twelve lower-severity gaps;
all are incorporated above. The Codex CLI voice remains unavailable and is not
counted as cross-model consensus. Rendered implementation still requires live
desktop/mobile, keyboard, screen-reader, contrast, and reduced-motion QA.

## Engineering Review: Executable Architecture

The engineering pass started with ten material gaps. All are resolved below and
in the amended delivery scopes. The independent review was grounded in the
current single-domain operation ledger, operation-ID-only agent protocol,
64-KiB IPC bound, synchronous container-only discovery endpoint, session lookup,
Linux-only CI, and wildcard nftables rule.

### Trust-boundary architecture

```text
private browser
  | HTTPS + session/CSRF
  v
ThreadingHTTPServer API
  |                       SQLite repository transaction
  | refresh 202 + run ID       |
  v                            v
collection scheduler ---> sources / runs / observations / links
  | bounded paged IPC              |
  +----------+----------+----------+---> reconciliation summaries
             |          |
       host collectors  per-domain collector.sock
                         (read only; runtime read permission only)

operation coordinator ---> parent migration + operation ledger
             | separately authorized child operation IDs
             +---------- source agent.sock (mutation protocol only)
             +---------- target agent.sock (mutation protocol only)
```

Collectors and mutation agents are different processes, sockets, principals,
protocol methods, and systemd units. Shared code is limited to canonical JSON,
bounded framing, schemas, validation, redaction, and reason-code definitions.
The collector cannot import or receive the operation ledger, issuer, replay
store, capability keys, or mutation dispatch implementation.

Every decision-bearing transformation is a pure, versioned function over an
explicit input bundle. Repositories and collectors acquire inputs; deterministic
normalizers, reconcilers, policy evaluators, and renderers compute results;
separate effectors apply an already-confirmed digest. No model inference,
similarity match, confidence score, or unrecorded ambient input is permitted in
that path. Native identity mismatches remain typed unresolved conflicts.

### Discovery data flow

```text
POST refresh
  -> validate session/CSRF -> create collection_run(queued) -> 202 runId
  -> scheduler launches bounded independent sources
  -> collector minimizes locally -> page(1..N, digest)
  -> ingest non-current rows -> validate terminal page/bounds/schema
     -> success: atomic current-run switch + reconcile + publish summary
     -> partial/failure: record source gap; retain last completed snapshot
  -> UI polls/subscribes by runId and preserves last-known-good evidence
```

Nil, empty, error, and stale paths are distinct: missing source registration is
a contract error; a valid empty terminal run is fresh and empty; timeout or
transport/schema failure is failed/partial; freshness expiry is stale. None can
silently replace the last completed snapshot or claim completeness.

The envelope carries `protocolVersion`, `runId`, `sourceId`, `hostId`,
`sequence`, `terminal`, `recordCount`, `byteCount`, `runningDigest`, and an
array of allowlisted normalized records. The scheduler caps concurrent sources,
per-source duration, global duration, records, bytes, stdout, and stderr.
D5 and D6 consume only the normalized vendor-neutral contract; repository,
policy, and UI-core code cannot branch on native collector or candidate-specific
fields. Conformance tests add and remove the reference adapter without modifying
those consumers.

### Migration parent/child state machine

```text
planned -> preflight -> awaiting-approval -> source-fencing -> source-fenced
   -> target-preparing -> target-starting -> target-verified -> route-switching
   -> authority-committed -> canonical-committed -> verifying -> succeeded

before authority commit failure -> recover/remove target -> reopen source
after authority commit failure  -> keep source fenced -> recover target
                                -> explicit rollback: fence target first

lost acknowledgement at any authority-changing edge -> indeterminate
  -> inspect durable parent, source fence, target evidence, route, authority epoch
  -> choose one reviewed forward-recovery or rollback transition
```

The parent owns one monotonically increasing authority epoch. Source and target
child operations are idempotent for `(migration_id, phase, authority_epoch)` and
reject role/domain mismatch. The workload-wide exclusive lock prevents restart,
backup, access, and any second migration from racing the parent. Crash fixtures
cover before/after source fence, target creation/start, route switch, authority
commit, canonical commit, verification, and rollback fence.

### Session diagnosis contract

Session lookup is a read path. It must not revoke identity-wide sessions when an
operator file, proxy header, or trusted-login check is temporarily unavailable.
Explicit operator disable/revocation owns that mutation. PR 2A first adds the
side-effect regression and stable safe reason codes, then PR 2B changes only the
proven failing boundary.

### Firewall policy flow

```text
canonical projects/relationships
  -> pure allowed-pair model
  -> preflight resolves project networks to live interfaces
  -> reject unknown/duplicate/stale mapping
  -> preview digest(model + mapping + current table)
  -> backup -> atomic nft apply -> installed equality -> exhaustive live probes
  -> persist -> reboot verify
  failure anywhere -> restore root-owned backup -> equality/probe verification
```

### Test coverage map

```text
PR 1  policy renderer: own-project allow, all directed cross-project denies,
      unknown/reused interface, egress pivot, atomic apply failure, rollback,
      persisted/live/reboot equality                              [unit+server]
PR 2  cookie/origin/identity/store matrix, destructive-read regression,
      reload/browser restart, expiry/revocation/restart           [unit+browser]
D1    schema migration/rollback, page protocol, atomic runs, pruning,
      bounds, version skew, concurrency, crash/restart,
      repeated/shuffled-input deterministic golden vectors        [unit+integration]
D2+   each source happy/empty/stale/fail/timeout/oversize/secret fixture,
      stopped resources, duplicate native IDs                    [unit+server]
D5/D6 reconciliation conflicts, partial completeness, blockers,
      reload/deep-link/a11y states                                [unit+browser]
M1-M4 parent transitions, exclusive locks, dual authorization, every crash edge,
      indeterminate reconciliation, pilot and rollback            [unit+integration+server]
5A/B  semantic states, dialog/panel keyboard behavior, responsive journeys,
      asset family and no-JS fail-closed                          [unit+browser]
6     exact standard discovery on Ubuntu/macOS, explicit Linux skips,
      controlled root/non-root contract                           [CI]
7     checklist-to-evidence parity and no code-only closure        [audit]
all   same explicit input repeated 100 times is byte-identical;
      shuffled source order and scheduling preserve output/digest;
      injected time changes only declared freshness outcomes;
      dependency/static audit finds no AI path in Argus core;
      absence audit proves the current core has no AI/model endpoint
      or advisory import/watcher/shared-write path; this inspects
      existing code and creates no advisory fixture or parser       [unit+CI+static]
```

The hostile tests are: forged collector pages containing secret-like fields;
stale bridge mapping attempting to gain access; simultaneous migration and
restart; loss of coordinator acknowledgement after authority switch; and an
operator-file read failure during session restoration. Every regression receives
a named test before its implementation. Deterministic fixture replay also covers
shuffled pages, locale/timezone changes, Unicode normalization, duplicate records,
equal timestamps, subprocess-output ordering, and simultaneous source completion.
The 100-run criterion replays captured immutable fixtures; it does not require a
changing live server to return identical observations.

The separately authorized C/AI ADR—not Approach A—must add hostile candidate
tests for forged absence/capacity/health, stale/removal/conflicting identity,
POST/proxy/action links, active HTML/Markdown/URIs, deletion, and corruption.
Those tests must prove no permission, authority-changing native preview digest,
Argus state, or acceptance evidence changes. No current test creates the deferred
advisory import, parser, renderer, or fixture surface.

### Performance and storage budgets

- Refresh returns `202` immediately; it does not hold the HTTP request for the
  current synchronous 30-second subprocess.
- Default source concurrency is conservative and configurable; no unbounded
  thread/process fan-out.
- Source output is rejected before unbounded parse/allocation. Pagination is
  bounded below the IPC frame ceiling.
- SQLite uses indexed source/run/identity/reconciliation lookups and atomic
  transactions. D1 sets byte/run retention from measured estate size and proves
  pruning does not remove the current or required rollback snapshots.
- Host metrics and estate refresh have separate timers, processes, files, and
  failure domains.

### Mixed-version deployment and rollback

```text
backup database/config -> deploy repository schema reader/writer
  -> verify current + previous envelope support
  -> deploy one collector source -> fixture/live compare -> expand collectors
  -> deploy reconciliation/API -> deploy completeness UI
  -> migration design schema -> eligibility gate -> coordinator/pilot
```

Every collector PR contains unit install/remove, identity/socket permission,
health check, upgrade, and rollback steps. The central reader accepts current and
previous versions during rolling deployment and fails closed on newer versions.
Database migrations back up first, validate forward and restart behavior, name
the last safe rollback point, and provide forward repair after that point.

### PR/worktree execution lanes

| Lane | Sequence | Shared modules |
| --- | --- | --- |
| Security | PR 1 only, then server proof | bootstrap/firewall/tests |
| Test foundation | PR 6A after PR 1, then PR 6B | CI/tests/docs/CLI |
| Session | PR 2A -> PR 2B | sessions/API/dashboard |
| Design | PR 5A prototypes/assets -> PR 5B after stable response contracts | dashboard/style/assets |
| Discovery | D1a repository -> D1b protocol/scheduler -> D2 rootful -> D2 rootless -> D3/D4 -> D5 -> D6 | state/collectors/API |
| Migration | M1 design -> M2 eligibility -> M3a coordinator schema/crash fixtures -> M3b pilot adapters -> M4 -> M5 | operations/agents/migration |
| Closeout | PR 7 audit -> independent failure-driven fixes | docs/issues |

After PR 1, PR 6A, and PR 6B, session, PR 5A, and D1 design work can proceed in separate
worktrees. Migration waits for the D5 freshness contract and M2 eligibility.
Dashboard implementation waits for approved prototypes and stable D5/M1 response
contracts. Shared API/dashboard/state modules are conflict flags and merge
sequentially.

### Engineering completion summary

- Scope: full reviewed program retained, decomposed into independently useful PRs.
- Architecture findings: six P1, four P2; all folded into the plan.
- Critical failure gaps after amendments: zero known.
- Test gaps after amendments: zero planned paths without a named test class.
- Performance: bounded scheduler, paged transport, atomic snapshots, separate metrics.
- Security: canonical authorization, collector/mutator separation, exhaustive probes.
- Outside voice: independent engineering review completed; Codex CLI unavailable.
- Unresolved engineering decisions: zero; live measurements fill declared budgets,
  not architectural choices.

## Developer Experience Review: Maintainer and Operator Contract

Argus is a private platform, CLI suite, web operator console, and documentation
set—not a public SDK. The current repository DX rates 4/10: it has extensive
safety documentation and `--help` coverage, but the primary docs still describe
an early P0 HTTP deployment, documented commands diverge from installed links,
plain `unittest discover` runs zero tests, and public command/error/upgrade
contracts are inconsistent. This contract raises the reviewed plan to 9/10;
live fresh-clone and server boomerang testing supplies the last point.

### Target personas

| Persona | Context | Tolerance | Needs first |
| --- | --- | --- | --- |
| Owner-operator | Checks Argus from phone/laptop on the tailnet and responds to exceptions | seconds for orientation; deliberate friction only at mutation | private route, session/completeness, exception, next safe action |
| Server operator | Uses an approved `oreochiserver` session to preflight, apply, verify, or recover | accepts multi-step safety gates but not ambiguity | privilege label, exact preview, backup, reason code, evidence and recovery command |
| Repository contributor | Changes Python/shell/docs on Linux, macOS, or WSL through PRs | under five minutes to trustworthy local feedback | one setup-free check, supported versions, repo map, exact CI parity |

Golden paths label every command `LOCAL READ-ONLY`, `SERVER READ-ONLY`, or
`SERVER MUTATION`. `sudo` appears only on the final reviewed apply/rollback step,
never on local validation, preview, status, or plan generation.

### First safe validation and magical moments

From a fresh clone with a supported Python:

```text
1. Read README current-state summary and prerequisites       <= 1 minute
2. Run ./scripts/argus-check                                <= 4 minutes
3. See one stable result: PASS or problem + cause + next action
```

`argus-check` is standard-library-only and runs the canonical unit discovery,
compile checks, manifest/schema validation, offline smoke, docs/command parity,
and generated/secret-safe diff checks. CI invokes this same entry point rather
than duplicating shell logic. Its successful output names test count, explicit
skip count/reasons, and the safe next step; failures preserve completed results.

The contributor magical moment is one command proving the repository is safe to
change. The operator magical moment is `argus estate refresh` returning a run ID,
last-known-good evidence, exact `fresh / required` coverage, gaps, and which
actions those gaps block—without granting privileged sockets or scanning secrets.

### Stable public CLI

One thin dispatcher becomes the documented surface:

```text
argus dashboard url
argus estate status|refresh|coverage
argus workload list|show <id>
argus workload move preview|preflight|apply|status|rollback <id>
argus operation show|recover <operation-id>
argus doctor [--json]
argus check [--json]
```

Noun/verb grammar is consistent, IDs are positional where unambiguous, and
status/preview is the default safe posture. Milestone-prefixed scripts remain
internal compatibility entry points until individually deprecated; they do not
appear in the current operator quick path. Compatibility emits a deprecation
notice and exact replacement before removal.

Every public command's `--help` states purpose, privilege class, prerequisites,
side effects, default read-only behavior, output/evidence location, examples,
and recovery/status command. `argus workload move` derives eligible targets and
does not hard-code the five retained workload IDs.

### Human and machine error contract

- Human mode: stdout is result data; stderr is a concise diagnostic containing
  problem, cause, stable code, and exact next action.
- JSON mode: one versioned envelope on stdout:
  `{ok,error:{code,message,nextAction,evidenceId,retrySafe,authority},data}`;
  absent optional fields are omitted and secrets/private raw evidence are never
  emitted.
- Exit classes: `0` success, `1` internal/unclassified failure, `2` invocation,
  `3` safe refusal/precondition, `4` unavailable/transient, `5`
  indeterminate/recovery-required.
- Every expected failure uses a documented stable reason code; the internal
  class is treated as a bug and still provides a safe evidence ID/next action.
- Migration output always names migration/journal ID, current authority and
  phase, whether retry is safe, and the exact status or recovery command.

CLI contract tests cover help, happy path, invalid invocation, missing
prerequisite, policy refusal, unavailable dependency, JSON parity, interrupted
operation, indeterminate authority, compatibility/deprecation, and documented
recovery.

### Current documentation architecture

```text
README
  -> OPERATOR START HERE
       dashboard URL discovery, daily estate status, exception investigation,
       server preflight/apply/recovery, current runbooks
  -> CONTRIBUTOR START HERE
       supported Python/OS, argus-check, repo map, change/PR/CI loop
  -> ARCHITECTURE
       current system model, trust boundaries, ADRs, schemas/protocols
  -> HISTORICAL DELIVERY RECORD
       phase plans/closeouts retained with status and superseded-by links
```

PR 0B declares the M0-M4 `argus` integration-line instructions historical and
sets every remediation child PR to base and target `main`; the PR guard asserts
that base. README, OPERATIONS, ACCEPTANCE, DASHBOARD_AND_API, and architecture
entry points are updated together. Current docs discover the effective private
dashboard URL with `argus dashboard url` rather than hard-coding a deployment-
specific port. Historical endpoint evidence stays labeled historical.

A docs checker validates internal links, current endpoint literals, privilege
labels, public command references, installed/documented parity, code examples,
and historical/superseded markers. Audit history remains intact.

### Install, upgrade, and rollback ergonomics

Each collector/coordinator/unit slice provides idempotent
`plan`, `install|upgrade`, `status`, and `rollback|remove` behavior through the
stable dispatcher or one scoped installer. Status never mutates.

`argus doctor --json` reports safe versions and mismatches: repository revision,
deployed revision, database schema, collector protocols, unit health, last
completed collection, last safe rollback point, and next action. It never prints
credentials, private topology, raw command lines, or source payloads.

Acceptance covers clean install, repeated install, N-1 upgrade, mixed current/
previous collector versions, interrupted upgrade, restart, status, rollback,
removal, and the point after which forward repair replaces rollback.

### CI and platform contract

- PR 6A makes plain `python3 -m unittest discover` collect the full suite and
  makes `argus-check` the local/CI source of truth.
- Supported Python versions are derived from `oreochiserver` plus the maintained
  current version, then named in README and CI.
- CI runs the lowest/current supported Python on Ubuntu and maintained macOS;
  platform skips are explicit with counted reasons.
- Linux/systemd/socket/root-bound behavior remains a separate Ubuntu and
  `oreochiserver` acceptance lane. macOS green is portability evidence, never
  substitute server evidence.
- The public-command installer and docs are tested bidirectionally: every
  documented command is installed and every installed public command is
  documented.

### Sanitized acceptance evidence

Every child issue/PR receives a versioned evidence summary with probe ID/version,
environment class (not private topology), timestamps, threshold, result, and
sanitized evidence reference. A read-only helper emits JSON and Markdown and
compares the same before/after probe. Raw runtime evidence remains ignored and
server-local; public PRs contain allowlisted summaries only.

### Competitive boundary

Official current documentation shows Portainer emphasizing multi-environment
management through sockets/APIs/agents, Beszel offering copyable multi-method
agent installation, and Cockpit bridging an authenticated Linux session to
system APIs. Argus does not chase their breadth. It borrows clear onboarding,
status, and recovery patterns while retaining its differentiation: no central
raw Docker sockets, configured-source truth, private trust-domain policy,
canonical/observed/effective reconciliation, typed high-risk operations, and
auditable rollback evidence.

### DX scorecard

| Dimension | Current | Planned | Resolution |
| --- | ---: | ---: | --- |
| First safe validation | 3/10 | 9/10 | one `argus-check`, under five minutes, local/CI parity |
| CLI/API design | 4/10 | 9/10 | stable dispatcher, read-only defaults, progressive subcommands |
| Errors/debugging | 4/10 | 9/10 | reason/exit/envelope contract and exact recovery |
| Documentation | 3/10 | 9/10 | three current paths plus labeled historical record |
| Upgrade/migration | 5/10 | 9/10 | idempotent plan/status/upgrade/rollback and doctor compatibility report |
| Dev environment | 5/10 | 9/10 | supported Python/OS matrix and explicit server-only lane |
| Community/ecosystem | 6/10 | 8/10 | private single-owner scope; clear contributor/issue/PR path, no public community program |
| Measurement | 4/10 | 9/10 | sanitized versioned before/after evidence helper |

TTHW target is **under five minutes to full safe local validation**, not a
marketing hello world. Mode is DX polish. No public SDK, plugin marketplace,
hosted sandbox, telemetry service, package registry, or public free tier is in
scope.

The independent DX voice found two P0, six P1, and two P2 gaps; all are
incorporated above. The Codex CLI voice remains unavailable. Unresolved DX
decisions: zero.

## Cross-Phase Review Synthesis

### Design litmus

| Check | Result after plan amendments |
| --- | --- |
| Product unmistakable in first screen | yes: Argus identity, private state, completeness, exceptions |
| One strong visual anchor | yes: actionable exception/completeness workspace |
| Understandable by scanning headings | yes: Safety, Coverage, Workloads, Operations |
| One job per section | yes |
| Cards are necessary | yes only where a record/interaction owns independent state; decorative card wall removed |
| Motion improves hierarchy | yes only for state transition/progress; reduced motion supported |
| Premium without decorative shadows/glow | yes; ornamental sci-fi language removed |

### Developer empathy narrative

> I maintain one private server, and I arrive because something changed—not to
> admire a dashboard. From a fresh checkout I want one command to tell me whether
> my change is safe. On the server I want every command labeled read-only or
> mutation, and every refusal to tell me why and what to run next. In the browser
> I need to know whether the estate view is complete before I trust it. If a move
> fails, I do not want a stack trace or a vague red badge; I need the journal ID,
> current authority, whether retry is safe, and the exact recovery command. I am
> willing to type a confirmation and use step-up at the authority boundary. I am
> not willing to hunt through milestone-era runbooks, guess which command is
> installed, or wonder whether a refresh silently skipped half the server.

### DX implementation checklist

- [ ] Fresh clone to full safe local validation in under five minutes.
- [ ] `argus-check` is the local/CI source of truth after PR 6A.
- [ ] Every public command is installed, documented, privilege-labeled, and has
      human/JSON help, failure, refusal, unavailable, and recovery tests.
- [ ] Every expected error provides stable code, problem, cause, and next action.
- [ ] Current docs use route discovery and contain no unlabeled retired endpoint.
- [ ] Operator, contributor, architecture, and historical paths are distinct.
- [ ] Install/upgrade/status/rollback is idempotent and rehearsed from N-1.
- [ ] Doctor reports revision/schema/protocol mismatch and last safe recovery.
- [ ] Sanitized before/after evidence uses the versioned acceptance schema.
- [ ] Server-only evidence is never replaced by macOS/local success.

### Dual-voice consensus

Codex CLI review was attempted twice in the CEO phase and returned no review
body, so all Codex columns are `N/A` and no false cross-model consensus is
claimed. Independent subagents and the primary review converged after amendments.

| Phase | Independent voice | Primary review | Result |
| --- | --- | --- | --- |
| CEO | 12 initial findings plus A/C amendment review; final PASS 9.5/10 | A now, C as separately gated option | clear |
| Design | 2 P0 plus 12 lower-severity findings | same exceptions-first/state/accessibility direction | clear at 9/10; rendered QA required |
| Engineering | 10 initial findings plus deterministic-boundary amendment review; final PASS 9.5/10 | same canonical-policy/collector/migration architecture | clear |
| DX | initial gaps plus deterministic replay/advisory-scope amendment review; final PASS 9/10 | same CLI/docs/check/upgrade contract | clear |

### Cross-phase themes

1. **Truth before breadth:** configured sources, last-known-good snapshots, and
   explicit gaps are more valuable than an unverifiable scan claim.
2. **Policy before observation:** runtime evidence resolves identities and proves
   state but never creates authorization.
3. **Separate read and write power:** collectors, mutation agents, sessions,
   preview, confirmation, authority, and canonical placement remain distinct.
4. **Durability at authority boundaries:** firewall apply, snapshot commit,
   session revocation, migration fencing, and rollback all need explicit atomic
   state and recovery.
5. **One operator language:** UI, CLI, API, logs, docs, tests, and evidence share
   stable states/reason codes without exposing secrets.
6. **Foundations before breadth:** workflow/evidence truth, security, canonical
   tests, and stable CLI precede collector and migration expansion.
7. **Deterministic kernel, replaceable shell:** Approach A establishes stable
   evidence/control contracts; a future Approach C may replace commodity
   management surfaces but receives no policy or mutation authority.
8. **No AI in the trust path:** core outcomes are reproducible and inspectable;
   any future model is isolated, read-only, untrusted, and advisory-only.

### Decision audit trail

| Decision | Source | Auto-decision principle | Result |
| --- | --- | --- | --- |
| Use staged evidence platform now | premise gate | operator selected A as valid current path | accepted |
| Treat C as the strategic horizon | operator override | preserve the stronger long-term option without delaying fixes or collapsing trust boundaries | accepted; separately gated |
| Require deterministic, AI-free control core | operator override | reproducibility and auditability are product invariants | accepted |
| Isolate any future AI as read-only advice | operator override/security | model output must never gain evidence, policy, or mutation authority | accepted; future-only |
| Split safety/reliability/platform clocks | CEO | completeness without delaying containment | accepted |
| Replace “whole server” with configured-estate completeness | CEO | truthful, testable outcome | accepted |
| Keep broad sources as independently accepted child slices | CEO/Eng | complete scope with reversible PRs | accepted |
| Build-versus-integrate per discovery contract | CEO | reuse commodity plumbing where trust fit allows | accepted |
| Separate collector and mutation-agent sockets | Eng | preserve accepted D005 boundary | accepted |
| Atomic paged observation runs | Eng | explicit, bounded, crash-safe state | accepted |
| Parent/child two-domain migration coordinator | Eng | current one-domain ledger cannot safely coordinate a move | accepted |
| Zero cross-project exceptions by default | Eng | least privilege and non-waivable isolation | accepted |
| Exceptions-first overview and route-backed detail | Design | daily operator decision hierarchy | accepted |
| Real modal only for authority-changing confirmation | Design | accessible deliberate friction | accepted |
| Stable `argus` dispatcher and one `argus-check` | DX | fight uncertainty and prevent local/CI drift | accepted |
| Current docs plus labeled historical record | DX | preserve audit history without misleading operators | accepted |
| Defer public exposure, multi-host, universal stateful adapters | all | outside confirmed blast radius | deferred |

### Aggregated implementation tasks

- [ ] **T1 (P0)** — Land this reviewed plan and prerequisite workflow/evidence
  truth through PR 0/0B; create/link every child issue.
- [ ] **T2 (P0)** — Replace wildcard sandbox forwarding with canonical,
  least-privilege, atomic firewall policy and exhaustive live proof.
- [ ] **T3 (P1)** — Establish canonical unittest discovery, `argus-check`, and
  Ubuntu/macOS CI before broad implementation.
- [ ] **T4 (P1)** — Reproduce session loss, prove GET lookup side-effect-free,
  then fix only the confirmed boundary with browser/server evidence.
- [ ] **T5 (P1)** — Produce Argus identity assets, DESIGN.md, semantic states,
  fixture-backed wireframes, and measured operator journeys.
- [ ] **T6 (P1)** — Implement source registry/atomic repository, authenticated
  paged collector protocol, bounded scheduler, and rootful/rootless collectors.
- [ ] **T7 (P1)** — Add host/source slices, reconciliation, completeness API/UI,
  secret-hostile fixtures, retention, version skew, and rollback.
- [ ] **T8 (P1)** — Land stable CLI/docs/error/upgrade/doctor contracts and
  installed/documented parity.
- [ ] **T9 (P1)** — Design parent/child migration/authority model, select a safe
  pilot from fresh evidence, implement crash fixtures and the minimum kernel.
- [ ] **T10 (P1)** — Execute and reverse the stateless pilot with sanitized
  server evidence before any generalization or relocation UI.
- [ ] **T11 (P1)** — Complete the overview/detail redesign and live visual,
  responsive, keyboard, screen-reader, contrast, and reduced-motion QA.
- [ ] **T12 (P1)** — Audit open P0 trackers against source, CI, and server
  acceptance; close only proven items and create separate fixes for failures.
- [ ] **T13 (all PRs)** — Run the reproduce/test/implement/adversarial-review/fix/
  CI/server-evidence loop until no actionable P0/P1 finding remains.
- [ ] **T14 (PR 6A and later core PRs)** — Add deterministic golden vectors,
  shuffled-order and repeated-run checks, explicit clock injection, and an
  AI-core dependency/endpoint audit; reject heuristic conflict resolution.
- [ ] **T15 (deferred decision)** — After D1/D5 stabilize, D6/PR 5B land, and
  post-A operator/operating-cost baselines are recorded, run the scored Approach
  C eligibility gate and, only in a separate ADR/issue/PR, prove one-way private
  read-only integration, conformance, and clean removal.

Per-phase JSONL task artifacts were not written because `jq` is unavailable;
the skill explicitly forbids hand-rolled JSONL. The aggregated tasks above are
the authoritative implementation list.

## Delivery Sequence

### PR 0: Reviewed remediation plan

Scope:

- This document only.
- Record the confirmed problem set, dependencies, implementation order,
  acceptance evidence, and rollback boundaries.
- Link the PR to `#197`; create one child issue for each untracked implementation
  slice after operator approval.

Acceptance:

- CEO, design, engineering, and developer-experience critiques are incorporated.
- The operator explicitly confirms the implementation scope before code changes.
- No server or product state changes.

### PR 0B: Workflow, evidence, and current documentation truth

Scope:

- Declare the former M0-M4 `argus` integration-line workflow historical and set
  every remediation branch to base and target current `main`.
- Add the base-branch assertion to the PR guard.
- Ship the minimal read-only `argus dashboard url` dispatcher path and its
  installer/help/JSON tests so the updated docs name an existing command. PR 6B
  expands the same dispatcher without changing this contract.
- Replace stale current-state HTTP/`:8088` guidance with deployment-neutral
  private URL discovery instructions; preserve historical evidence as labeled.
- Add Operator, Contributor, Architecture, and Historical paths to the README
  and mark superseded phase documents without deleting audit history.
- Define the versioned allowlisted acceptance-summary schema, PR-template table,
  storage/redaction rules, and minimal read-only JSON/Markdown emitter required
  to record PR 1's three-run baseline before any server mutation.

Acceptance:

- A new contributor can identify the correct base/target branch unambiguously.
- No current operator path hard-codes the retired dashboard route.
- Historical documents remain accessible and visibly historical.
- Every command named by PR 0B exists and passes help/human/JSON contract tests.
- PR 1 can record a sanitized before/after evidence summary without inventing a
  new format or copying raw server evidence into Git/GitHub.

### PR 1: Default-deny cross-project sandbox networking (`#270`)

Scope:

- Replace wildcard bridge-to-bridge forwarding with rules generated from
  canonical same-project network relationships. Resolve canonical identities
  to live interfaces only during preflight; observations never grant access.
- Permit cross-project traffic only from an explicit, typed relationship.
- PR 1 defaults to zero cross-project exceptions. A topology relationship never
  grants connectivity. If a current dependency is proven, a separate reviewed
  connectivity policy names source project/network, target service/network,
  direction, protocol, destination port, owner, reason, and optional expiry;
  rendering remains least-privilege L3/L4, never bridge-pair acceptance.
- Preserve declared workload egress without allowing another project to pivot
  through the egress-enabled bridge.
- Extend the verifier to probe own-project success and every cross-project
  denial in both active domains.
- Preserve and verify firewall rollback from the root-owned backup.
- Bind preview/apply to a digest of canonical relationships plus the resolved
  runtime mapping. Reject unknown, duplicated, stale, or changed mappings and
  leave every unrecognized bridge denied.
- Extract one pure firewall-policy renderer used by bootstrap and remediation.
  Apply the nftables table atomically through a firewall-only
  plan/apply/verify/rollback path; do not rerun the full sandbox bootstrap.

Acceptance:

- No `iifname "br-*" oifname "br-*" accept` rule remains.
- Every current multi-service project retains intra-project communication.
- Every unrelated directed project-network pair fails closed. Bounded live
  probes run concurrently and remain exhaustive at every current estate size.
- Canonical relationships, rendered rules, installed rules, and enumerated live
  bridges match exactly; unknown bridges fail acceptance and remain denied.
- Negative tests cover wrong direction, other ports/protocols, unrelated target
  services, expiry, and connectivity-policy removal.
- Hastur's declared inner DNS/TLS rules remain byte-for-byte scoped to its
  resolved bridge, and no other project can pivot through them. The 2026-08-03
  baseline confirmed outbound TCP was already blocked by the host UID guard;
  live egress remains issue `#267` and is not silently broadened in PR 1.
- Persisted rules equal live rules after apply and after reboot.
- Full server smoke reports zero failures and zero warnings.

### PR 2A: Operator session boundary diagnosis

Scope:

- Reproduce reload loss through the real Tailscale HTTPS origin and capture only
  safe status evidence: cookie presence flags, response status, identity-header
  presence flag, and session lookup result. Never log tokens or identities.
- Produce a decision table identifying the confirmed failing boundary; do not
  change session lifetime or authentication semantics.
- Prove every `GET` and session-lookup path is side-effect-free except for the
  documented last-seen update. Specifically test the current destructive-read
  hypothesis: a transient operator-file or trusted-identity lookup failure must
  not invoke identity-wide session revocation.
- Add safe restoration reason codes: `identity-missing`, `operator-disabled`,
  `cookie-missing`, `session-not-found`, `session-expired`, `session-revoked`,
  and `session-store-unavailable`.

Acceptance:

- The real Tailscale HTTPS reload failure is reproduced or the issue records
  exhaustive negative evidence for every origin/proxy/cookie/session boundary.
- Evidence contains status flags and reason codes only; never credentials,
  tokens, cookies, CSRF values, identities, or private request headers.
- The diagnosis names the narrow PR 2B regression and acceptance tests.
- Repeated `GET /api/session` calls do not change session validity, revocation,
  or ownership state.

### PR 2B: Confirmed operator session restoration fix

Scope:

- Fix only the boundary proven by PR 2A rather than extending session lifetime
  blindly.
- Make session restoration an explicit startup state: checking,
  authenticated, unauthenticated, expired, and unavailable.
- Ensure a transient restoration failure does not silently present as logout.
- Keep Secure, HttpOnly, SameSite, CSRF, idle timeout, absolute timeout,
  revocation, and step-up protections.

Acceptance:

- Authenticate once, reload repeatedly, and retain the same session until idle
  or absolute expiry.
- Browser restart within the allowed lifetime restores the session.
- Wrong origin, missing identity, revoked session, expired session, missing CSRF,
  and API restart cases fail closed with actionable UI state.
- Session and CSRF values never appear in logs, tests, Git, or browser storage.

### Epic D: Configured-estate read-only discovery

Scope:

- Introduce normalized observation records with source, type, stable observed
  ID, timestamp, provenance, and redacted attributes.
- Define a versioned source registry. Each source declares stable host/source
  identity, owner, scope, privilege, freshness SLO, schema version, and current
  state; dashboard completeness is computed only against this registry.
- Validate expected sources derived from canonical trust domains plus reviewed
  host-source configuration. An omitted expected source becomes a visible
  `configuration-gap`; zero sources is `not-configured`, never 100%. Exclusion
  requires reviewed owner, reason, and expiry and stays visible.
- Store source state and observations in SQLite behind the existing repository
  boundary. D1 defines `sources`, `collection_runs`, `observations`, and
  `reconciliation_links`; observation identity is source ID + resource kind +
  native ID + collection run, never a globally assumed native ID.
- Add typed read-only collectors incrementally, starting with sources that
  answer an operator decision, for:
  - rootful Docker and every configured rootless trust-domain daemon;
  - running and stopped containers, Compose labels, images, networks, volumes,
    mounts, health, and published ports;
  - system and enabled user systemd services/timers;
  - system and user cron references;
  - running processes and listening sockets;
  - Caddy routes, Tailscale Serve/Funnel state, cloudflared state;
  - repositories, Compose files, and known manifests only under explicitly
    configured roots.
- Run privileged or domain-specific collection through narrow local collectors.
  The central API receives typed redacted observations and never receives a raw
  Docker socket or arbitrary command surface.
- Give every domain a collector process/socket separate from its mutation agent.
  Collectors have no operation ledger, issuer, replay store, signing key, or
  mutation method; the domain-agent socket remains operation-ID-only.
- Pin each source to an exact socket path, expected UID/GID, mode, host, and
  domain. Before accepting a page, verify parent ownership, socket type/mode/
  owner, Unix peer credentials, and equality between envelope IDs and registry
  binding. Collector payload remains untrusted schema input after peer checks.
- Transfer bounded pages containing protocol version, run ID, source ID,
  sequence number, record/byte counts, and a running digest. A validated terminal
  page is required before commit. Reject missing, duplicated, reordered,
  replayed, oversized, or digest-mismatched pages.
- Collect independent sources concurrently with a configurable worker cap,
  individual timeouts and output/record/byte ceilings, plus one global refresh
  deadline. A timed-out source cannot block completed sources. Metrics remain on
  their independent schedule.
- Enforce per-source field allowlists and minimization at the collector boundary.
  Do not collect raw command lines, environments, file contents, Git remotes, or
  unconstrained filesystem candidates; repository and manifest discovery is
  restricted to configured roots.
- Reconcile observations to known projects/workloads without turning observation
  into canonical truth or automatic admission.
- Report collection gaps and stale sources explicitly.

Acceptance:

- A fixture matrix covers every source, empty/error/stale states, stopped
  resources, duplicate identifiers, and partial collector failure.
- Server comparison accounts for every configured Docker daemon and identifies
  unregistered projects, orphaned schedules, and non-container services.
- Refresh is idempotent, read-only, bounded, and never prints secrets.
- Partial failure returns useful results plus source-specific gaps; it never
  claims the estate is complete.
- Ingest into a non-current run, validate it, then atomically mark it current. A
  partial or failed run records its gap but never replaces the last completed
  snapshot. Define retention, pruning, and database-size ceilings.
- Support the current and previous collector envelope version during rolling
  deployment and reject unknown future versions. Deploy repository support,
  collectors, reconciliation/API, then completeness UI.
- Outcome checks track refresh duration, fresh/configured-source ratio, unknown
  and conflicting observations, and false-complete incidents. Source expansion
  pauses if early slices do not improve operator confidence.
- Tests cover multi-page sources, mid-run disconnect, replay, reordering,
  malformed/oversized output, timeout, concurrent sources, run supersession,
  schema migration, restart recovery, pruning, and safe database rollback.
- Tests also cover socket replacement, wrong UID, wrong source/host ID,
  cross-domain impersonation, empty registry, omitted canonical domain,
  duplicate source, expired exclusion, and source removal.

### Epic M: Migration kernel and pilot relocation between trust domains

Scope:

- Add `migration.preview`, `migration.preflight`, `migration.cutover`, and
  `migration.rollback` as durable typed operations.
- Add one durable parent migration record containing source/target domains,
  canonical and policy revisions, observation snapshot IDs, authority epoch,
  parent phase, and separately authorized source, target, and rollback child
  operation IDs.
- A central coordinator advances the parent state machine and dispatches child
  operations to each domain agent. Every child rechecks its domain role,
  migration ID, authority epoch, canonical/policy revisions, preview digest,
  and local fence state.
- Accept a workload ID and an eligible target trust domain. Derive source
  placement from canonical state; reject same-domain, unknown, incompatible,
  occupied, or policy-denied targets.
- Generalize only the durable journal, preview/preflight, target eligibility,
  authority fencing, verification, and rollback primitives needed by one real
  stateless pilot. Keep workload-specific backup, restore, health, credential,
  egress, route, and rollback contracts explicit.
- Preserve Compose project names and prevent simultaneous source and target
  writers across crashes and reboots.
- Extend the workload-wide exclusive lock to every migration phase and every
  other mutation. Store runtime authority separately from desired canonical
  placement; update canonical placement only after source fencing, target
  verification, route switching, and authority commit are durable.
- Add a dashboard relocation flow with source/target summary, blockers, storage
  impact, expected downtime, route impact, health gates, exact confirmation,
  progress, and rollback state.

Acceptance:

- The selected stateless pilot passes source-to-target cutover and a rehearsed
  rollback. A later bidirectional acceptance run is required only when fresh
  evidence proves an eligible same-realm pair in both directions.
- Stateful relocation remains blocked without a verified workload-specific
  backup and isolated restore contract.
- Crash injection at every authority boundary proves at most one writer can be
  authoritative.
- Lost acknowledgements become `indeterminate` and reconcile from durable
  source/target evidence; authority-changing child operations are never blindly
  redispatched.
- Same-domain, cross-realm, stale preview, unavailable agent, target collision,
  missing capacity, missing route, and incomplete observation cases fail closed.
- Server evidence proves Compose identity, data fingerprints, private routes,
  and health before and after a pilot relocation.
- Generalization beyond the pilot requires a second materially different move
  and evidence identifying which behavior is truly common.

### PR 5A: Argus identity and immediate density relief

Scope:

- Add the local Argus SVG mark and favicon generated from one source asset.
- Remove redundant always-visible metadata and place existing secondary detail
  behind the current inspector without freezing new API contracts.
- Produce fixture-backed overview/detail and source-completeness state
  prototypes before Epic D or Epic M response schemas freeze.

Acceptance:

- Browser tab, bookmark, and installed shortcut show the Argus icon.
- Routine workload health and placement remain visible with fewer simultaneous
  controls; no dangerous operation becomes easier to trigger accidentally.
- The approved prototypes define required summary fields and all loading,
  empty, error, partial, stale, and success states for later API contracts.

### PR 5B: Dashboard information architecture

Scope:

- Keep the overview focused on host health, exposure, domain health, discovery
  completeness, and workload alerts.
- Make workload rows/cards show identity, placement, health, access, freshness,
  and the primary action only.
- Move evidence, history, migration, backup, restart, and access controls into a
  keyboard-accessible detail panel or dedicated workload view.
- Separate authentication state from the generic Admin Mode toggle.
- Preserve responsive behavior, visible focus, touch targets, contrast,
  reduced-motion behavior, loading/empty/error/partial/success states, and
  no-JavaScript-safe private content boundaries.

Acceptance:

- Desktop and mobile visual QA covers every state and all six workloads.
- The top bar has no more than one primary action plus compact utilities.
- Routine status can be read without opening details; dangerous operations are
  never one accidental click away.
- Keyboard-only and screen-reader labels cover navigation, details, dialogs,
  progress, and errors.

### PR 6A: Test portability and standard discovery (`#264`)

Scope:

- Make plain `python3 -m unittest discover` collect the complete suite.
- Add `scripts/argus-check` as the standard-library-only local/CI entry point
  for tests, compile checks, manifests, offline smoke, docs/command parity, and
  safe diff/generated-artifact checks.
- Add the machine-readable Argus-core boundary policy and own the deterministic
  replay harness, locked dependency/SBOM audit, declared-endpoint and outbound-
  network-policy audit, dynamic-load/model-SDK exclusion, and CI integration.
- Define an internal replay bundle containing schema/transform version, Argus
  revision, supported Python/runtime version, canonical/config/source-page
  digests, explicit clock, expected canonical-output/reason/permitted-action/
  preview digests, and evidence ID. Raw bundles stay local and follow retention/
  redaction policy; only the sanitized digest summary may enter a PR.
- Make `argus-check` verify replay bundles and emit expected/actual digests with
  stable `replay-ok`, `replay-mismatch`, `replay-bundle-incomplete`, and
  `replay-version-unsupported` results plus an exact next action. An unsupported
  historical transform is never reported as nondeterminism. Byte identity is
  required across every supported Python/OS lane declared by the boundary policy;
  otherwise the runtime is not supported until the mismatch is resolved.
- Record `coreBoundaryPolicyVersion`, audit version/result, dependency/SBOM
  digest, endpoint/network-policy digest, replay bundle/output digests, and Argus
  revision in sanitized check/doctor evidence. Emit `core-boundary-violation` for
  a boundary failure; never emit raw private observations.
- Mark Linux-only process, socket, and identity tests explicitly.
- Keep Linux CI and `oreochiserver` coverage unchanged.
- Document non-root execution and platform-specific skips.

Acceptance:

- Standard unittest discovery passes on Linux CI.
- macOS produces green results with explicit Linux-only skips rather than false
  failures.
- Running the suite as root fails early with an actionable explanation when a
  non-root contract is required.
- A fresh clone reaches a complete safe local check in under five minutes with
  one documented command, and CI invokes the same command.
- Fixture replay is byte-identical on every supported lane, and version,
  incomplete-bundle, mismatch, and core-boundary failures are distinguishable.

Before PR 6A exists, docs-only PR 0B is exempt from the new global harness and
records the explicit baseline dependency/endpoint search. PR 1 must add repeated
and shuffled-input golden vectors for its pure firewall renderer and run the
transitional verification block. PR 6A and every later core PR use the maintained
global policy and replay checks through `argus-check`.

### PR 6B: Stable CLI and current operator contract

Scope:

- Introduce the thin `argus` dispatcher and public noun/verb grammar defined in
  the DX review while retaining milestone scripts as compatibility internals.
- Implement the human/JSON error envelope, exit classes, privilege labels,
  help contract, deprecation mapping, URL discovery, and installed/documented
  command parity checks.
- Add the three-path current docs landing structure and `argus doctor --json`
  revision/schema/protocol compatibility summary.

Acceptance:

- Every documented public command is installed and every installed public
  command is documented.
- Public help, JSON, failure, refusal, unavailable, interrupted, and recovery
  behavior passes the shared CLI contract suite.
- Current operator docs contain no unlabeled milestone commands or stale route
  literals.
- Status/preview commands are read-only; mutation requires the final explicit
  reviewed apply/rollback step.

### PR 7: Existing P0 acceptance-ledger audit

Scope:

- Re-evaluate `#265`, `#266`, `#217`, `#218`, and `#219` against current source,
  CI, and sanitized server evidence.
- Close an issue only when every acceptance item is proven.
- This PR is read-only except for the acceptance ledger and tracker links. If
  evidence contradicts completion, open or update a narrowly scoped child issue;
  every resulting fix lands through its own later PR.
- Keep `#197` and `#243` open until their full epics, including explicit Phase 2
  exclusions, are actually complete.

Acceptance:

- Hastur scheduling, credential delivery, egress, refresh, backup, and health
  are proven on the target runtime.
- Kadath's rootless database backup timer, verification, retention, and retired
  legacy schedule are proven.
- Phase 1 session, ledger/worker, issuer/agent, negative authorization, recovery,
  and zero-warning smoke evidence match their tracker checklists.
- No tracker is closed from code presence alone.

## Cross-PR Architecture

```text
                                +---------------------------+
                                | private operator browser  |
                                +-------------+-------------+
                                              |
                                     Tailscale Serve HTTPS
                                              |
                                +-------------v-------------+
                                | loopback Caddy + Argus API |
                                +------+------+-------------+
                                       |      |
                         typed queries |      | durable typed operations
                                       |      |
                 +---------------------v--+ +-v--------------------------+
                 | observation repository | | operation ledger + worker |
                 +-----------+-------------+ +-------------+-------------+
                             |                             |
                 redacted typed observations              | capabilities
                             |                             |
          +------------------+------------------+          |
          |                  |                  |          |
  +-------v-------+  +-------v-------+  +-------v----------v--+
  | host collector|  | route collector|  | domain-local agents|
  +-------+-------+  +---------------+  +-----+-----------+--+
          |                                  |           |
  proc/systemd/cron/listeners          personal-*     work-*
                                      Docker domains  Docker domains
```

Observation never grants authorization. Relocation consumes canonical desired
state plus fresh observations, but the domain agent independently rechecks
policy, capability, revision, target, and runtime evidence before mutation.

## Verification Matrix

| Requirement | Automated evidence | Server evidence |
| --- | --- | --- |
| Cross-project isolation | Rule rendering, relationship, negative matrix, rollback tests | Pairwise bridge probes, persisted/live equality, reboot |
| Session persistence | Cookie/session/API/UI state tests | Authenticated reload and browser restart over Tailscale HTTPS |
| Configured-estate discovery | Collector fixtures, reconciliation, partial-failure tests | Registered-source parity, freshness, and declared gaps |
| Relocation | Preview/policy, crash injection, rollback, UI tests | One reviewed pilot with backup, health, identity, route evidence |
| UI/branding | HTML/CSS/asset, accessibility and state tests | Desktop/mobile visual and keyboard QA |
| Test portability | Linux/macOS discovery checks | Non-root server suite |
| P0 tracker closeout | Checklist-to-evidence audit | Sanitized zero-warning smoke and workload-specific proofs |
| Deterministic core | Repeated and shuffled-input golden vectors, canonical-byte/digest equality, explicit-clock tests, no-AI dependency/static audit | Same version/config/snapshot replay produces the recorded digest |

PR 0B and PR 1 use the transitional explicit verification block because the
canonical wrapper intentionally lands in PR 6A:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q control-plane scripts tests
python3 scripts/validate-manifests
python3 scripts/smoke-test --offline
git diff --check
```

PR 6A and every later implementation PR run only the maintained source of truth:

```text
./scripts/argus-check
```

Server-affecting PRs also require purpose-built preflight, backup, apply,
rollback rehearsal where safe, post-apply checks, listener/exposure review, and
the full server smoke suite. Raw secrets and private runtime data remain outside
Git and public PR comments.

## Implementation Critique Loop

For each implementation PR:

1. Reproduce or prove the current gap with the smallest authoritative fixture or
   server-safe check.
2. Write the regression or acceptance test before the implementation where
   practical.
3. Implement the complete slice, including error, empty, stale, partial,
   rollback, and recovery paths.
4. Run focused tests, then the full offline suite.
5. Perform an adversarial code review for security, correctness, scope, test
   quality, failure recovery, operator clarity, and accidental exposure.
6. Fix every P0/P1 finding and rerun the review. Repeat until no actionable
   P0/P1 finding remains.
7. Push a draft PR with the safety checklist and linked issue.
8. Wait for CI and review feedback, fix findings, and rerun verification.
9. For server work, deploy only the reviewed branch, back up affected config,
   validate before reload, execute the approved preflight/apply, and capture
   sanitized evidence.
10. Merge only after all acceptance evidence is present. Rebase the next PR from
    the new `main`; do not stack unrelated fixes.

## Failure and Rescue Registry

| Failure | Detection | Safe state | Rescue |
| --- | --- | --- | --- |
| Firewall rule blocks own project | own-project probe fails before commit | restore prior persisted/live rules | apply root-owned backup and rerun pairwise matrix |
| Firewall still allows lateral traffic | cross-project negative probe succeeds | refuse apply/acceptance | restore backup; inspect bridge-to-project mapping |
| Session restore returns 401 | explicit startup state and safe reason code | unauthenticated; no mutation UI | correct origin/identity/session boundary, then reauthenticate |
| Collector source unavailable | source gap with timestamp and error class | partial inventory marked incomplete | restore collector/agent; rerun without changing canonical state |
| Observation is stale or ambiguous | freshness/collision check | relocation and admission denied | refresh source or resolve canonical link manually |
| Relocation fails before authority switch | journal phase and target absence proof | source remains authoritative | remove attempt-scoped target and restart verified source |
| Relocation fails after authority switch | durable authority record | source remains fenced | recover target or invoke reviewed rollback when data-safe |
| Dashboard asset fails | asset/state/UI tests | text identity and controls remain usable | restore prior generated assets; regenerate from reviewed source |
| Server verification cannot run | SSH/agent/preflight failure | PR stays draft/unmerged | repair access or run through approved server operator session |

## Explicitly Not In This Remediation Program

- Public Cloudflare activation, public portfolio hosting, DNS changes, Funnel,
  or router changes.
- Kubernetes replacement of the accepted trust-domain model.
- Automatic adoption or mutation of newly discovered resources.
- Generic arbitrary shell, raw Docker proxy, or management-plane Docker socket.
- Adoption of Approach C before its separate post-A evaluation gate.
- AI/LLM/model inference, probabilistic decisions, autonomous action, or an AI
  dependency in the Argus observation, policy, authorization, operation, or
  evidence path.
- Closing the full `#197` or `#243` epics before all of their independent
  acceptance criteria are actually satisfied.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | ---: | --- | --- |
| CEO Review | `/autoplan` | Scope and strategy | 2 | CLEAR | A-now/C-horizon, measurable gate, conformance, and non-gating advisory contract cleared, 9.5/10 |
| Codex Review | dual voice | Independent second model | 2 attempts | UNAVAILABLE | CLI returned no review body; not counted as consensus |
| Eng Review | `/autoplan` | Architecture and tests | 2 | CLEAR | deterministic acquisition/transform split, indirect-authority defense, and future AI isolation cleared, 9.5/10 |
| Design Review | `/autoplan` | UI/UX states and hierarchy | 1 | CLEAR | 14 findings resolved, 9/10; rendered QA remains an implementation gate |
| DX Review | `/autoplan` | Maintainer/operator experience | 2 | CLEAR | replay ownership, evidence vocabulary, and no speculative advisory scope cleared, 9/10 |

**CROSS-MODEL:** Independent amendment reviews and the primary review converge on
A as the deterministic foundation and C as a separately gated, one-way,
non-authoritative companion option. Codex CLI output was unavailable, so no
dual-model agreement is claimed.

**VERDICT:** CEO + DESIGN + ENG + DX PLAN REVIEWS CLEARED — operator approved
phased implementation on 2026-08-03. Every slice remains gated by its linked
issue, pull request, tests, safety checklist, and required server evidence.

**UNRESOLVED DECISIONS:**

- NO UNRESOLVED DECISIONS
