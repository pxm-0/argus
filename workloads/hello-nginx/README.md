# Hello Nginx

Low-risk demo workload used for the first P1 migration.

## Status

- Lifecycle: active
- Migration: migrated
- Runtime: Docker Compose
- Compose project: `hello-nginx`
- Service: `web`
- Health: `http://127.0.0.1:18080`
- Access: local effective, Cloudflare protected planned

## Cloudflare Protected Demo Plan

`hello-nginx` is the approved low-risk P1 demo workload for protected
Cloudflare planning. The route uses the intentionally non-routable hostname:

```text
hello-nginx.oreo-cloud.invalid
```

The desired access state is `cloudflare-protected`, but effective access remains
`local`. No Cloudflare tunnel, DNS record, public route, or `cloudflared`
service is enabled by this plan.

## Layout

```text
/srv/oreo-cloud/workloads/hello-nginx/
├── README.md
├── manifest.json
└── source/
```

`source/` is ignored by Oreo Cloud Git. The migrated source contains the
workload Compose file and is intentionally not tracked here.

## Migration Notes

Original path:

```text
/srv/apps/hello-nginx
```

The old path is preserved as a compatibility symlink to:

```text
/srv/oreo-cloud/workloads/hello-nginx/source
```

The original Compose file used host port `8080`, which conflicts with Intake OS.
The migrated Compose file binds Nginx to localhost only:

```text
127.0.0.1:18080->80/tcp
```

## Rollback

Stop the migrated stack:

```bash
docker compose -p hello-nginx -f /srv/oreo-cloud/workloads/hello-nginx/source/docker-compose.yml down
```

Remove the compatibility symlink and restore the backup directory recorded in
`manifest.json`.
