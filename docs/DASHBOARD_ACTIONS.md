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
verified Tailscale identity through the trusted Caddy proxy
opaque Argus session cookie
argus_csrf cookie == X-Argus-CSRF header
Origin == configured private operator origin
```

The bootstrap credential is submitted in the JSON body only for session
exchange and step-up reauthentication. It is cleared from the input
immediately and is never stored in browser storage.

## Response Rules

Action responses are structured JSON. They include operation class names such as `docker-compose-restart` or `argus-backup-run`, but they do not expose raw shell command strings.

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
- destination under `/srv/argus/runtime/backups/<id>`
- exact confirmation
- audit event

## Smoke Coverage

`scripts/smoke-test` starts a temporary local API with a temporary token and verifies:

- unauthenticated action POSTs return 401
- restart preview returns structured JSON without raw shell commands
- backup apply is blocked without exact confirmation
- logs sanitization redacts token-like content and truncates long lines
