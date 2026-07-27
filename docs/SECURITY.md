# Security Requirements

## Default Posture

```text
private first, public never by accident
```

## Hard Blocks in P0

P0 must not expose:

- PostgreSQL
- Docker socket
- SSH
- host filesystem browser
- control API directly
- dashboard publicly
- workload source code
- `.env` files
- secrets
- tokens
- database files
- runtime backups

## Dashboard Exposure

Dashboard must be served by Caddy on port `8088`, bound to the Tailscale IP only.

Do not bind dashboard to `0.0.0.0`.

## Control API Exposure

Control API must bind only to:

```text
127.0.0.1:8099
```

Caddy may proxy it only through the Tailscale-bound dashboard route.

## Token Handling

Control token path:

```text
/etc/argus/control-token
```

Permissions:

```text
root:root
0600
```

systemd supplies a read-only private credential copy to the API process.

Rules:

- never commit token
- never print token
- never include token in generated HTML
- never write token to logs
- use it only to exchange verified Tailscale identity for an Argus session
- clear the credential input immediately after exchange
- never store it in browser storage
- store only an opaque session identifier in an `HttpOnly`, `Secure`,
  `SameSite=Strict` cookie
- require the readable `argus_csrf` cookie to exactly match the
  `X-Argus-CSRF` header for state-changing requests
- expire server-side sessions after 30 minutes of inactivity and eight hours
  absolute, with logout, revocation, and five-minute step-up reauthentication

Operator identity is accepted only from `X-Argus-Tailnet-Login` on the
loopback-only API when `X-Argus-Proxy-Token` matches the root-owned Caddy marker.
Caddy removes incoming `Tailscale-*` and `X-Argus-*` headers before setting
those values. The normalized login must be an enabled owner in the structured
server-local `/etc/argus/operators.json` allowlist.

## Git Hygiene

Git should track platform config and docs only.

Must not track:

- workload source
- `.env`
- runtime data
- logs
- metrics output
- backups
- tokens
- Cloudflare credentials
- SSH keys
- TLS private keys
- database files/dumps

## Metrics Safety

Metrics collector must not expose:

- env vars
- process command-line args
- container inspect output
- secrets

Use `ps -eo pid,comm,%cpu,%mem` rather than `ps aux` or `ps -ef`.

## Access Policy Safety

P0 rules:

- `none`, `local`, `tailnet` can be safe effective states.
- Cloudflare states can be desired/planned.
- Public Cloudflare exposure requires confirmation.
- Restricted/sensitive public exposure is blocked by default.
- Effective access updates only after successful apply.

## Audit Logging

Write audit events to:

```text
/srv/argus/runtime/audit.log
```

Do not track audit logs in Git.

Audit events must not contain secrets.

## Caddy Changes

Generate the planned dashboard route without touching live Caddy:

```bash
argus-caddy-dashboard-plan
```

Before editing Caddyfile:

```bash
sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.backup.$(date +%Y%m%d-%H%M%S)"
```

Validate:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

Reload only on success:

```bash
sudo systemctl reload caddy
```

## Cloudflare Safety

P0 Cloudflare is plan-only.

Do not:

- start cloudflared
- run Quick Tunnel
- create named tunnel
- create DNS records
- store token in repo

## Doctor Checks

`argus-doctor` must warn if:

- dashboard listener is not bound to Tailscale IP
- control API binds to non-localhost
- Tailscale Funnel appears enabled
- cloudflared service is active unexpectedly
- `.env` is tracked
- Cloudflare credentials are tracked
- workload source is tracked
- policy allows restricted public exposure
- `access.json.effective` says Cloudflare but Cloudflare provider is disabled
