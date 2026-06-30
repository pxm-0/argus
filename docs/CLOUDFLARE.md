# Cloudflare Provisioning Plan

## Goal

Provision for future workload access through Cloudflare without enabling exposure in P0.

Cloudflare should be a per-workload access provider, not the default platform access method.

## P0 Rules

- Do not start `cloudflared`.
- Do not create a tunnel.
- Do not create DNS records.
- Do not run Quick Tunnel automatically.
- Do not store tokens or credentials in Git.
- Do not expose the dashboard.
- Do not expose the control API.
- Do not expose PostgreSQL.
- Do not expose Docker socket.
- Generate plans only.

## Access States

Cloudflare relates to two access states:

```text
cloudflare-protected
cloudflare-public
```

For P0:

- `cloudflare-protected` can be requested and planned.
- `cloudflare-public` can be requested only if policy allows.
- Neither state becomes effective automatically unless Cloudflare activation is explicitly implemented later.

## Quick Tunnel

Quick Tunnel is useful for short demos and development previews.

P0 behavior:

```text
allowQuickTunnels: false
```

Future behavior can allow Quick Tunnel only after explicit confirmation.

## Named Tunnel

Named Tunnel is the intended future production-grade option.

Future named tunnel requirements:

- hostname configured
- workload policy allows Cloudflare
- Cloudflare Access required unless explicitly public
- credentials stored outside Git
- ingress validated before reload
- no database/admin/control targets exposed

## Files

```text
cloudflare/README.md
cloudflare/cloudflared-config.template.yml
cloudflare/planned-ingress.yml
cloudflare/generate_cloudflare_config.py
cloudflare/quick-tunnel-notes.md
scripts/oreo-cloudflare-plan
```

## Planned Ingress Generator

`generate_cloudflare_config.py` should:

1. read `workloads.json`
2. read `privacy.json`
3. read `access.json`
4. read `policy.json`
5. read `exposure.json`
6. include only workloads where desired access is Cloudflare-related and policy allows planning
7. require hostname for named routes
8. append a final `http_status:404` catch-all rule
9. write `cloudflare/planned-ingress.yml`
10. never write credentials
11. never start `cloudflared`

Example generated file:

```yaml
# Generated plan only. No tunnel is enabled by this file.
ingress:
  - hostname: demo.example.com
    service: http://127.0.0.1:8090
  - service: http_status:404
```

## CLI

Create:

```text
scripts/oreo-cloudflare-plan
```

Usage:

```bash
oreo-cloudflare-plan
```

Output:

```text
Cloudflare Exposure Plan

Provider enabled: false

Requested:
- demo-app: cloudflare-protected, missing hostname

Blocked:
- uptime-kuma: restricted/admin target
- dashboard: control-plane target

Generated:
cloudflare/planned-ingress.yml
```

The CLI is plan-only. It rewrites `cloudflare/planned-ingress.yml` and prints a
summary, but it never shells out to `cloudflared`, DNS providers, systemd, Docker,
or Tailscale.

## Policy Requirements

Recommended P0 policy:

- `restricted` -> `cloudflare-public`: blocked
- `sensitive` -> `cloudflare-public`: blocked
- `restricted` -> `cloudflare-protected`: allowed only with confirmation and Access requirement
- `sensitive` -> `cloudflare-protected`: allowed only with confirmation and Access requirement
- `unclassified` -> `cloudflare-public`: allowed only with confirmation phrase, but still planned only in P0

## Future Activation Phase

Only after P0:

1. Install/configure `cloudflared` if needed.
2. Store credentials under `/etc/cloudflared`, not Git.
3. Generate ingress from Oreo Cloud.
4. Validate ingress.
5. Start/reload `cloudflared`.
6. Verify Cloudflare Access policy.
7. Update `access.json.effective`.
8. Write audit event.
