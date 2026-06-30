# P3 Tailnet-Only Routing Review

P3-02 verifies that the Oreo Cloud dashboard and control API remain private
before any real Cloudflare protected activation work begins.

- Verified on: 2026-06-30T22:06Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `c2d3018`
- P3 issue: `#81`

## Route Model

Tracked route config keeps the dashboard on the tailnet and the API on
localhost:

```json
{
  "dashboard": {
    "bind": "tailscale",
    "port": 8088,
    "url": "http://oreochiserver:8088"
  },
  "api": {
    "bind": "127.0.0.1",
    "port": 8099,
    "public": false
  }
}
```

The route generator refuses a public dashboard bind and refuses a non-local or
public API bind.

## Live Dashboard Route

The live Caddy import for the dashboard is bound to the Tailscale IP:

```caddy
http://oreochiserver:8088, http://100.75.210.83:8088 {
    bind 100.75.210.83
    root * /srv/oreo-cloud/control-plane/dashboard/public
    handle /api/* {
        reverse_proxy 127.0.0.1:8099
    }
    file_server
}
```

This keeps the dashboard listener off wildcard interfaces and proxies API
requests only to the localhost control API.

## Listening Sockets

Observed listeners relevant to P3-02:

```text
100.75.210.83:8088  caddy dashboard route
127.0.0.1:8765      review-ui container
127.0.0.1:8099      oreo-control-api
127.0.0.1:8080      local workload listener
127.0.0.1:8081      local workload listener
*:80                existing default Caddy site
```

No `0.0.0.0:8088`, wildcard `:8088`, or non-localhost `:8099` listener was
observed.

The existing `*:80` Caddy default site is not the Oreo Cloud dashboard or
control API route. It remains a separate host-level Caddy default and should be
reviewed before any broader external exposure work, but P3-02 dashboard/API
privacy acceptance is satisfied.

## Service State

```text
oreo-control-api.service active
caddy active
cloudflared inactive
```

Tailscale Funnel status:

```text
No serve config
```

## Validation

Live Caddy validation without mutation:

```text
Valid configuration
```

Doctor summary:

```text
ok=True failures=0 checks=21
```

Server smoke after the review:

```text
PASS Cloudflare rollback preview works
PASS effective access reconcile clean
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

Server Git status remained clean:

```text
## main...origin/main
```

## Result

P3-02 acceptance is satisfied:

- dashboard remains private
- API remains localhost-only
- no Funnel detected
- no unexpected `cloudflared` active
- Caddy planned/live validation passes
- doctor passes
