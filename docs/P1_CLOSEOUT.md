# Oreo Cloud P1 Closeout

P1 status: complete when this closeout PR is merged and `p1-complete` is tagged on `main`.

Verified on `oreochiserver`: 2026-06-30T18:56Z.

## Completed Phases

| Phase | Result |
| --- | --- |
| P1 spec | PR #28 added `docs/OREO_CLOUD_P1.md`. |
| P1-01 baseline | PR #40 recorded server baseline evidence in `docs/P1_BASELINE.md`. |
| P1-02 manifest schema | PR #41 added workload manifest documentation and an example schema. |
| P1-03 first migration metadata | PR #42 recorded `hello-nginx` as the first migrated workload. |
| P1-04 logs CLI | PR #43 added safe `oreo-logs`. |
| P1-05 restart CLI | PR #44 added safe restart preview/apply commands. |
| P1-06 backup/restore planning | PR #45 added backup and restore planning commands and docs. |
| P1-07 dashboard V2 | PR #46 added manifest, backup, operation, and audit context to the dashboard/API. |
| P1-08 audit events | PR #47 hardened audit event output and documentation. |
| P1-09 Cloudflare protected demo plan | PR #48 planned protected access for `hello-nginx` only. |
| P1-10 smoke expansion | PR #49 expanded smoke coverage for P1 invariants. |

## Migrated Workloads

`hello-nginx` is the only P1 migrated workload.

- Canonical root: `/srv/oreo-cloud/workloads/hello-nginx`
- Source path: `/srv/oreo-cloud/workloads/hello-nginx/source`
- Legacy compatibility path: `/srv/apps/hello-nginx`
- Runtime: Docker Compose project `hello-nginx`, service `web`
- Health URL: `http://127.0.0.1:18080`
- Migration status: `migrated`
- Privacy: `unclassified`
- Effective access: `local`

## Operation Commands

Added during P1:

- `scripts/oreo-logs`
- `scripts/oreo-restart-preview`
- `scripts/oreo-restart`
- `scripts/oreo-backup-plan`
- `scripts/oreo-backup-run`
- `scripts/oreo-restore-plan`
- `scripts/oreo-events`

Server note: these commands work from `/srv/oreo-cloud/scripts/...`. Only
`oreo-events` is currently symlinked in `/usr/local/bin`; the newer operation
commands still need an operator sudo symlink refresh if short command names are
desired.

## Dashboard Changes

Dashboard V2 now shows:

- workload manifest-backed operation and backup metadata
- migration status and last health check
- last sanitized audit event per workload
- Access Plan, Backups, Cloudflare Plan, Events, and System sections
- protected Cloudflare desired state for `hello-nginx`

The live control API was restarted after the P1-10 merge and now returns the
Dashboard V2 fields: top-level `events`, per-workload `operations`, `backup`,
and `lastAuditEvent`.

## Backup Status

`hello-nginx` has a backup plan:

- destination: `/srv/oreo-cloud/runtime/backups/hello-nginx`
- `backupAllowed`: `false`
- `oreo-backup-run hello-nginx` remains blocked unless the manifest explicitly
  enables backup execution.
- restore remains manual through `oreo-restore-plan hello-nginx`.

## Cloudflare Status

Cloudflare remains plan-only.

- Provider enabled: `false`
- `cloudflared`: not active
- DNS records created: none
- Router ports opened: none
- Public route exposed: none
- Planned demo workload: `hello-nginx`
- Planned hostname: `hello-nginx.oreo-cloud.invalid`
- Effective access: `local`
- Desired access: `cloudflare-protected`
- Planned ingress requires Cloudflare Access before any future activation.

## Final Smoke Test

Final live command:

```bash
cd /srv/oreo-cloud
scripts/smoke-test
```

Output:

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

## Known Limitations

- Only `hello-nginx` was migrated in P1.
- Cloudflare is not activated; P1 only proves the protected plan path.
- The planned Cloudflare hostname uses `.invalid` and is intentionally not
  reachable.
- Backup execution is blocked for `hello-nginx`; only planning is enabled.
- Restore remains manual.
- Dashboard admin controls still require the local control API token and should
  remain private.
- Most new operation CLIs are not yet symlinked into `/usr/local/bin` on
  `oreochiserver`.

## P2 Recommendations

- Add a real protected Cloudflare activation phase with named tunnel
  credentials stored outside Git, Access policy verification, and post-apply
  effective access updates.
- Migrate the next low-risk workload only after adding rollback notes and backup
  metadata first.
- Add first-class manifest schema validation instead of shape-only smoke checks.
- Add a safe dashboard action layer for logs/restart previews without exposing
  raw command output.
- Implement backup execution for workloads that have explicit source/database
  backup requirements and restore tests.
- Make generated dashboard runtime-event rendering avoid dirtying the tracked
  static artifact during server-side regeneration.
