# P4 Workload Risk Matrix

P4-01 documents workload risk before any stateful migration or internal routing
change. The review used tracked config plus read-only `docker ps` and
`docker inspect` evidence from `oreochiserver`.

- Verified on: 2026-07-01T12:36Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `049009b`
- P4 issue: `#95`

Environment values were not recorded. Only env file paths and
sensitive-looking key names are listed.

## Decision

P4 selects `review-ui` as the only plausible next migration candidate, but not
as automatically safe. P4-03 must either migrate it after the gates below are
cleared or document a safe deferral.

Required gates before `review-ui` migration:

- identify source/build provenance for `dupe-engine-worker:v0.10.9`
- classify ownership and backup needs for `/data/runs`
- classify ownership and backup needs for `/data/review_ui_jobs`
- confirm whether `GPG_KEY` is inherited from the image or runtime environment
  without recording its value
- decide whether bind-mounted state is included in backups, excluded, or
  treated as external state

All sensitive, restricted, admin, or wildcard-bound workloads remain deferred.

## Summary Matrix

| Workload | Risk | Migration Recommendation |
| --- | --- | --- |
| `review-ui` | Medium | Candidate after provenance, bind-mount, and env-key review. |
| `hello-nginx` | Low | Already migrated; keep as regression/restore reference. |
| `uptime-kuma` | High | Defer; stateful restricted monitoring with wildcard bind. |
| `hastur` | Critical | Defer; sensitive SSH/auth/data mounts and wildcard bind. |
| `intake-os` | Critical | Defer; sensitive/company workload with PostgreSQL/Caddy state and secrets. |
| `dozzle` | Critical | Do not expose; Docker socket admin tool. |

## review-ui

| Field | Value |
| --- | --- |
| id | `review-ui` |
| runtime | `docker` |
| compose path | none observed |
| image | `dupe-engine-worker:v0.10.9` |
| ports | `127.0.0.1:8765 -> 8765/tcp` |
| bind mounts | `/data/runs -> /data/runs rw`; `/data/review_ui_jobs -> /data/review_ui_jobs rw` |
| named volumes | none observed |
| env file paths | none observed for running container; related legacy `dupe-engine` compose files reference `.env` |
| stateful data paths | `/data/runs`; `/data/review_ui_jobs` |
| secrets risk | Medium; sensitive-looking env key name `GPG_KEY` observed |
| backup requirements | Decide whether `/data/runs` and `/data/review_ui_jobs` are durable state, cache, or rebuildable job output. |
| rollback difficulty | Medium; single Docker container, but bind-mounted state ownership is unclear. |
| migration recommendation | Candidate for P4-03 only after provenance and state classification. |

Notes:

- Effective access is `local`.
- Desired access is `tailnet`.
- Prior tracked discovery mentioned a stale Funnel route, but P2/P3 server
  evidence found no current Tailscale Serve/Funnel config.

## hello-nginx

| Field | Value |
| --- | --- |
| id | `hello-nginx` |
| runtime | `docker-compose` |
| compose path | `/srv/argus/workloads/hello-nginx/source/docker-compose.yml` |
| compose project | `hello-nginx` |
| service | `web` |
| image | `nginx:alpine` |
| ports | `127.0.0.1:18080 -> 80/tcp` |
| bind mounts | none observed |
| named volumes | none observed |
| env file paths | none observed |
| stateful data paths | none observed |
| secrets risk | Low; no sensitive-looking env key names observed |
| backup requirements | Source-only backup already tested; keep latest artifact validation. |
| rollback difficulty | Low; migrated demo workload with restore drill evidence. |
| migration recommendation | Already migrated; use for regression, smoke, and restore drill pattern. |

## uptime-kuma

| Field | Value |
| --- | --- |
| id | `uptime-kuma` |
| runtime | `docker-compose` |
| compose path | `/srv/argus/workloads/uptime-kuma/source/docker-compose.yml` |
| compose project | `uptime-kuma` |
| service | `uptime-kuma` |
| image | `louislam/uptime-kuma:1` |
| ports | `0.0.0.0:54321 -> 3001/tcp`; `[::]:54321 -> 3001/tcp` |
| bind mounts | none observed |
| named volumes | `uptime-kuma_uptime-kuma-data -> /app/data rw` |
| env file paths | none observed |
| stateful data paths | `/var/lib/docker/volumes/uptime-kuma_uptime-kuma-data/_data`; `/app/data` in container |
| secrets risk | High; restricted monitoring state can contain internal URLs, tokens, alert targets, and operational history |
| backup requirements | Volume backup with restore drill; preserve ownership and SQLite/application data consistency. |
| rollback difficulty | High; stateful app and wildcard host bind remediation needed. |
| migration recommendation | Defer in P4 unless backup and restore strategy is proven first. |

