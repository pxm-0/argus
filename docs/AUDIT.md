# Oreo Cloud Audit Events

Oreo Cloud writes local audit events to:

```text
/srv/oreo-cloud/runtime/audit.log
```

The file is JSONL: one JSON object per line. `runtime/*` and `*.log` are ignored by Git, so audit logs must stay untracked.

## Event Shape

Every event should include:

```json
{"timestamp":"2026-06-30T12:00:00Z","actor":"local-cli","action":"restart.apply","workloadId":"hello-nginx","result":"ok"}
```

Required fields:

- `timestamp`: UTC ISO-8601 timestamp.
- `actor`: source of the event, such as `local-cli` or `admin-token`.
- `action`: stable operation name.
- `workloadId`: workload ID, or a system scope such as `cloudflare`.
- `result`: `ok`, `blocked`, or `failed`.

Extra fields are allowed when they are operationally useful and non-sensitive.

## Secret Rules

Audit events must not contain secrets, tokens, passwords, private keys, bearer headers, raw environment values, or private key material.

The shared CLI audit helper redacts secret-shaped keys before writing events. `oreo-events` also sanitizes events while reading so older or hand-written lines do not dump secret-shaped fields.

Do not add raw command output, `.env` content, control tokens, Cloudflare credentials, SSH keys, or request headers to audit events.

## Current Actions

The current P1 action names are:

- `privacy.set`
- `access.apply`
- `logs.view`
- `restart.preview`
- `restart.apply`
- `backup.plan`
- `backup.run`
- `cloudflare.plan`
- `migration.apply`

Manual migration events should use `migration.plan` for dry-run planning and `migration.apply` for cutover or rollback-affecting changes.

## CLI

Print recent events:

```bash
/srv/oreo-cloud/scripts/oreo-events
```

Print sanitized JSONL:

```bash
/srv/oreo-cloud/scripts/oreo-events --json
```

Filter by workload, action, or result:

```bash
/srv/oreo-cloud/scripts/oreo-events --workload hello-nginx
/srv/oreo-cloud/scripts/oreo-events --action restart.apply
/srv/oreo-cloud/scripts/oreo-events --result blocked
```

## Dashboard And API

The dashboard and `/api/events` show only sanitized recent event summaries:

- `timestamp`
- `action`
- `workloadId`
- `result`

Raw audit details remain local to `runtime/audit.log` and are not exposed by the dashboard.

## Verification

Useful checks:

```bash
git check-ignore runtime/audit.log
/srv/oreo-cloud/scripts/oreo-events --limit 20
/srv/oreo-cloud/scripts/oreo-events --limit 20 --json
/srv/oreo-cloud/scripts/smoke-test
```
