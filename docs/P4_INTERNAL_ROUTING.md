# P4 Internal Routing Review

P4-05 reviews internal routing options without adding public exposure. No Caddy
route, Tailscale Serve/Funnel config, Cloudflare tunnel, DNS record, or access
state was changed.

- Verified on: 2026-07-01T12:43Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `049009b`
- P4 issue: `#103`

## Dashboard And API

The Argus dashboard remains private on the Tailscale-bound Caddy route:

```caddy
http://oreochiserver:8088, http://100.75.210.83:8088 {
    bind 100.75.210.83
    root * /srv/argus/control-plane/dashboard/public
    handle /api/* {
        reverse_proxy 127.0.0.1:8099
    }
    file_server
}
```

The control API remains localhost-only:

```text
127.0.0.1:8099
```

Caddy validation:

```text
Valid configuration
```

## Current Route Config

Tracked route intent:

| Workload | Tailnet Route | Cloudflare Route | Effective Access |
| --- | --- | --- | --- |
| `intake-os` | planned `http://oreochiserver:8080` | disabled | local |
| `hastur` | planned `http://oreochiserver:4173` | disabled | local |
| `uptime-kuma` | planned `http://oreochiserver:54321` | disabled | local |
| `review-ui` | planned `http://oreochiserver:8765` | disabled | local |
| `dozzle` | local-only | blocked | local |
| `hello-nginx` | local-only | planned placeholder `.invalid` | local |

Planned tailnet URLs are not treated as effective routed access. Effective
access remains `local` for all workloads.

## Listener Review

Relevant listeners:

```text
100.75.210.83:8088  Argus dashboard, Tailscale-bound Caddy route
127.0.0.1:8099      Argus control API
127.0.0.1:8765      review-ui
127.0.0.1:8080      intake-os local proxy
127.0.0.1:8081      dozzle
127.0.0.1:18080     hello-nginx
0.0.0.0:4173        hastur legacy host bind
[::]:4173           hastur legacy host bind
0.0.0.0:54321       uptime-kuma legacy host bind
[::]:54321          uptime-kuma legacy host bind
*:80                existing default Caddy site
```

P4 should not add private routing on top of unclear or unsafe workload state.
The existing wildcard binds for `hastur` and `uptime-kuma` are legacy exposure
risks to remediate before any internal route promotion. The existing default
Caddy `:80` site is also host-level state outside the Argus dashboard
route and should be reviewed before broader routing work.

## Routing Recommendations

| Workload | P4 Routing Recommendation |
| --- | --- |
| `review-ui` | Keep local until migration/provenance gates clear. A future tailnet route should be host-bound, not path-proxied, unless app subpath support is proven. |
| `uptime-kuma` | Keep local/effective deferred. Remediate wildcard bind and prove backup/restore before tailnet convenience routing. |
| `hastur` | Keep local/effective deferred. Do not route until SSH/auth/data risks are explicitly handled. |
| `intake-os` | Keep local/effective deferred. Do not route without explicit re-scope and database backup/rollback plan. |
| `dozzle` | Keep local-only. Do not expose through Cloudflare or convenience dashboard routing because it mounts the Docker socket. |
| `hello-nginx` | Keep as local regression target; Cloudflare remains deferred until real protected-access prerequisites exist. |

## External Exposure State

Tailscale Funnel:

```text
No serve config
```

Cloudflare:

```text
cloudflared inactive
```

Server smoke:

```text
PASS P3 Cloudflare activation remains deferred
PASS P3 deferral evidence recorded
PASS no Funnel detected
PASS no unexpected cloudflared active
PASS no tracked secrets
PASS doctor security audit clean
PASS workload CLI works
PASS health CLI works
PASS Caddy dashboard route generated
PASS Caddy route is private
PASS planned Caddy route validates
PASS live Caddy validates

Smoke summary: 0 failure(s), 0 warning(s)
```

## Result

P4-05 acceptance is satisfied:

- dashboard remains private
- API remains localhost-only
- sensitive/admin tools are not externally exposed by Argus routes
- no Funnel is configured
- smoke passes