## hastur

| Field | Value |
| --- | --- |
| id | `hastur` |
| runtime | `docker-compose` |
| compose path | `/srv/argus/workloads/hastur/source/compose.yml` |
| compose project | `hastur` |
| service | `hastur` |
| image | `hastur:local` |
| ports | `0.0.0.0:4173 -> 4173/tcp`; `[::]:4173 -> 4173/tcp` |
| bind mounts | `/home/oreo/.ssh -> /root/.ssh ro`; `/home/oreo/hastur/auth -> /app/auth ro`; `/home/oreo/hastur/data -> /app/data rw` |
| named volumes | none observed |
| env file paths | `/home/oreo/hastur/.env` referenced by compose; value not inspected |
| stateful data paths | `/home/oreo/hastur/auth`; `/home/oreo/hastur/data`; `/home/oreo/.ssh` |
| secrets risk | Critical; sensitive-looking key names include `SCROLL_PASSES`, `EXPORT_SSH_PORT`, `EXPORT_SSH_HOST`, `EXPORT_SSH_KEY`, `EXPORT_SSH_USER`, `FULL_SCROLL_PASSES` |
| backup requirements | Explicit secret exclusion, data backup, auth backup decision, and restore isolation are required before any move. |
| rollback difficulty | Critical; SSH/auth mounts and wildcard bind make rollback and exposure safety non-trivial. |
| migration recommendation | Defer. Discovery only until explicitly scoped with operator approval. |

## intake-os

| Field | Value |
| --- | --- |
| id | `intake-os` |
| runtime | `docker-compose` |
| compose path | `/srv/argus/workloads/intake-os/source/docker-compose.server.yml` |
| compose project | `intake-os` |
| service | not tracked |
| images | `intake-os-web`; `caddy:2` |
| ports | tracked: `0.0.0.0:3000 -> 3000/tcp`; `127.0.0.1:5433 -> 5432/tcp`; `127.0.0.1:8080 -> 8080/tcp` |
| bind mounts | `/home/oreo/intake-os/deploy/Caddyfile.server -> /etc/caddy/Caddyfile ro` |
| named volumes | `intake-os_intake_os_pgdata`; `intake-os_caddy_data -> /data rw`; `intake-os_caddy_config -> /config rw` |
| env file paths | `/home/oreo/intake-os/.env.server` referenced by server compose; value not inspected |
| stateful data paths | PostgreSQL volume; Caddy data/config volumes |
| secrets risk | Critical; sensitive-looking key names include `OPENAI_API_KEY`, `AUTH_MODE`, `POSTGRES_PASSWORD` |
| backup requirements | Database backup, volume backup, Caddy state decision, secret exclusion, restore rehearsal, and application consistency plan. |
| rollback difficulty | Critical; company/sensitive app with database and Caddy state. |
| migration recommendation | Defer. No migration without explicit P4 re-scope and backup/rollback approval. |

## dozzle

| Field | Value |
| --- | --- |
| id | `dozzle` |
| runtime | `docker` |
| compose path | none observed |
| image | `amir20/dozzle:latest` |
| ports | `127.0.0.1:8081 -> 8080/tcp` |
| bind mounts | `/var/run/docker.sock -> /var/run/docker.sock rw` |
| named volumes | none observed |
| env file paths | none observed |
| stateful data paths | none observed |
| secrets risk | Critical through Docker socket access rather than env/config. |
| backup requirements | None for app state; preserve local-only/admin-tool posture. |
| rollback difficulty | Medium operationally, critical security impact if exposed. |
| migration recommendation | Do not expose or migrate into public/tailnet automation. Keep local admin-only. |

## P4 Risk Ordering

From lowest to highest migration risk:

```text
hello-nginx   already migrated; low regression target
review-ui     possible candidate, but state/provenance unclear
uptime-kuma   restricted stateful monitoring
dozzle        Docker socket admin tool
hastur        sensitive SSH/auth/data
intake-os     sensitive company app with database/Caddy state
```

## Result

P4-01 acceptance is satisfied:

- paths are listed without secret contents
- risk ratings are assigned
- `review-ui` is selected as the only possible P4 candidate, gated by
  provenance, bind-mount, env-key, and backup decisions
