# PRD: Argus P0

## Product Summary

Argus is a private personal ECS-style server control plane. It organizes local Docker/Docker Compose workloads, tracks them in Git-backed configuration, exposes a private dashboard over Tailscale, and provides safe controls for visibility and access state.

P0 focuses on the platform foundation, not full deployment automation.

## User Problem

The server currently risks becoming a pile of ports, folders, and mental notes. The owner wants a single access point from phone/laptop anywhere, a clear model for workloads, and a path toward private/public workload access without accidentally exposing sensitive services.

## Target User

Primary user: the server owner/admin.

Secondary users: future collaborators or testers who may access specific workloads through a controlled access method, such as Tailscale or Cloudflare Access.

## Goals

1. Create `/srv/argus` as the canonical platform root.
2. Track platform configuration and docs in Git.
3. Model workloads as agnostic units by default.
4. Separate workload identity from privacy and access policy.
5. Provide a private dashboard accessible from phone/laptop over Tailscale.
6. Provide dashboard toggles for privacy and desired access in authenticated admin mode.
7. Keep desired access separate from effective access.
8. Add a btop-style monitoring panel hidden behind a toggle.
9. Provide safe workload migration planning into `/srv/argus/workloads/<id>/source`.
10. Provision Cloudflare access planning without enabling public exposure by default.

## Non-Goals for P0

P0 will not implement:

- Kubernetes
- full CI/CD
- one-click browser deploys
- browser terminal
- public dashboard
- automatic Cloudflare tunnel activation
- automatic DNS creation
- automatic destructive workload migration
- public database access
- direct Docker socket exposure
- multi-user RBAC

## Key Concept: Workloads Are Agnostic

A workload should not be permanently classified as company, demo, private, or public inside `workloads.json`.

Instead:

- `workloads.json` describes what the app is and how it runs.
- `privacy.json` stores current privacy classification.
- `access.json` stores desired and effective access states.
- `policy.json` stores guardrails.
- `exposure.json` stores provider capability/planning.

This lets the dashboard toggle privacy and access without changing the workload identity model.

## P0 Access States

```text
none
local
tailnet
cloudflare-protected
cloudflare-public
```

Definitions:

- `none`: no managed access.
- `local`: server-local URL only, usually `127.0.0.1`.
- `tailnet`: private access through Tailscale.
- `cloudflare-protected`: externally reachable but requires Cloudflare Access or equivalent auth.
- `cloudflare-public`: externally reachable without tailnet access or auth.

## P0 Privacy States

```text
unclassified
personal
internal
sensitive
restricted
```

Privacy does not equal access. A workload may be `sensitive` and still have `tailnet` access. A workload may be `unclassified` and still be kept local until deliberately exposed.

## Functional Requirements

### Workload Registry

The system must maintain a neutral workload registry with runtime, health, and paths.

### Privacy Registry

The system must maintain privacy state per workload.

### Access Registry

The system must maintain desired and effective access state per workload.

### Policy Engine

The system must block unsafe transitions by default, especially restricted/sensitive workloads moving to public exposure.

### Dashboard

The dashboard must show workload cards, privacy, desired access, effective access, health, routes, migration state, and monitoring.

### Dashboard Mutations

Unauthenticated dashboard mode is view-only. Authenticated admin mode can change privacy and request/apply access changes.

### Control API

The control API must bind only to `127.0.0.1:8099`. Caddy may proxy `/api/*` only through the Tailscale-bound dashboard route.

### Monitoring

The dashboard must include a btop-style monitor panel that is hidden by default and only fetches metrics while open.

### Cloudflare Planning

The system must generate Cloudflare exposure plans but not start tunnels, create DNS, or publish anything in P0.

### Git

The platform root must be a local Git repo. Secrets, tokens, workload source, `.env`, runtime data, metrics, logs, and backups must not be tracked.

## Non-Functional Requirements

- Safe by default.
- Idempotent scripts.
- No secret printing.
- No public exposure by default.
- All config JSON validates with `python3 -m json.tool`.
- Works without `jq`.
- Python scripts use the standard library where practical.
- Caddy config is validated before reload.
- Workload migration uses copy-validate-cutover-rollback flow.

## Success Criteria

P0 is successful when the owner can open a private dashboard from phone over Tailscale, see all workloads and system state, toggle monitor mode, toggle privacy/desired access in admin mode, and run smoke tests showing no accidental public exposure.
