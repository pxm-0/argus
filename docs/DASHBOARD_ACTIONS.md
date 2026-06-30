# Dashboard Action Safety

P2 adds a structured action layer for private dashboard operations.

## Endpoints

```text
GET  /api/actions
POST /api/workloads/<id>/logs/preview
POST /api/workloads/<id>/restart/preview
POST /api/workloads/<id>/restart/apply
POST /api/workloads/<id>/backup/preview
POST /api/workloads/<id>/backup/apply
```

All `POST` endpoints require:

```text
Authorization: Bearer <control-token>
```

The token is read from `/etc/oreo-cloud/control-token` by default. It is never embedded in dashboard HTML and the browser stores it only in `sessionStorage`.

## Response Rules

Action responses are structured JSON. They include operation class names such as `docker-compose-restart` or `oreo-backup-run`, but they do not expose raw shell command strings.

Logs preview returns sanitized, capped output:

```text
maxLines: 100
maxBytes: 65536
```

Secret-like lines and token-like key/value pairs are redacted.

## Apply Rules

Apply endpoints require exact workload ID confirmation:

```json
{"confirmation":"hello-nginx"}
```

Restart apply also requires:

- manifest restart permission
- docker-compose runtime metadata
- post-restart health verification
- audit event

Backup apply also requires:

- manifest backup permission
- destination under `/srv/oreo-cloud/runtime/backups/<id>`
- exact confirmation
- audit event

## Smoke Coverage

`scripts/smoke-test` starts a temporary local API with a temporary token and verifies:

- unauthenticated action POSTs return 401
- restart preview returns structured JSON without raw shell commands
- backup apply is blocked without exact confirmation
- logs sanitization redacts token-like content and truncates long lines
