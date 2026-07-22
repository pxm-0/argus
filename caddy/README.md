# Private Dashboard Caddy Route

This directory contains the planned Caddy route for the Argus dashboard.

P0 intent:

- serve the dashboard on port `8088`
- bind only to the Tailscale IP from `config/routes.json`
- proxy `/api/*` to `127.0.0.1:8099`
- avoid Cloudflare, Funnel, DNS, router, and public listener changes

Generate the route:

```bash
argus-caddy-dashboard-plan
```

The command writes `caddy/dashboard.Caddyfile` and prints the manual backup,
validate, and reload sequence. It does not edit `/etc/caddy/Caddyfile`.
