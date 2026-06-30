# Oreo Cloud P2 Baseline

Baseline recorded from `oreochiserver` for P2-00.

- Verified at: `2026-06-30T20:00:43Z`
- GitHub issue: `#54`
- Target branch: `p2/00-closeout-baseline`
- Source spec: `docs/OREO_CLOUD_P2.md`

## Git State

Server checkout:

```text
## main...origin/main
```

Tags:

```text
p1-complete
```

`p2-complete` does not exist yet.

## Smoke Test

Command:

```bash
cd /srv/oreo-cloud
scripts/smoke-test
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
PASS workload manifests valid
PASS no unapproved workload source tracked
PASS no runtime artifacts tracked
PASS migration statuses valid
PASS backup plans exist for migrated workloads
PASS operation scripts exist
PASS operation permissions valid
PASS dashboard V2 generated
PASS dashboard V2 contains no secret markers
PASS effective access policy valid
PASS control API binds localhost only
PASS metrics collector works
PASS metrics.json valid
PASS Cloudflare plan generated
PASS Cloudflare disabled by default
PASS Cloudflare plan excludes blocked workloads
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

## Service Status

```text
oreo-control-api.service: active
oreo-metrics.timer: active
cloudflared: inactive
tailscale funnel status: No serve config
```

## Network Bindings

Observed listeners relevant to Oreo Cloud:

```text
100.75.210.83:8088  caddy dashboard listener
127.0.0.1:8099      oreo-control-api.service
127.0.0.1:2019      caddy admin API
*:80                caddy HTTP listener
```

P2 starts with the control API bound to localhost only and the dashboard route bound to the Tailscale IP. The live smoke test reports the dashboard route as private.

## Caddy Validation

Command:

```bash
cd /srv/oreo-cloud
caddy validate --config caddy/dashboard.Caddyfile
```

Result:

```text
Valid configuration
```

Caddy also reported a formatting warning for `caddy/dashboard.Caddyfile`; no formatting change is included in this baseline PR.

## Workload Summary

| Workload | Lifecycle | Kind | Runtime | Migration | Privacy | Desired Access | Effective Access |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `intake-os` | active | web-app | docker-compose | planned | sensitive | tailnet | local |
| `hastur` | active | web-app | docker-compose | planned | sensitive | tailnet | local |
| `uptime-kuma` | active | web-app | docker-compose | planned | restricted | tailnet | local |
| `review-ui` | active | web-app | docker | needs-discovery | internal | tailnet | tailnet |
| `dozzle` | active | admin-tool | docker | needs-discovery | restricted | local | local |
| `hello-nginx` | active | web-app | docker-compose | migrated | unclassified | cloudflare-protected | local |

## Access And Exposure Notes

- Cloudflare provider is disabled in checked-in config.
- `cloudflared` is inactive on the live server.
- Live Tailscale reports `No serve config`; no Funnel is active.
- Checked-in `config/routes.json` and `config/exposure.json` still contain stale discovery fields showing an earlier observed Funnel route for `review-ui`. P2-08 should reconcile observed/effective state; P2-00 records the discrepancy but does not mutate config.
- `hello-nginx` still has desired access `cloudflare-protected` with effective access `local`, which matches the P1 plan-only Cloudflare state.

## GitHub Tracking

Current open issue before P2 issue creation:

```text
#5 P0-05: Optional Workload Organization
```

P2 setup performed for this phase:

```text
Created label: p2
Created milestone: P2
Created issue: #54 P2-00: Baseline and Release Hygiene
```

## Acceptance

- [x] `p1-complete` tag exists.
- [x] Smoke test passes at start of P2.
- [x] Control API binds localhost only.
- [x] Dashboard route remains private according to smoke and listener state.
- [x] `cloudflared` is not unexpectedly active.
- [x] Funnel remains disabled in live Tailscale state.
