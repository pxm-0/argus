# Private Dashboard Caddy Route

This directory contains the planned Caddy route for the Argus dashboard.

M5 Phase 1 intent:

- serve the dashboard backend on `127.0.0.1:8088`
- place only Tailscale Serve in front of the loopback backend so it supplies
  verified `Tailscale-User-Login`
- proxy `/api/*` to `127.0.0.1:8099`
- avoid Cloudflare, Funnel, DNS, router, and public listener changes

Generate the route:

```bash
argus-caddy-dashboard-plan
```

The command writes `caddy/dashboard.Caddyfile` and prints the manual backup,
validate, and reload sequence. It does not edit `/etc/caddy/Caddyfile`.
