# P3 Cloudflare Rollback Proof

P3-05 proves the Cloudflare rollback path exists before P3 closeout. Because
P3-04 deferred activation, rollback was previewed but not applied.

- Verified on: 2026-06-30T22:12Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `c2d3018`
- P3 issue: `#87`

## Rollback Preview

`scripts/oreo-cloudflare-rollback hello-nginx` is non-mutating without
`--apply` and returned:

```json
{
  "apply": false,
  "hostname": "hello-nginx.oreo-cloud.invalid",
  "ok": true,
  "workloadId": "hello-nginx",
  "wouldLowerEffectiveTo": "local",
  "wouldPreserveEvidence": true
}
```

Rollback was not applied because no Cloudflare activation occurred and
`hello-nginx` effective access was already `local`.

## Reconcile Proof

`scripts/oreo-access-reconcile --json` passed with live local probes:

```json
{
  "failures": 0,
  "offline": false,
  "ok": true,
  "warnings": 0
}
```

Relevant reconcile findings:

```text
OK intake-os: local probe completed http://127.0.0.1:8080 status=200
OK hastur: local probe completed http://127.0.0.1:4173 status=200
OK uptime-kuma: local probe completed http://127.0.0.1:54321 status=302
OK review-ui: local probe completed http://127.0.0.1:8765 status=200
OK dozzle: local probe completed http://127.0.0.1:8081 status=200
OK hello-nginx: local probe completed http://127.0.0.1:18080 status=200
OK hello-nginx: desired Cloudflare protected remains planned until verified activation
```

## Blocked Workloads

Blocked and deferred workloads remain local, with no Cloudflare URL configured:

```text
dozzle privacy=restricted desired=local effective=local cloudflare=
hastur privacy=sensitive desired=tailnet effective=local cloudflare=
intake-os privacy=sensitive desired=tailnet effective=local cloudflare=
review-ui privacy=internal desired=tailnet effective=local cloudflare=
uptime-kuma privacy=restricted desired=tailnet effective=local cloudflare=
```

`hello-nginx` remains local until a verified protected activation exists:

```text
hello-nginx privacy=unclassified desired=cloudflare-protected effective=local cloudflare=https://hello-nginx.oreo-cloud.invalid
```

## Post-Preview Verification

Server Git status remained clean:

```text
## main...origin/main
```

Server smoke after rollback preview and reconcile:

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

## Result

P3-05 acceptance is satisfied:

- rollback preview works
- rollback was not applied because activation was deferred
- blocked workloads remain local and excluded from Cloudflare effective access
- effective access reconciliation works
- smoke passes
