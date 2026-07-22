# Argus M5 Topology UI Foundation

This first M5 gate adds a private, read-only whole-estate projection to the
existing dashboard. It does not add a domain agent, capability issuer, public
route, or new mutation endpoint.

## Information architecture

The topology is read from left to right:

1. `oreochiserver` is the physical containment boundary.
2. The management plane contains the private operator UI and loopback API.
3. `legacy-rootful` is an explicit quarantine, not a workload trust domain.
4. The four workload trust domains remain visible even when empty:
   `personal-sandbox`, `personal-managed`, `work-sandbox`, and `work-managed`.
5. Each workload appears exactly once under its canonical runtime placement.
6. The workload detail list remains the keyboard-accessible drill-down and
   control surface.

Every topology edge has one allowlisted meaning: `containment`,
`runtime-placement`, or `route`. Trust-domain boundaries are rendered as
columns; they are never styled as ordinary dependency edges.

## State semantics

The projection keeps declared access and effective access separate. A visible
blue rule marks drift, and the text retains both values so drift is not encoded
by color alone. Canonical M4 classification supersedes legacy quarantine only
for explicitly classified workloads. Unknown or server-local workload records
fall back to `legacy-rootful` with denied admission.

The topology projection copies only allowlisted identifiers and state labels.
It does not copy arbitrary runtime inspection output, secrets, environment
values, Docker socket details, or capability material.

## Control boundary

All topology data is read-only. A workload placed outside `legacy-rootful`
receives `controlMode: domain-agent-required`; its existing central-dashboard
controls render disabled. This is deliberate fail-closed behavior until M5 adds
an identity-backed approval flow and a policy-enforcing domain-local agent.

Legacy operations remain subject to the existing backend manifest, policy,
authentication, confirmation, redaction, and audit checks. The UI does not
convert visibility into authorization.

## Remaining M5 gates

- declared, observed, and effective freshness/provenance evidence;
- domain-local collectors and typed operation agents;
- preview digest, expected revision, policy version, identity approval,
  short-lived capability, replay protection, and idempotency enforcement;
- durable operation state and rollback evidence;
- negative authorization, stale evidence, degraded mode, and server validation.
