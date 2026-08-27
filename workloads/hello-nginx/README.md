# Hello Nginx

Low-risk demo workload used for the first P1 migration.

## Status

- Lifecycle: admitted private-production pilot
- Migration: personal-sandbox source, personal-managed canonical target
- Runtime: Docker Compose
- Compose project: `hello-nginx`
- Service: `web`
- Health: container health plus loopback HTTP validation
- Access: private Tailscale Serve on port 8447; public exposure prohibited

## Public Exposure Policy

Public exposure remains deferred. The historical non-routable hostname is
retained only as inert planning metadata:

```text
hello-nginx.argus.invalid
```

No Cloudflare tunnel, DNS record, public route, Funnel, or `cloudflared`
service is enabled. The production pilot exposes only a loopback listener and
a tailnet-only Tailscale Serve route.

## Layout

```text
/srv/argus/workloads/hello-nginx/
├── README.md
├── manifest.json
└── source/
```

The repository normally ignores workload source trees. This stateless pilot
tracks only `source/docker-compose.yml` as a narrow exception so admission is
bound to the exact pinned image, loopback listener, health check, and Compose
project. No application source, runtime state, credential, or database is
tracked.

## Migration Notes

Original path:

```text
/srv/apps/hello-nginx
```

The old path is preserved as a compatibility symlink to:

```text
/srv/argus/workloads/hello-nginx/source
```

The original Compose file used host port `8080`, which conflicts with Intake OS.
The migrated Compose file binds Nginx to localhost only:

```text
127.0.0.1:18080->80/tcp
```

## Rollback

Use the linked typed operation:

```bash
rollback migration hello-nginx
```

For production rollback, use `rollback production hello-nginx`. Both paths
fence the managed target before restoring the proven personal-sandbox source.
