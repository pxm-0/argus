# Implementation Plan: Argus P0

## Phase 0: Discovery Only

Run read-only discovery. Do not edit files, install packages, restart services, start tunnels, or expose anything.

Collect:

- hostname and user
- Tailscale IP/status
- Docker containers/networks/volumes
- Docker Compose projects
- Compose labels and working directories
- current listening ports
- Caddy status
- Git version and existing repo state
- cloudflared version/service/config hints
- existing workload directories
- current health URLs where known

Deliverable:

```text
docs/DISCOVERY.md
```

## Phase 1: Git-Tracked Base Layout

Create `/srv/argus` and initialize a local Git repo.

Create directories:

```text
config/
config/schemas/
workloads/
control-plane/dashboard/public/
control-plane/api/
control-plane/monitoring/
cloudflare/
scripts/
systemd/
runtime/
runtime/metrics-history/
runtime/migration-backups/
docs/
```

Create:

- `.gitignore`
- `.gitattributes`
- `README.md`
- `AGENTS.md`
- `docs/GIT.md`
- `docs/SECURITY.md`
- `docs/MIGRATION.md`

Commit:

```text
Initialize Argus repo
```

## Phase 2: Neutral Registries

Create:

```text
config/workloads.json
config/access.json
config/privacy.json
config/policy.json
config/routes.json
config/exposure.json
config/monitoring.json
```

Validate each file:

```bash
python3 -m json.tool <file> >/dev/null
```

Commit:

```text
Add neutral workload and access registries
```

## Phase 3: Workload Migration Planning

Create:

```text
scripts/argus-migrate-workload-plan
```

This command prints a safe migration plan. It must not move files or restart workloads.

Commit:

```text
Add workload migration planning
```

## Phase 4: Optional Manual Workload Organization

Move selected workloads one at a time into:

```text
/srv/argus/workloads/<id>/source
```

Only after:

1. current Compose project name is known
2. bind mounts and named volumes are known
3. source is copied
4. Compose validates from the new path
5. rollback path exists

Commit only safe files:

- workload `README.md`
- workload `manifest.json`
- registry updates
- docs

Do not commit source, `.env`, runtime data, backups, or secrets.

Commit:

```text
Organize workloads under Argus
```

## Phase 5: Read-Only CLI

Create:

- `argus-inventory`
- `argus-workloads`
- `argus-health`
- `argus-open`
- `argus-doctor`
- `argus-git-checkpoint`
- `argus-events`

Symlink them into `/usr/local/bin`.

Commit:

```text
Add read-only Argus CLI
```

## Phase 6: Dashboard Generator

Create:

```text
control-plane/dashboard/generate_dashboard.py
```

Generate:

```text
control-plane/dashboard/public/index.html
control-plane/dashboard/public/style.css
control-plane/dashboard/public/app.js
```

Dashboard must show:

- workload cards
- health
- privacy state
- desired access
- effective access
- routes
- migration state
- Cloudflare plan state
- monitor toggle

Commit:

```text
Add private dashboard generator
```

## Phase 7: Monitoring

Create:

```text
control-plane/monitoring/collect_metrics.py
systemd/argus-metrics.service
systemd/argus-metrics.timer
scripts/argus-monitor
```

Collector writes:

```text
control-plane/dashboard/public/metrics.json
```

The dashboard fetches `metrics.json` only when the monitor panel is open.

Commit:

```text
Add btop-style monitoring
```

## Phase 8: Local Control API

Create:

```text
control-plane/api/server.py
systemd/argus-control-api.service
```

Bind only to:

```text
127.0.0.1:8099
```

Token file:

```text
/etc/argus/control-token
```

Never commit or print the token.

Commit:

```text
Add dashboard control API
```

## Phase 9: Access Controller

Create:

```text
scripts/argus-access-preview
scripts/argus-access-apply
scripts/argus-privacy-set
```

Behavior:

- preview policy decisions before applying
- mutate `privacy.json` only for privacy changes
- mutate `access.json.desired` first for access changes
- update `effective` only after apply succeeds
- write audit events
- regenerate dashboard
- never start Cloudflare in P0 unless explicitly overridden by a future task

Commit:

```text
Add policy-driven access controller
```

## Phase 10: Cloudflare Planning

Create:

```text
cloudflare/README.md
cloudflare/cloudflared-config.template.yml
cloudflare/planned-ingress.yml
cloudflare/generate_cloudflare_config.py
cloudflare/quick-tunnel-notes.md
scripts/argus-cloudflare-plan
docs/CLOUDFLARE.md
```

P0 generates plans only.

Commit:

```text
Add Cloudflare exposure planning
```

## Phase 11: Private Caddy Route

Configure Caddy to serve the dashboard on port `8088`, bound to the Tailscale IP.

Back up Caddyfile first.

Validate:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

Reload only if validation passes:

```bash
sudo systemctl reload caddy
```

Commit docs/config example:

```text
Add private Caddy dashboard route
```

## Phase 12: Smoke Test

Create:

```text
scripts/smoke-test
```

Symlink:

```text
/usr/local/bin/argus-smoke-test
```

Smoke test checks:

- Git repo exists
- JSON configs valid
- dashboard generated
- API binds locally
- Caddy validates
- metrics collector works
- Cloudflare plan generated
- no Tailscale Funnel detected
- no cloudflared service active unless explicitly expected
- no tracked secrets
- CLI commands work

Commit:

```text
Add Argus smoke test
```
