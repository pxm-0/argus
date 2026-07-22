# P4 Backup Strategy

P4-02 creates a backup strategy before any stateful workload migration. The
strategy is intentionally conservative: backup execution remains disabled for
all newly documented stateful, sensitive, restricted, or admin-adjacent
workloads until a restore drill proves the plan.

- Verified on: 2026-07-01T12:39Z
- P4 issue: `#97`

## Policy

P4 backup policy:

- document data paths before enabling backup execution
- keep `backupAllowed: false` until a workload-specific backup has been tested
- keep `restoreAllowed: false` until a non-destructive restore drill passes
- exclude env files, secret values, credentials, SSH keys, tokens, and Docker
  socket access by default
- never print or commit secret contents
- restore into ignored runtime test paths before touching live services

## Manifest Updates

P4 adds plan-only manifests for:

```text
review-ui
dozzle
uptime-kuma
hastur
intake-os
```

Each manifest records backup requirements and exclusions while keeping:

```json
{
  "backupAllowed": false,
  "restoreAllowed": false
}
```

`hello-nginx` remains the only backup-enabled workload, and it already has a
source-only backup and restore drill pattern.

## Workload Strategy

| Workload | Data Paths | Backup Posture | Restore Requirement |
| --- | --- | --- | --- |
| `review-ui` | `/data/runs`, `/data/review_ui_jobs` | Planned but disabled until state ownership is classified. | Restore to isolated bind paths; confirm job output expectations. |
| `dozzle` | none; Docker socket access only | Disabled. | No restore drill needed for app state; preserve local-only posture. |
| `uptime-kuma` | `uptime-kuma_uptime-kuma-data` volume | Planned but disabled until volume backup consistency is proven. | Restore into isolated volume and confirm app starts without exposing routes. |
| `hastur` | `/home/oreo/hastur/data`; auth/SSH paths excluded | Planned but disabled; sensitive paths require explicit approval. | Restore into isolated paths and never overwrite live SSH/auth data. |
| `intake-os` | PostgreSQL volume, Caddy data/config volumes | Planned but disabled; requires explicit re-scope. | Database dump/restore and volume restore must be proven in isolation. |
| `hello-nginx` | source compose only | Configured and enabled. | Existing non-destructive restore drill pattern applies. |

## Exclusions

Default backup exclusions:

```text
env values
.env files
.env.server files
API keys
tokens
passwords
SSH keys
auth secrets
Docker socket access
live runtime artifacts
```

Workload-specific exclusions:

```text
dozzle: /var/run/docker.sock
hastur: /home/oreo/.ssh, /home/oreo/hastur/auth, /home/oreo/hastur/.env
intake-os: /home/oreo/intake-os/.env.server, database passwords, API keys
uptime-kuma: notification tokens and internal monitor secrets
review-ui: env values and unclassified transient job output until reviewed
```

## Restore Requirements

Before `backupAllowed` can become true for a stateful workload:

1. Document exact source paths or volumes.
2. Document exact exclusions.
3. Document whether the app must be stopped or quiesced.
4. Produce an artifact under `/srv/argus/runtime/backups/<id>`.
5. Verify checksums.
6. Restore into `/srv/argus/runtime/restore-tests/<id>/...`.
7. Confirm live services are unaffected.
8. Run `scripts/smoke-test` on `oreochiserver`.

Before `restoreAllowed` can become true:

1. A non-destructive restore drill must pass.
2. The expected recovered files or volumes must be listed.
3. Rollback and cleanup steps must be documented.
4. The workload owner/operator must approve live restore semantics.

## Result

P4-02 acceptance is satisfied:

- `backupAllowed` remains false for newly documented stateful workloads
- data paths are documented
- restore requirements are documented
- backup exclusions are documented
- no secrets are committed
