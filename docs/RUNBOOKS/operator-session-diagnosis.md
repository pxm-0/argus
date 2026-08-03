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
