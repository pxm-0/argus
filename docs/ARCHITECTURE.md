# Architecture: Argus P0

## High-Level Architecture

```text
Phone / Laptop
      |
      | Tailscale private network
      v
oreochiserver Tailscale IP
      |
      v
Caddy bound to Tailscale IP on :8088
      |
      +--> static dashboard files
      |
      +--> /api/* -> 127.0.0.1:8099
                         |
                         v
                    Argus Control API
                         |
                         +--> config/*.json
                         +--> scripts/argus-access-*
                         +--> scripts/argus-privacy-set
                         +--> runtime/audit.log

Metrics timer
      |
      v
collect_metrics.py -> dashboard/public/metrics.json

Cloudflare planning
      |
      v
generate_cloudflare_config.py -> cloudflare/planned-ingress.yml
```

## Trust Boundaries

### Tailscale Boundary

The dashboard should be reachable only from the tailnet in P0. Caddy must bind the dashboard listener to the Tailscale IP, not to all interfaces.

### Local API Boundary

The control API must bind only to `127.0.0.1:8099`. It is not a public API. It is only reachable through the Tailscale-bound Caddy route.

### Admin Mutation Boundary

View-only dashboard access does not require a token. Any mutation requires admin mode with a bearer token from `/etc/argus/control-token`.

### Cloudflare Boundary

Cloudflare configuration is planned only in P0. No tunnel should be started and no DNS should be created by P0 scripts.

## Core Components

### 1. Platform Root

```text
/srv/argus
```

The platform root contains tracked docs, config, templates, dashboard, API, scripts, systemd unit templates, and workload manifests.

### 2. Git Repo

`/srv/argus` is a local Git repo. Git tracks platform definitions, not secrets or workload source code.

### 3. Neutral Workload Registry

`config/workloads.json` contains workload identity and runtime facts only.

Examples:

- workload id
- name
- lifecycle
- runtime type
- Compose path
- Compose project name
- local URL
- health check URL
- canonical source path
- migration state

It should not permanently mark a workload as private/public/company/demo.

### 4. Privacy Registry

`config/privacy.json` stores privacy state per workload.

### 5. Access Registry

`config/access.json` stores desired and effective access state per workload.

### 6. Policy Registry

`config/policy.json` stores allowed/blocked transitions and confirmation requirements.

### 7. Exposure Registry

`config/exposure.json` stores provider capability and Cloudflare provisioning state.

### 8. Dashboard

Static HTML/CSS/JS generated from tracked generator source and served by Caddy.
Generated files under `control-plane/dashboard/public/` are local artifacts and
are ignored by Git.

The dashboard has:

- workload cards
- privacy controls
- access controls
- access preview/apply flow
- monitoring toggle
- Cloudflare plan panel
- audit/event panel

### 9. Control API

A tiny Python standard-library HTTP API for authenticated mutations.

### 10. Monitoring Collector

A timer-driven Python script that writes safe metrics to `metrics.json`.

### 11. Cloudflare Planner

A generator that reads workload/access/privacy/policy config and writes a
planned Cloudflare ingress file only. The generated plan is a local artifact and
is ignored by Git.

## P0 Network Model

```text
Private dashboard:
http://oreochiserver:8088

Fallback:
http://<tailscale-ip>:8088

Control API backend:
http://127.0.0.1:8099

Cloudflare:
planned only, no active tunnel in P0
```

## Access State Machine

```text
none -> local -> tailnet -> cloudflare-protected -> cloudflare-public
```

Not every transition is allowed. Policy decides.

Recommended P0 behavior:

- `none`, `local`, and `tailnet` can be applied by P0.
- `cloudflare-protected` can be requested and planned.
- `cloudflare-public` can be requested only if policy allows, but should not become effective until Cloudflare activation is explicitly implemented.

## Desired vs Effective Access

`desired` means what the admin requested.

`effective` means what is actually active.

This distinction avoids lying in the dashboard. Example:

```json
{
  "desired": "cloudflare-protected",
  "effective": "tailnet",
  "lastError": "Cloudflare is provisioned but disabled in P0."
}
```

## Workload Migration Architecture

Canonical workload layout:

```text
/srv/argus/workloads/<id>/
├── README.md
├── manifest.json
└── source/      # ignored by Argus Git
```

Migration should use copy-first, validate, cut over, symlink old path, health check, and rollback if needed.

## Security Posture

Default posture:

```text
private first, public never by accident
```

P0 must not expose:

- PostgreSQL
- Docker socket
- SSH
- dashboard publicly
- control API publicly
- workload source or env files
- Cloudflare tokens
- `.env` files
