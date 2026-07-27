# Argus M5 Phase 1 Runbook

Phase 1 replaces reusable browser bearer authentication with a verified
Tailscale identity plus a short-lived Argus session, and routes routine
operations through durable typed-operation agents.

## Boundaries

- Tailscale Serve is the only remote entry point. Funnel stays disabled.
- Caddy listens only on `127.0.0.1:8088`.
- The API listens only on `127.0.0.1:8099`.
- `/etc/argus/operators.json`, `/etc/argus/operator-proxy-token`, and
  capability keys are server-local and never committed.
- The control API has no Docker socket mount and no capability-signing key.
- Each agent accepts only an operation ID over its Unix socket. It loads the
  exact durable record, independently rechecks domain, policy, revision,
  digest, expiry, nonce, and typed parameters, then executes.

Tailscale Serve supplies `Tailscale-User-Login` to the loopback-only Caddy
backend. Caddy removes client-supplied `Tailscale-*` and `X-Argus-*` headers,
copies the verified login to `X-Argus-Tailnet-Login`, and supplies a root-owned
proxy marker as `X-Argus-Proxy-Token`. The API accepts those headers only from
a loopback peer with a constant-time marker match.

## Server-local prerequisites

Create the structured operator allowlist without printing its contents. The
real file has exactly one enabled owner for Phase 1 and uses the schema in
`config/operators.json`:

```text
getent group argus-control >/dev/null || sudo groupadd --system argus-control
sudo install -d -m 0770 -o oreo -g argus-control /srv/argus/runtime/argus/m5/agents
sudo install -d -m 0750 -o root -g argus-control /etc/argus/domain-keys
sudo install -m 0600 -o root -g root \
  /path/to/operators.json /etc/argus/operators.json
sudo sh -c 'umask 0027; printf "ARGUS_OPERATOR_PROXY_TOKEN=%s\n" \
  "$(openssl rand -base64 48 | tr "+/" "-_" | tr -d "=\\n")" \
  > /etc/argus/operator-proxy-token'
sudo chown root:root /etc/argus/operator-proxy-token
sudo chmod 0600 /etc/argus/operator-proxy-token
sudo /srv/argus/scripts/argus-m5-runtime-permissions
```

Never paste either credential into a command argument, issue, PR, or shell
transcript. The API stores only SHA-256 hashes of session and CSRF values in
`/var/lib/argus/control/session.sqlite3`, mode `0600`.

The runtime permission reconciliation is required before starting the API or
agents. It safely upgrades the durable operation ledger and its sidecars to
`oreo:argus-control` mode `0660`, so domain agents can persist state
transitions without making the ledger world-readable. The separate API-owned
session database and its sidecars remain mode `0600`.

Create one independent random 32-byte-or-longer capability key for every active
domain. Do not copy, print, or commit key material. Ownership must let only the
matching agent identity read its key. Current active domains require:

```text
legacy-rootful
personal-sandbox
```

Install each key mode `0400`, owned by its agent Unix identity (`oreo` for
`legacy-rootful`, `argus-personal-sandbox` for `personal-sandbox`). The
management API identity and `argus-control` group must not be able to read
either key.

The non-legacy service template maps `personal-sandbox` to the existing
`argus-personal-sandbox` Unix identity. The legacy compatibility unit runs as
the existing `oreo` operator identity while retaining the same typed contract.
Non-legacy agents derive their rootless engine socket from the reviewed domain
contract (`/var/lib/argus/<domain>/docker.sock`) and explicitly make the host
rootful Docker sockets inaccessible.

## Reviewed activation

All commands run on `oreochiserver` after the PR merges.

1. Back up `/etc/caddy/Caddyfile` and affected systemd units.
2. Install the reviewed files under `/srv/argus`.
3. Generate the dashboard:

   ```text
   python3 /srv/argus/control-plane/dashboard/generate_dashboard.py
   ```

4. Generate `caddy/dashboard.Caddyfile` and merge the reviewed loopback route
   into `/etc/caddy/Caddyfile`. Do not replace unrelated routes.
5. Run the session-boundary preflight. It refuses stale headers, unsafe
   server-local file modes, an enabled Funnel, or invalid Caddy:

   ```text
   sudo /srv/argus/scripts/argus-m5-session-boundary --preflight
   ```

6. Apply the reviewed API unit and Caddy environment drop-in:

   ```text
   sudo /srv/argus/scripts/argus-m5-session-boundary \
     --apply --acknowledge-m5-session-boundary
   ```

   The script backs up the Caddyfile, affected units, and prior session
   database; validates Caddy before reload; restarts only the API; reloads
   Caddy; and verifies direct loopback requests fail closed. It does not change
   a route, listener, workload, Funnel, DNS record, or firewall policy.

7. Inspect `tailscale serve status --json` and `tailscale funnel status`.
   Refuse activation if any Argus Funnel route exists.
8. After checking the server's installed Tailscale CLI help, configure the
   reserved tailnet-only dashboard route:

   ```text
   tailscale serve --bg --yes --https=8448 http://127.0.0.1:8088
   ```

   Confirm the resulting URL is
   `https://oreochiserver.tail0a3a58.ts.net:8448`. Do not use a Funnel command.

## Acceptance evidence

Record only secret-safe results:

```text
python3 -m unittest discover -s tests -v
python3 -m json.tool config/operators.json
systemctl is-active argus-control-api.service
systemctl is-active argus-domain-agent-legacy-rootful.service
systemctl is-active argus-domain-agent@personal-sandbox.service
ss -ltn
tailscale serve status --json
tailscale funnel status
```

From a user-owned tailnet device, verify session exchange, expiry, logout,
CSRF double-submit rejection, Origin rejection, direct identity-header
rejection, immediate operator disablement, and a step-up-gated approval.
Exercise health, sanitized logs,
restart, backup, and `none`/`local`/`tailnet` access only where the manifest and
policy report them eligible. Confirm:

- create/apply returns `202` plus a durable operation ID;
- refresh resumes the latest operation state;
- duplicate idempotency keys return the same operation;
- a conflicting mutation returns `409`;
- disabled actions show the exact policy reason;
- no public listener, route, Funnel, Cloudflare tunnel, DNS record, router
  port, PostgreSQL exposure, or Docker socket exposure was added.

If any server check cannot be completed safely, leave the pull request open and
record the blocker rather than claiming Phase 1 complete.
