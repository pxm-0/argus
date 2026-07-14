# Oreo Cloud P0 Package

This package is the P0 handoff for building **Oreo Cloud**: a private, Git-tracked, personal ECS-style control plane for `oreochiserver`.

P0 is not a public hosting platform. P0 is the minimum safe foundation:

- one private dashboard reachable from phone/laptop over Tailscale
- Git-tracked platform configuration
- neutral workload registry
- dashboard-visible privacy and access states
- authenticated dashboard toggles for privacy and desired access
- read-only workload health/status commands
- btop-style monitoring panel behind a dashboard toggle
- workload migration planning into `/srv/oreo-cloud/workloads/<id>`
- Cloudflare exposure planning, disabled by default
- no public exposure unless a future task explicitly enables it

## Document Map

| File | Purpose |
|---|---|
| `ARGUS_V1_BRIDGE.md` | Accepted bridge from Oreo Cloud into the Argus V1 trust-domain and portfolio architecture |
| `docs/ARGUS_V1_DECISIONS.md` | Public-safe architecture decisions, viability evidence, limits, and delivery ledger |
| `docs/PRD.md` | Product requirements for P0 |
| `docs/ARCHITECTURE.md` | System architecture and trust boundaries |
| `docs/IMPLEMENTATION_PLAN.md` | Step-by-step build plan |
| `docs/CONFIG_MODEL.md` | Workload/access/privacy/policy schema model |
| `docs/DASHBOARD_AND_API.md` | Dashboard behavior and local control API spec |
| `docs/MONITORING.md` | btop-style metrics collector and UI spec |
| `docs/MIGRATION.md` | Safe workload move plan |
| `docs/CLOUDFLARE.md` | Cloudflare provisioning model, disabled by default |
| `docs/SECURITY.md` | Safety rules, token handling, exposure guardrails |
| `docs/OPERATIONS.md` | Commands and operator workflow |
| `docs/CODEX_TASKS.md` | Task prompts to paste into Codex |
| `docs/PR_WORKFLOW.md` | Required PR workflow for every P0 phase |
| `docs/ACCEPTANCE.md` | P0 definition of done and smoke tests |
| `docs/REFERENCES.md` | External references used for implementation assumptions |
| `docs/P5_PLATFORM_MATURITY.md` | P5 scheduled smoke, retention, and restore-gate scope |
| `docs/P6_PRODUCTIZATION_OPTIONAL.md` | P6 optional template/productization scope |
| `docs/LEAN_CLEANUP_CLOSEOUT.md` | Generated-artifact and duplicate-surface cleanup record |
| `templates/` | Starter config, systemd, Caddy, Cloudflare, and script templates |

## P0 North Star

From a phone on Tailscale, open:

```text
http://oreochiserver:8088
```

See all workloads, health, routes, privacy state, desired access state, effective access state, and a toggleable monitor panel.

Admin mode can change privacy and desired access, but P0 should only apply safe states automatically. Cloudflare exposure remains planned/provisioned, not live, unless explicitly enabled in a later phase.
