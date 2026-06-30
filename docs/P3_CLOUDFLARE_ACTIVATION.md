# P3 Cloudflare Activation Deferral

P3-04 would activate `hello-nginx` through `cloudflare-protected` only if the
P3-03 prerequisites existed. They do not exist, so activation remains safely
deferred.

- Verified on: 2026-06-30T22:10Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `c2d3018`
- P3 issue: `#85`
- Decision: `defer`

## Activation Rules

P3 activation rules remain:

```text
allowed workload: hello-nginx only
access mode: cloudflare-protected only
public mode: forbidden
Access/Auth: required
```

No activation apply was run because the preview was blocked.

## Missing Prerequisites

Activation is deferred for these blockers:

```text
- real hostname required; .invalid is only a planning placeholder
- Cloudflare provider is disabled
- Cloudflare provider is not provisioned
- named tunnels are not allowed by exposure policy
```

Additional warning:

```text
- cloudflared is not installed; ingress validation/start cannot run yet
```

Required manual checks remain incomplete:

```text
- Cloudflare named tunnel exists and credentials are stored outside Git.
- Cloudflare Access application exists for the hostname.
- Access policy denies unauthenticated requests.
- DNS points at the named tunnel only after Access policy verification.
```

## Activation Preview

`scripts/oreo-cloudflare-activate-preview --json hello-nginx` returned
`"ok": false`:

```json
{
  "allowNamedTunnels": false,
  "allowQuickTunnels": false,
  "blockers": [
    "real hostname required; .invalid is only a planning placeholder",
    "Cloudflare provider is disabled",
    "Cloudflare provider is not provisioned",
    "named tunnels are not allowed by exposure policy"
  ],
  "configPath": "/etc/cloudflared/oreo-cloud.yml",
  "hostname": "hello-nginx.oreo-cloud.invalid",
  "ok": false,
  "providerEnabled": false,
  "providerProvisioned": false,
  "service": "http://127.0.0.1:18080",
  "warnings": [
    "cloudflared is not installed; ingress validation/start cannot run yet"
  ],
  "workloadId": "hello-nginx"
}
```

## Planned Ingress Only

The generated ingress remains a plan-only file:

```yaml
# Generated plan only. No tunnel is enabled by this file.
ingress:
  - hostname: hello-nginx.oreo-cloud.invalid
    service: http://127.0.0.1:18080
    # Cloudflare Access policy required before activation.
  - service: http_status:404
```

No `cloudflared` config was applied to `/etc/cloudflared`, no DNS route was
created, and no Cloudflare process was started.

## Effective Access

`hello-nginx` remains local:

```text
desired=cloudflare-protected
effective=local
cloudflare=https://hello-nginx.oreo-cloud.invalid
lastError=Cloudflare protected access is planned only; no tunnel, DNS record, or public route is enabled.
```

`cloudflared` remains inactive:

```text
inactive
```

## Validation

Doctor summary:

```text
ok=True failures=0 checks=21
```

Server smoke after the deferral review:

```text
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

P3-04 deferral acceptance is satisfied:

- prerequisites are missing, so activation remains deferred
- this document explains the missing prerequisites
- `hello-nginx` effective access remains `local`
- `cloudflared` remains inactive
- no credentials, DNS route, tunnel, token, public route, or activation evidence
  was created
- smoke still passes
