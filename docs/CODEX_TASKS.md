# Codex Task Prompts

Use these as separate Codex tasks. Do not give Codex the whole project as one vague instruction.

## Task 1: Discovery Only

```text
Perform read-only discovery for Argus P0.

Collect:
- hostname and user
- Tailscale IP/status
- Docker containers/networks/volumes
- Docker Compose projects
- Compose labels, working directories, config files
- container bind mounts and named volumes
- listening ports
- Caddy status
- Git version and existing /srv/argus state
- cloudflared version/service/config hints
- existing workload paths
- existing health URLs where inferable

Do not install packages.
Do not edit files.
Do not restart services.
Do not start tunnels.
Do not expose anything.
Do not print .env contents.
Write docs/DISCOVERY.md or /tmp/argus-discovery.md if the project root does not exist yet.
```

## Task 2: Create Git-Tracked Base Layout

```text
Create /srv/argus as a local Git repo on main.

Create directories:
config, config/schemas, workloads, control-plane/dashboard/public, control-plane/api, control-plane/monitoring, cloudflare, scripts, systemd, runtime, runtime/metrics-history, runtime/migration-backups, docs.

Create:
- .gitignore
- .gitattributes
- README.md
- AGENTS.md
- docs/GIT.md
- docs/SECURITY.md
- docs/MIGRATION.md

Do not configure Caddy.
Do not move workloads.
Do not expose anything.
Commit: Initialize Argus repo
```

## Task 3: Create Neutral Registries

```text
Create config files:
- workloads.json
- access.json
- privacy.json
- policy.json
- routes.json
- exposure.json
- monitoring.json

Workloads are agnostic by default.
workloads.json describes app identity/runtime only.
privacy.json stores classification.
access.json stores desired/effective access.
policy.json stores guardrails.
exposure.json stores provider capability/planning.

Use discovery results for real ports, Compose paths, and project names where known.
Validate all JSON with python3 -m json.tool.
Commit: Add neutral workload and access registries
```

## Task 4: Add Workload Migration Planner

```text
Create scripts/argus-migrate-workload-plan.

It should read workloads.json and print a safe plan to move one workload to /srv/argus/workloads/<id>/source.

It must show:
- current path
- target path
- compose file
- compose project name
- health URL
- legacy path
- bind mount risks
- named volume risks
- copy command
- validation command
- cutover command
- rollback command

It must not move files.
It must not restart services.
It must not edit configs.
Symlink it into /usr/local/bin.
Commit: Add workload migration planning
```

## Task 5: Optional Workload Organization

```text
Move selected workloads one at a time into /srv/argus/workloads/<id>/source.

Use copy-validate-cutover-rollback.
Preserve Compose project name with -p or COMPOSE_PROJECT_NAME.
Preserve named volumes.
Preserve old path as a symlink when useful.
Do not commit source, .env, secrets, runtime data, backups, or database files.
Run health checks after each move.
Rollback if health fails.
Commit only manifests, registry updates, and docs.
Commit: Organize workloads under Argus
```

## Task 6: Read-Only CLI

```text
Create scripts:
- argus-inventory
- argus-workloads
- argus-health
- argus-open
- argus-doctor
- argus-git-checkpoint
- argus-events

Symlink them into /usr/local/bin.
Use Python standard library where practical.
Do not require jq.
Do not print secrets.
Do not mutate services except git checkpoint when explicitly called.
Commit: Add read-only Argus CLI
```

## Task 7: Dashboard Generator

```text
Create control-plane/dashboard/generate_dashboard.py.

Generate:
- control-plane/dashboard/public/index.html
- control-plane/dashboard/public/style.css
- control-plane/dashboard/public/app.js

Dashboard must show workload cards, privacy state, desired access, effective access, health, routes, migration state, Cloudflare plan state, and monitor toggle.
No CDN. No remote fonts. No external JS.
Commit: Add private dashboard generator
```

## Task 8: Monitoring

```text
Create:
- control-plane/monitoring/collect_metrics.py
- systemd/argus-metrics.service
- systemd/argus-metrics.timer
- scripts/argus-monitor

Collector writes valid JSON to control-plane/dashboard/public/metrics.json.
Dashboard monitor panel is hidden by default and fetches metrics only while open.
Do not expose env vars, command-line args, docker inspect, tokens, or secrets.
Commit: Add btop-style monitoring
```

## Task 9: Control API

```text
Create local-only control API at control-plane/api/server.py.
Bind only to 127.0.0.1:8099.
Use token file /etc/argus/control-token.
Never commit or print the token.

Implement:
- GET /api/workloads
- GET /api/access
- GET /api/privacy
- POST /api/workloads/<id>/privacy
- POST /api/workloads/<id>/access/preview
- POST /api/workloads/<id>/access/apply
- GET /api/metrics
- GET /api/events

Create systemd/argus-control-api.service.
Commit: Add dashboard control API
```

## Task 10: Access Controller

```text
Create:
- scripts/argus-access-preview
- scripts/argus-access-apply
- scripts/argus-privacy-set

Behavior:
- preview policy decisions before apply
- update privacy.json for privacy changes
- update access.json desired first for access changes
- update effective only after successful apply
- write runtime/audit.log
- regenerate dashboard
- do not start Cloudflare in P0
- do not enable Tailscale Funnel
- block restricted/sensitive cloudflare-public unless policy explicitly allows
Commit: Add policy-driven access controller
```

## Task 11: Cloudflare Planning

```text
Create:
- cloudflare/README.md
- cloudflare/cloudflared-config.template.yml
- cloudflare/planned-ingress.yml
- cloudflare/generate_cloudflare_config.py
- cloudflare/quick-tunnel-notes.md
- scripts/argus-cloudflare-plan
- docs/CLOUDFLARE.md

Generate plans only.
Do not start cloudflared.
Do not create tunnels.
Do not create DNS.
Do not store tokens.
Commit: Add Cloudflare exposure planning
```

## Task 12: Private Caddy Dashboard Route

```text
Configure Caddy to serve dashboard on port 8088 bound to the Tailscale IP only.
Proxy /api/* to 127.0.0.1:8099.
Back up Caddyfile before editing.
Validate Caddy before reload.
Reload only if validation passes.
Do not enable Cloudflare.
Do not enable Funnel.
Do not expose public routes.
Commit docs/template change: Add private Caddy dashboard route
```

## Task 13: Smoke Test

```text
Create scripts/smoke-test and symlink as /usr/local/bin/argus-smoke-test.

Check:
- Git repo exists
- JSON configs valid
- dashboard generated
- API binds localhost only
- metrics collector works
- metrics.json valid
- Cloudflare plan generated
- no Funnel detected
- no unexpected cloudflared active
- no tracked secrets
- workload CLI works
- health CLI works
- Caddy validates

Commit: Add Argus smoke test
```
