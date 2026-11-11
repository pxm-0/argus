# Dashboard Action Safety

P2 added a structured action layer for private dashboard operations. The
dashboard and `argus op` now use the typed operations API (served by
`control-plane/api/server.py`; full contract in
[`ARGUS_M5_OPERATIONS_CONTROL_PLANE.md`](ARGUS_M5_OPERATIONS_CONTROL_PLANE.md)):

## Endpoints

```text
GET  /api/workloads/<id>/operations
POST /api/workloads/<id>/operations/preview
POST /api/workloads/<id>/operations
POST /api/operations/<operation-id>/approve
POST /api/operations/<operation-id>/cancel
```

The original P2 per-action routes remain only as compatibility shims that map
onto the typed operations (`logs.preview`, `workload.restart`,
`backup.create`):

```text
POST /api/workloads/<id>/logs/preview
POST /api/workloads/<id>/restart/preview
POST /api/workloads/<id>/restart/apply
POST /api/workloads/<id>/backup/preview
POST /api/workloads/<id>/backup/apply
```

There is no action-listing endpoint; `GET /api/actions` returns 404.

All `POST` endpoints require:

```text
verified Tailscale identity through the trusted Caddy proxy
opaque Argus session cookie
argus_csrf cookie == X-Argus-CSRF header
Origin == configured private operator origin
```

The bootstrap credential is submitted in the JSON body only for session
exchange and step-up reauthentication, together with the operator's
authenticator code in `totp` (the "Authenticator code" input,
`autocomplete="one-time-code"`; a recovery code also works once). Both inputs
are cleared immediately after use and are never stored in browser storage. After
5 failures in 5 minutes the API answers 429 with `Retry-After` for 15 minutes;
see `docs/RUNBOOKS/operator-session-diagnosis.md`.

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
