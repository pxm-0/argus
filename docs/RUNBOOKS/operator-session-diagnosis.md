# Operator Session Diagnosis

This runbook covers remediation PR 2A for issue `#217`. It diagnoses session
restoration without changing cookie lifetime, origin validation, CSRF, step-up,
or trusted-proxy requirements. All evidence is status-only. Never record an
identity, cookie, CSRF value, bootstrap credential, proxy token, or private
request header.

## Confirmed root cause

The former `current_session()` path treated every failed operator lookup as a
confirmed disablement. If the trusted proxy identity was present while the
operator credential file was temporarily missing, unreadable, or invalid, a
read-only `GET /api/session` called `revoke_identity()`. Restoring the file did
not restore the session because the lookup itself had permanently revoked it.

PR 2A separates confirmed disablement from unavailable lookup state. Only a
confirmed `operator-disabled` result may revoke identity-wide sessions. Missing
identity/proxy evidence and unavailable operator/session stores fail closed
without changing session ownership or revocation state.

## Restoration decision table

| Boundary | Result | HTTP | Allowed mutation |
| --- | --- | ---: | --- |
| Trusted proxy identity absent or unverified | `identity-missing` | 401 | none |
| Operator registry unavailable or invalid | `session-store-unavailable` | 401 | none |
| Operator conclusively absent, disabled, or not owner | `operator-disabled` | 401 | revoke that identity's sessions |
| Session cookie absent | `cookie-missing` | 401 | none |
| Cookie has no matching identity-bound row | `session-not-found` | 401 | none |
| Matching session exceeded idle or absolute expiry | `session-expired` | 401 | none |
| Matching session was explicitly revoked | `session-revoked` | 401 | none |
| Matching active session | authenticated | 200 | update only `last_seen_at` and idle `expires_at` |

The response exposes only the allowlisted result. Exceptions, paths, database
details, identities, and credential values remain server-side.

## Safe live capture

Use the real private Tailscale HTTPS origin. Authenticate once, then reload and
request `/api/session` three times. Record only:

- response status;
- whether the browser sent a session cookie, as a boolean derived from
  `cookie-missing` versus another result, never the cookie itself;
- whether trusted identity reached the API, as a boolean derived from
  `identity-missing` versus another result, never the identity header;
- the allowlisted restoration result;
- whether the same browser remains authenticated after reload.

Store raw status evidence in a root-owned mode-0700 directory outside the
checkout with files mode 0600. Convert only the allowlisted three-run summary
for the PR. If browser access is unavailable, mark the real-origin check
blocked; loopback or unit evidence does not substitute for it.

## PR 2B boundary

PR 2B should consume these reason codes and model restoration as `checking`,
`authenticated`, `unauthenticated`, `expired`, or `unavailable`. It must not
extend session lifetime, store credentials in browser storage, relax cookies,
or weaken CSRF/origin/identity/revocation checks.

## Second factor (TOTP) at exchange and step-up

Each operator can be enrolled with an authenticator (RFC 6238: SHA-1, 6 digits,
30 s, 160-bit secret). Once enrolled, `POST /api/session/exchange` and
`POST /api/session/step-up` both require the bootstrap token and a current
`totp` code (or one unused recovery code). Body keys are exactly
`bootstrapToken` and `totp`.

| Condition | HTTP |
| --- | ---: |
| Operator enrolled, token and code both valid | 201 / 200 |
| Any factor missing or wrong (generic message, never says which) | 401 |
| Operator not enrolled, `ARGUS_TOTP_REQUIRED=1` | 403 |
| Operator not enrolled, `ARGUS_TOTP_REQUIRED` unset | token alone, as before |
| 5 failures in 5 minutes: locked 15 minutes, `Retry-After` set, correct credentials included | 429 |
| Secrets file present but unreadable or malformed | 401 (fails closed) |

- Codes are accepted for the counters `t-1..t+1` and each counter only once
  (it must exceed the last accepted one, updated in the same transaction).
- The lockout is per operator login, covers the bootstrap token too, and is
  checked before the token file is read. Rejection audit events carry the
  action, actor and a fixed reason only, never a submitted value.
- State lives in the session database (`totp_state`, `totp_recovery_used`,
  schema 4; the migration writes `<db>.pre-v4.bak` first).

### Enrol

On the server, from an interactive terminal (root only, TTY only):

```bash
sudo argus keys totp-enroll --operator <login>     # add --rotate to replace
```

The command prints the `otpauth://` URI and 10 single-use recovery codes once on
the terminal, asks for one valid code, and only then writes
`/etc/argus/operator-totp.json` (mode 0600, atomic). Scan the URI on a device
**other than the Mac that holds the bootstrap token**, otherwise one stolen
machine holds both factors. Store the recovery codes offline.

Then, once, enable the credential in `argus-control-api.service`:

```ini
LoadCredential=operator-totp.json:/etc/argus/operator-totp.json
Environment=ARGUS_TOTP_FILE=%d/operator-totp.json
```

`sudo systemctl daemon-reload && sudo systemctl restart argus-control-api`.
Verify exchange and step-up with token plus code from a second terminal before
setting `ARGUS_TOTP_REQUIRED=1` and restarting again. Rollback: unset
`ARGUS_TOTP_REQUIRED` and restart; the secrets stay in place.

### Limits

The secret is a real second factor only after the sudo-narrowing work (PR9): the
`oreo` account can read `/etc/argus` today, so root-only here is a file mode, not
yet a boundary. Until then the factor protects against a stolen bootstrap token,
not against a compromised `oreo` shell. Adding a second operator needs an API
restart (credentials are copied at unit start).
