# P3 Next Workload Discovery

P3-06 inspects remaining workload risk without migrating files, changing
runtime state, or exposing new routes.

- Verified on: 2026-06-30T22:14Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `c2d3018`
- P3 issue: `#89`

## Discovery Scope

P3 discovery reviewed current tracked workload metadata plus read-only
`docker ps` and `docker inspect` output. Environment values were not recorded.
Only sensitive-looking environment key names are listed when observed.

No files were moved, no containers were restarted, and no access state was
changed.

## Candidate Summary

| Workload | Privacy | Migration State | Effective Access | P3 Recommendation |
| --- | --- | --- | --- | --- |
| `review-ui` | internal | needs-discovery | local | Best next candidate, but source/build provenance and bind mount ownership need review before migration. |
| `dozzle` | restricted | needs-discovery | local | Do not migrate or expose; Docker socket bind makes it an admin tool. |
| `uptime-kuma` | restricted | planned | local | Defer; stateful monitoring data and public host bind need a later stateful phase. |
| `hastur` | sensitive | planned | local | Defer; mounts SSH/auth/data paths and has wildcard host bind. |
| `intake-os` | sensitive | planned | local | Defer; company/sensitive workload with Caddy/Postgres volumes and Caddyfile bind. |

## review-ui

Runtime:

```text
container: review-ui
image: dupe-engine-worker:v0.10.9
status: running
runtime type: docker
compose project: none observed
```

Network and health:

```text
127.0.0.1:8765 -> 8765/tcp
health URL: http://127.0.0.1:8765
expected status: 200
```

Bind mounts:

```text
/data/runs -> /data/runs rw
/data/review_ui_jobs -> /data/review_ui_jobs rw
```

Named volumes:

```text
none observed
```

Secrets/env locations and keys:

```text
env file path: none observed
sensitive-looking env key names: GPG_KEY
```

Recommendation:

```text
Do not migrate in P3. Keep local effective access. Before migration, identify
the source repository/build process for dupe-engine-worker:v0.10.9, classify
/data/runs and /data/review_ui_jobs ownership/backup needs, and confirm whether
GPG_KEY is inherited from the image or runtime environment without recording
its value.
```

## dozzle

Runtime:

```text
container: dozzle
image: amir20/dozzle:latest
status: running
kind: admin-tool
```

Network and health:

```text
127.0.0.1:8081 -> 8080/tcp
health URL: http://127.0.0.1:8081
expected status: 200
```

Bind mounts:

```text
/var/run/docker.sock -> /var/run/docker.sock rw
```

Named volumes:

```text
none observed
```

Secrets/env locations and keys:

```text
env file path: none observed
sensitive-looking env key names: none observed by key name
```

Recommendation:

```text
Do not expose through Cloudflare or tailnet dashboard automation. Treat as a
restricted local admin tool because it mounts the Docker socket.
```

## uptime-kuma

Runtime:

```text
container: uptime-kuma
image: louislam/uptime-kuma:1
status: running
runtime type: docker-compose
compose project: uptime-kuma
```

Network and health:

```text
0.0.0.0:54321 -> 3001/tcp
[::]:54321 -> 3001/tcp
health URL: http://127.0.0.1:54321
expected status: 302
```

Bind mounts:

```text
none observed
```

Named volumes:

```text
uptime-kuma_uptime-kuma-data -> /app/data rw
```

Secrets/env locations and keys:

```text
env file path: none observed
sensitive-looking env key names: none observed by key name
```

Recommendation:

```text
Defer to a stateful-workload phase. It is a restricted monitoring dashboard
with persistent state and an existing wildcard host bind that needs remediation
before any access promotion.
```

## hastur

Runtime:

```text
container: hastur
image: hastur:local
status: running
runtime type: docker-compose
compose project: hastur
```

Network and health:

```text
0.0.0.0:4173 -> 4173/tcp
[::]:4173 -> 4173/tcp
health URL: http://127.0.0.1:4173
expected status: 200
```

Bind mounts:

```text
/home/oreo/.ssh -> /root/.ssh ro
/home/oreo/hastur/auth -> /app/auth ro
/home/oreo/hastur/data -> /app/data rw
```

Named volumes:

```text
none observed
```

Secrets/env locations and keys:

```text
env file path: none observed
sensitive-looking env key names: SCROLL_PASSES, EXPORT_SSH_KEY, FULL_SCROLL_PASSES
```

Recommendation:

```text
Defer. It is sensitive, mounts SSH/auth/data paths, and has a wildcard host
bind. It needs source review, secret handling review, backup planning, and bind
remediation before migration or access promotion.
```

## intake-os

Runtime:

```text
container: intake-os-local-proxy-1
image: caddy:2
status: running
runtime type: docker-compose
compose project: intake-os
```

Network and health:

```text
127.0.0.1:8080 -> 8080/tcp
health URL: http://127.0.0.1:8080
expected status: 200
```

Tracked discovery also records `0.0.0.0:3000 -> 3000/tcp` for the application
workload.

Bind mounts:

```text
/home/oreo/intake-os/deploy/Caddyfile.server -> /etc/caddy/Caddyfile ro
```

Named volumes:

```text
intake-os_caddy_config -> /config rw
intake-os_caddy_data -> /data rw
intake-os_intake_os_pgdata
```

Secrets/env locations and keys:

```text
env file path: not inspected in P3 because workload remains sensitive/deferred
sensitive-looking env key names: not inspected in P3
```

Recommendation:

```text
Defer. It is sensitive/company work with Caddy and PostgreSQL state, plus a
Caddyfile bind mount. It belongs in a later stateful migration phase with an
explicit backup/restore plan and operator approval.
```

## Verification

Server Git status after discovery:

```text
## main...origin/main
```

Server smoke after discovery:

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

P3-06 acceptance is satisfied:

- bind mounts documented
- named volumes documented
- health URLs documented where known
- secrets/env locations and sensitive-looking key names listed without values
- migration recommendations recorded
- no files moved
