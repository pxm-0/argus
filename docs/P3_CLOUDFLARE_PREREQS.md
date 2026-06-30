# P3 Cloudflare Prerequisite Record

P3-03 records whether real Cloudflare protected activation can proceed for the
approved low-risk workload, `hello-nginx`.

- Verified on: 2026-06-30T22:08Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `c2d3018`
- P3 issue: `#83`
- Activation decision: `defer`

## Required Fields

| Field | Value |
| --- | --- |
| hostname | `https://hello-nginx.oreo-cloud.invalid` |
| named tunnel id | not present |
| credentials location | not present |
| credentials tracked by Git | no |
| DNS route evidence | none; no DNS route created |
| Access policy evidence | none; activation deferred |
| allowed workload | `hello-nginx` |
| blocked workloads verified | yes; plan excludes blocked workloads |
| activation decision | defer |

## Tracked Exposure Policy

Cloudflare remains disabled and unprovisioned:

```json
{
  "enabled": false,
  "provisioned": false,
  "default": false,
  "allowQuickTunnels": false,
  "allowNamedTunnels": false,
  "requireAccessPolicy": true,
  "configPath": "/srv/oreo-cloud/cloudflare/planned-ingress.yml",
  "observedCloudflared": "not-installed"
}
```

`hello-nginx` remains planned for protected access but effectively local:

```json
{
  "desired": "cloudflare-protected",
  "effective": "local",
  "urls": {
    "local": "http://127.0.0.1:18080",
    "tailnet": "",
    "cloudflare": "https://hello-nginx.oreo-cloud.invalid"
  },
  "lastError": "Cloudflare protected access is planned only; no tunnel, DNS record, or public route is enabled."
}
```

The `.invalid` hostname is a planning placeholder, so activation must not
proceed.

## Server Prerequisite Evidence

Cloudflare runtime state:

```text
cloudflared command: not found
cloudflared service: inactive
missing /etc/cloudflared
/srv/oreo-cloud/cloudflare/planned-ingress.yml exists
```

Tracked credential search found only templates, not credentials:

```text
cloudflare/cloudflared-config.template.yml
templates/cloudflare/cloudflared-config.template.yml
```

No Cloudflare credential file, tunnel token, or named tunnel credential JSON was
found in tracked files.

## Plan Evidence

`scripts/oreo-cloudflare-plan` generated the planning config only:

```text
Cloudflare Exposure Plan

Provider enabled: false

Requested:
- hello-nginx: cloudflare-protected, hello-nginx.oreo-cloud.invalid

Blocked:
- none

Generated:
/srv/oreo-cloud/cloudflare/planned-ingress.yml

No cloudflared process, tunnel, DNS record, token, or public route was created.
```

## Activation Preview

`scripts/oreo-cloudflare-activate-preview hello-nginx` blocked activation:

```text
hello-nginx Cloudflare protected activation: blocked
Hostname: hello-nginx.oreo-cloud.invalid
Service: http://127.0.0.1:18080
Config path: /etc/cloudflared/oreo-cloud.yml
Blockers:
- real hostname required; .invalid is only a planning placeholder
- Cloudflare provider is disabled
- Cloudflare provider is not provisioned
- named tunnels are not allowed by exposure policy
Warnings:
- cloudflared is not installed; ingress validation/start cannot run yet
Manual checks:
- Cloudflare named tunnel exists and credentials are stored outside Git.
- Cloudflare Access application exists for the hostname.
- Access policy denies unauthenticated requests.
- DNS points at the named tunnel only after Access policy verification.
```

## Smoke Evidence

Server smoke confirmed the Cloudflare guardrails:

```text
PASS Cloudflare plan generated
PASS Cloudflare disabled by default
PASS Cloudflare plan excludes blocked workloads
PASS Cloudflare activation blocks placeholder hostname
PASS Cloudflare activation refuses quick tunnel mode
PASS Cloudflare rollback preview works
PASS no Funnel detected
PASS no unexpected cloudflared active
Smoke summary: 0 failure(s), 0 warning(s)
```

Server Git status remained clean:

```text
## main...origin/main
```

## Result

P3-03 activation prerequisites are not satisfied, so activation is safely
deferred:

- credentials path is outside Git only as an intended future path,
  `/etc/cloudflared/oreo-cloud.yml`; no credential currently exists
- Access policy evidence does not exist, so activation is deferred
- hostname remains `.invalid`, so activation is blocked
- `hello-nginx` remains `local` effective access
- blocked workload exposure remains false
- no Cloudflare tunnel, DNS route, token, or public route was created
