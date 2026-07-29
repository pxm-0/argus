# Argus M5 Phase 1 Runbook

Phase 1 replaces reusable browser bearer authentication with a verified
Tailscale identity plus a short-lived Argus session, and routes routine
operations through durable typed-operation agents.

## Boundaries

- Tailscale Serve is the only remote entry point. Funnel stays disabled.
- Caddy listens only on `127.0.0.1:8088`.
- The API listens only on `127.0.0.1:8099`.
- `/etc/argus/operators.json`, `/etc/argus/operator-proxy-token`, and the
  issuer key are server-local and never committed.
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
`/var/lib/argus/control/session.sqlite3`, mode `0600`. Schema version 3
reserves the idempotency key for the originating session before persisting
operation intent, then binds the resulting operation ID. Approval and
cancellation reject a replacement session even when it belongs to the same
operator identity, including across an API crash between intent creation and
operation-ID binding.

The runtime permission reconciliation is required before starting the API or
agents. It safely upgrades the durable operation ledger and its sidecars to
`argus-worker:argus-control` mode `0660` at
`/var/lib/argus/control/operations.sqlite3`, so the API and domain agents can
persist state transitions without making the ledger world-readable. The
separate API-owned session database and its sidecars remain mode `0600`.

The separate capability issuer owns one Ed25519 private key at
`/etc/argus/capability-issuer/ed25519.key`, mode `0600`. Neither the API, worker,
nor any domain agent can read it. Current and previous public keys may be
distributed to each active domain for a ten-minute rotation overlap. Current
active domains are:

```text
legacy-rootful
personal-sandbox
```

The reviewed activation creates the private key without printing it and
installs only `issuer.pub` below `/etc/argus/domains/<domain>/`. Issuance stops
if any distributed public key does not match the active private key.

The non-legacy service template maps `personal-sandbox` to the existing
`argus-personal-sandbox` Unix identity. The legacy compatibility unit runs as
the existing `oreo` operator identity while retaining the same typed contract.
Non-legacy agents derive their rootless engine socket from the reviewed domain
contract (`/var/lib/argus/<domain>/docker.sock`) and explicitly make the host
rootful Docker sockets inaccessible.

## Reviewed activation

All commands run on `oreochiserver` after the reviewed branch is staged and
before merge. The secret-safe acceptance evidence is attached to the PR before
it leaves draft.

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

## Durable ledger and worker activation

The API persists intent and approval but never opens an agent socket or starts
a dispatch thread. `argus-operation-worker.service`, running as the locked
`argus-worker` identity, is the only process that claims queued work. It sends
only an operation ID to the matching domain agent and has no Docker socket.

After the reviewed ledger/worker PR is staged, run the read-only preflight:

```text
sudo /srv/argus/scripts/argus-m5-ledger-worker --preflight
```

The preflight refuses unresolved operations, two competing ledger locations,
invalid units, or API/worker runtime-socket access. It prints counts only and
does not print operation contents.

Apply with the explicit acknowledgement:

```text
sudo /srv/argus/scripts/argus-m5-ledger-worker \
  --apply --acknowledge-m5-ledger-worker
```

The apply path:

- backs up the old and new SQLite locations plus all affected units;
- stops the API first, then the worker and agents, rechecks that no operation
  became unresolved, and takes the final consistent SQLite backups;
- creates `argus-worker` as a locked system identity if absent;
- migrates the ledger under SQLite `BEGIN IMMEDIATE` with a pre-version backup;
- installs and starts the worker before the API and agents;
- verifies schema version, events, ownership, service state, socket denial,
  unresolved-operation count, and direct-API rejection;
- retires the old runtime ledger into the root-only backup directory;
- restores prior units, databases, enablement, and service states on failure.

It does not change Caddy, Tailscale Serve, Funnel, a route, listener, workload,
DNS record, or firewall rule.

## Capability issuer and agent activation

After the ledger worker is active, run:

```text
sudo /srv/argus/scripts/argus-m5-capability-issuer --preflight
sudo /srv/argus/scripts/argus-m5-capability-issuer \
  --apply --acknowledge-m5-capability-issuer
```

The apply path backs up affected units and key paths, stops the API before the
worker and agents, refuses unresolved operations, creates a locked
`argus-issuer` identity, generates or preserves the Ed25519 private key,
distributes only its public key, and restarts the worker, issuer, agents, and
API in dependency order. Agent sockets move to the deterministic
`/run/argus/domains/<domain>/agent.sock` contract with exact owner, group, mode,
and typed `agent.status` verification. Agents persist capability IDs and nonces
in domain-local mode-`0600` SQLite before executing.

The API and worker never read the signing key. Messages are canonical JSON in a
four-byte length-prefixed frame capped at 64 KiB; arbitrary shell, Compose
arguments, and Docker API requests remain impossible.

## Private workload inspector activation

After the reviewed workload-inspector branch is staged on `oreochiserver`, and
before merge, regenerate the static surface and rerun the idempotent
session-boundary activation:

```text
python3 /srv/argus/control-plane/dashboard/generate_dashboard.py
sudo /srv/argus/scripts/argus-m5-session-boundary --preflight
sudo /srv/argus/scripts/argus-m5-session-boundary \
  --apply --acknowledge-m5-session-boundary
```

The API restart performs the backed-up session-database schema upgrade. Verify
that preview results show policy reason, revision, digest, expected impact,
health checks, and rollback behavior; disabled controls show their exact
blockers; and an in-flight operation returns after a browser refresh. The raw
response stays behind the technical-details disclosure.

## Acceptance evidence

Record only secret-safe results:

```text
python3 -m unittest discover -s tests -v
python3 -m json.tool config/operators.json
systemctl is-active argus-control-api.service
systemctl is-active argus-operation-worker.service
systemctl is-active argus-capability-issuer.service
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
