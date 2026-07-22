# P1 Baseline Re-Verification

Verified: 2026-06-30T18:15:54Z on `oreochiserver`

## Summary

P0 remains healthy and ready for P1 implementation.

- `/srv/argus` is a Git repo on `main`.
- `argus-smoke-test` passes with `0 failure(s), 0 warning(s)`.
- `argus-control-api.service` is active and enabled.
- `argus-metrics.timer` is active and enabled.
- Caddy validates successfully.
- Tailscale Funnel is disabled.
- Dashboard is bound to the Tailscale IP on port `8088`.
- Control API is bound only to `127.0.0.1:8099`.
- API read check returned 5 workloads.

## Git State

```text
## main...origin/main
```

## Smoke Test

Command:

```bash
argus-smoke-test
```

Result:

```text
PASS Git repo exists
PASS config/access.json valid JSON
PASS config/exposure.json valid JSON
PASS config/monitoring.json valid JSON
PASS config/policy.json valid JSON
PASS config/privacy.json valid JSON
PASS config/routes.json valid JSON
PASS config/workloads.json valid JSON
PASS JSON configs valid
PASS dashboard index.html generated
PASS dashboard style.css generated
PASS dashboard app.js generated
PASS control API binds localhost only
PASS metrics collector works
PASS metrics.json valid
PASS Cloudflare plan generated
PASS Cloudflare disabled by default
PASS no Funnel detected
PASS no unexpected cloudflared active
PASS no tracked secrets
PASS workload CLI works
PASS health CLI works
PASS Caddy dashboard route generated
PASS Caddy route is private
PASS planned Caddy route validates
PASS live Caddy validates

Smoke summary: 0 failure(s), 0 warning(s)
```

## Services

```text
argus-control-api.service active enabled
argus-metrics.timer active enabled
```

## Caddy

Command:

```bash
caddy validate --config /etc/caddy/Caddyfile
```

Result:

```text
Valid configuration
exit=0
```

Dashboard route import:

```text
/etc/caddy/Caddyfile imports /etc/caddy/ArgusDashboard.Caddyfile
```

Dashboard route:

```caddyfile
http://oreochiserver:8088, http://100.75.210.83:8088 {
    bind 100.75.210.83
    root * /srv/argus/control-plane/dashboard/public
    handle /api/* {
        reverse_proxy 127.0.0.1:8099
    }
    file_server
}
```

Dashboard HTTP check:

```text
HTTP/1.1 200 OK
Server: Caddy
```

## Tailscale Funnel

Command:

```bash
tailscale funnel status
```

Result:

```text
No serve config
```

## Listening Ports

```text
100.75.210.83:8088  caddy dashboard route
127.0.0.1:8099      argus-control-api.service
```

No `0.0.0.0:8088` or non-localhost `:8099` listener was observed.

## API Read Check

Command:

```bash
curl -sS --max-time 5 http://127.0.0.1:8099/api/workloads
```

Result:

```text
5 workloads returned
```

## Known Open P1 Issues

- #29 P1-01: Baseline Re-Verification
- #30 P1-02: Workload Manifest Schema Upgrade
- #31 P1-03: First Low-Risk Workload Migration
- #32 P1-04: Logs CLI
- #33 P1-05: Restart Preview and Apply CLI
- #34 P1-06: Backup and Restore Planning
- #35 P1-07: Dashboard V2
- #36 P1-08: Audit Events
- #37 P1-09: Cloudflare Protected Demo Workload
- #38 P1-10: Smoke Test Expansion
- #39 P1-11: Closeout

## Baseline Decision

P1 can proceed. No unexpected public exposure, active Funnel, invalid Caddy
configuration, API bind drift, tracked secret, or failing P0 smoke check was found.
