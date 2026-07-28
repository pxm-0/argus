# Private Dashboard Caddy Route

This directory contains the planned Caddy route for the Argus dashboard.

M5 Phase 1 intent:

- serve the dashboard backend on `127.0.0.1:8088`
- place only Tailscale Serve in front of the loopback backend
- remove client-supplied `Tailscale-*` and `X-Argus-*` headers with explicitly
  ordered request handlers before proxying
- snapshot and restore only the client-supplied `X-Argus-CSRF` and
  `X-Argus-CSRF-Bootstrap` values required by the API
- replace the trusted Argus identity and proxy-marker headers only from
  Caddy-controlled inputs
- copy the Serve-attested login into `X-Argus-Tailnet-Login` before deleting
  the original `Tailscale-*` headers
- authenticate Caddy to the API with the root-owned proxy marker loaded from
  `/etc/argus/operator-proxy-token`
- proxy `/api/*` to `127.0.0.1:8099`
- avoid Cloudflare, Funnel, DNS, router, and public listener changes

Generate the route:

```bash
argus-caddy-dashboard-plan
```

The command writes `caddy/dashboard.Caddyfile` and prints the manual backup,
validate, and reload sequence. It does not edit `/etc/caddy/Caddyfile`.

The marker file is an environment file containing
`ARGUS_OPERATOR_PROXY_TOKEN=<random base64url>`, mode `0600`, owned by
`root:root`. systemd loads it for Caddy and supplies a private credential copy
to the API. Never print or commit its value.
