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
exchange and step-up reauthentication, together with the operator's
authenticator code in `totp` (the "Authenticator code" input,
`autocomplete="one-time-code"`; a recovery code also works once). The sign-in
form is a real `<form>` (login `autocomplete="username"`, token
`autocomplete="current-password"`), so a password manager can save the token and
offer the code; the login field is only for the password manager and is never
sent. When a change needs step-up, the same form opens in confirm mode and the
change continues after a fresh code. Token and code are cleared immediately after
each attempt and are never stored in browser storage. After
5 failures in 5 minutes the API answers 429 with `Retry-After` for 15 minutes;
see `docs/RUNBOOKS/operator-session-diagnosis.md`.

In the terminal, `argus op` on macOS reads the authenticator secret from the
login Keychain item `argus-totp` and sends the codes itself, so only the
bootstrap token is typed. It records the last code counter it sent in
`~/Library/Caches/argus/totp-last-counter` and waits for the next 30 s code
rather than resend a spent one, within a run or across runs. Store
the base32 secret from `argus keys totp-enroll` (the `secret=` value of the
`otpauth://` URI) with `security add-generic-password -s argus-totp -a <login> -T "" -w`,
which prompts for it. `-T ""` trusts no app, so macOS asks once per run before
handing the secret over; choose "Allow", not "Always Allow". Without it,
`security` is trusted and any process running as you can read the secret
silently. With no item the CLI asks for the code as before. This
deliberately puts the second factor on the Mac, against the enrolment hint to keep
it on another device; the API still requires the owner's tailnet identity and the
bootstrap token.

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
