# Oreo Cloud P1 - Workload Operations and Organization

Status: Draft for implementation
Owner: Oreo
Target system: `oreochiserver`
Depends on: Oreo Cloud P0 complete
Default access model: Tailscale-private
Default exposure model: no public exposure unless explicitly approved

---

## 1. Executive Summary

P0 established Oreo Cloud as a private, Git-tracked personal ECS-style control plane.

P1 turns that foundation into a useful daily operations platform.

The main goal of P1 is to organize real workloads under the Oreo Cloud structure, add safe operational commands, improve the dashboard for workload management, introduce backup/restore planning, and test Cloudflare protected access only on approved low-risk workloads.

P1 must preserve the core P0 security model:

- Workloads are neutral by default.
- Privacy state lives in `config/privacy.json`.
- Access state lives in `config/access.json`.
- Policy guardrails live in `config/policy.json`.
- Desired access and effective access remain separate.
- Dashboard mutations require authenticated admin mode.
- Tailscale remains the default private access path.
- Cloudflare remains opt-in per workload.
- No sensitive, restricted, infrastructure, database, admin, or company workload becomes public by accident.

P1 should not turn Oreo Cloud into Kubernetes, a full CI/CD platform, or a public hosting system. It should make the current personal ECS box more organized, safer to operate, and easier to use from a phone or laptop.

---

## 2. Current P0 Baseline

P1 assumes the following are already true:

- `/srv/oreo-cloud` exists.
- `/srv/oreo-cloud` is a Git repo.
- GitHub PR-per-phase workflow exists and is enforced.
- P0 discovery report is merged.
- Base repo layout is merged.
- Neutral workload/access/privacy/config registries are merged.
- Migration planner exists.
- Read-only CLI exists.
- Private dashboard generator exists.
- Monitoring collector and systemd timer exist.
- Local-only control API exists and is running.
- Access controller CLI exists.
- Cloudflare plan-only generator exists.
- Private Caddy dashboard route exists and is installed.
- Smoke test passes live.
- `oreo-control-api.service` is active.
- `oreo-metrics.timer` is active.
- API listens only on `127.0.0.1:8099`.
- Caddy validates.
- Tailscale Funnel is disabled.
- `oreo-cloud-smoke-test` passes with `0 failure(s), 0 warning(s)`.

P1 must begin by re-verifying this baseline before changing anything.

---

## 3. P1 Goals

### 3.1 Primary Goals

1. Move selected workloads into the canonical Oreo Cloud workload layout.
2. Preserve Docker Compose project names, volumes, bind mounts, and health behavior during moves.
3. Add safe workload operation commands.
4. Improve the dashboard so it becomes the normal home for workload status and access control.
5. Add backup and restore planning per workload.
6. Add policy-gated restart and logs actions for approved workloads.
7. Add Cloudflare protected access for one low-risk demo workload only, if a suitable workload exists.
8. Strengthen auditability, smoke tests, and rollback documentation.

### 3.2 Secondary Goals

- Make workload cards more useful on mobile.
- Surface migration state clearly.
- Add event history to the dashboard.
- Add CLI and dashboard previews before any risky operation.
- Improve GitHub issue hygiene for P1.
- Create repeatable patterns for future workloads.

---

## 4. Non-Goals

P1 should not implement:

- Kubernetes.
- Full CI/CD.
- Browser terminal.
- Browser shell access.
- Public admin panel.
- Public Oreo Cloud dashboard.
- Public Uptime Kuma.
- Public PostgreSQL.
- Public Docker socket.
- Tailscale Funnel.
- Automatic public exposure.
- Automatic Cloudflare DNS mutation without explicit approval.
- Automatic destructive workload migration without preview and rollback.
- Secrets manager.
- Multi-user RBAC.
- Full app marketplace.
- Fully automated app discovery.
- Browser-based deploy buttons for sensitive workloads.

---

## 5. Hard Safety Rules

Codex and all implementation work must follow these rules:

1. Do not expose the Oreo Cloud dashboard publicly.
2. Do not expose the control API publicly.
3. Do not enable Tailscale Funnel.
4. Do not expose PostgreSQL.
5. Do not expose the Docker socket.
6. Do not expose SSH through Cloudflare.
7. Do not commit workload source code unless explicitly approved.
8. Do not commit company source code.
9. Do not commit `.env` files.
10. Do not commit secrets, tokens, keys, certs, database files, dumps, runtime data, backups, or Cloudflare credentials.
11. Do not move more than one workload at a time.
12. Do not migrate a workload without a migration plan.
13. Do not restart a workload without explicit migration or operation approval.
14. Preserve Docker Compose project names during migration and operations.
15. Preserve named Docker volumes.
16. Preserve old workload paths with symlinks when useful.
17. Run smoke tests after each phase.
18. Use Git branches and PRs for each phase.
19. Desired access may change before effective access changes.
20. Effective access changes only after policy validation and successful apply.
21. Sensitive and restricted workloads cannot become `cloudflare-public` unless policy is explicitly changed.
22. Cloudflare protected access must require an auth/access layer unless the workload is explicitly approved as public.
23. All mutations must write audit events.

---

## 6. P1 Product Requirements

### 6.1 Workload Organization

Oreo Cloud should become the canonical organizational home for workloads.

Canonical layout:

```text
/srv/oreo-cloud/workloads/<workload-id>/
├── README.md
├── manifest.json
├── source/        # ignored by Oreo Cloud Git by default
├── data/          # ignored
├── env/           # ignored
├── backups/       # ignored
└── runtime/       # ignored
```

The source directory may contain a standalone app repo, Docker Compose files, service code, or a symlink into an external app repo.

Oreo Cloud Git should track only safe metadata unless explicitly directed otherwise:

- `README.md`
- `manifest.json`
- optional templates
- docs
- config registries

Oreo Cloud Git should not track:

- workload source code by default
- company code
- `.env` files
- secrets
- runtime data
- database files
- logs
- backups
- generated metrics
- Cloudflare credentials

### 6.2 Workload Operations

P1 should add safe operational commands:

```bash
oreo-logs <workload-id>
oreo-restart-preview <workload-id>
oreo-restart <workload-id>
oreo-backup-plan <workload-id>
oreo-backup-run <workload-id>
oreo-restore-plan <workload-id>
oreo-workload-status <workload-id>
```

Initial operations should be CLI-first. Dashboard buttons may be added only for read-only views or policy-gated authenticated actions.

### 6.3 Dashboard Improvements

Dashboard should become the default daily view.

Each workload card should show:

- name
- workload ID
- lifecycle
- runtime type
- migration status
- privacy state
- desired access
- effective access
- health
- local URL
- tailnet URL
- Cloudflare URL, if planned or active
- backup status
- last operation
- last audit event
- open link
- logs action, if allowed
- restart preview action, if allowed

Dashboard must remain mobile-friendly.

### 6.4 Monitoring Improvements

The P0 btop-style monitor remains toggleable.

P1 should add:

- container CPU/memory display where available
- per-workload container grouping
- stale metrics warning
- service status summary
- last metrics collection timestamp
- lightweight historical trend file, if already supported safely

Monitoring must not expose:

- environment variables
- command-line arguments
- tokens
- secrets
- `.env` contents
- container inspect output containing secrets

### 6.5 Backup and Restore Planning

Each workload should have a backup policy in its manifest.

Backup planning should answer:

- Is source backed up?
- Are env files backed up?
- Are named Docker volumes backed up?
- Are bind mounts backed up?
- Is there a database?
- How is the database dumped?
- Where are backups stored?
- Are backups encrypted?
- How is restore tested?

P1 does not need to implement a perfect backup system, but every migrated workload should have a documented backup plan.

### 6.6 Cloudflare Protected Access

Cloudflare remains disabled by default.

P1 may test Cloudflare protected access for one approved low-risk workload.

Rules:

- Do not use Intake OS as the first Cloudflare test.
- Do not use Uptime Kuma as the first Cloudflare test.
- Do not use the Oreo Cloud dashboard as the first Cloudflare test.
- Do not expose PostgreSQL, Docker socket, SSH, admin dashboards, or company workloads.
- Use a low-risk demo workload only.
- Prefer `cloudflare-protected` over `cloudflare-public`.
- Require policy approval before effective access changes.
- Keep desired and effective access separate.
- Update audit log.
- Update smoke test to detect accidental public exposure.

---

## 7. User Stories

### 7.1 Workload Organization

As the operator, I want workloads organized under `/srv/oreo-cloud/workloads` so that the server is understandable and maintainable.

Acceptance:

- A workload has a canonical root.
- A workload has a manifest.
- Old paths still work if compatibility symlink is created.
- Docker Compose project name is preserved.
- Health checks pass after migration.

### 7.2 Safe Logs

As the operator, I want to view logs by workload ID without remembering container names.

Acceptance:

- `oreo-logs <id>` works for approved workloads.
- Unknown workload IDs are rejected.
- Restricted workloads require confirmation or policy approval.
- Logs do not reveal `.env` files by design.
- Log access writes an audit event if configured.

### 7.3 Safe Restart

As the operator, I want to restart a workload by ID with confirmation and health verification.

Acceptance:

- `oreo-restart-preview <id>` shows what would happen.
- `oreo-restart <id>` requires exact workload ID confirmation.
- Restart uses the preserved Compose project name.
- Health check runs after restart.
- Audit event is written.
- Failure path is clear.

### 7.4 Dashboard Operations

As the operator, I want the dashboard to show workload status, access state, privacy state, and operations clearly from my phone.

Acceptance:

- Dashboard loads over Tailscale.
- Dashboard remains view-only without admin token.
- Admin mode can preview allowed operations.
- Sensitive operations require confirmation.
- No secrets appear in generated HTML or JS.

### 7.5 Cloudflare Protected Demo

As the operator, I want one low-risk demo workload to be reachable through Cloudflare protected access.

Acceptance:

- Workload is marked eligible in config.
- Policy allows protected access.
- Cloudflare ingress plan is generated.
- Effective state changes only after successful apply.
- Protected access is documented.
- Smoke test detects if disallowed workloads become exposed.

---

## 8. Architecture

### 8.1 P1 Architecture Overview

```text
Phone / Laptop
      |
      | Tailscale
      v
Caddy on oreochiserver
      |
      +-- static dashboard
      +-- /api/* -> 127.0.0.1:8099

Local control API
      |
      +-- reads registries
      +-- writes privacy/access desired state
      +-- calls policy previews
      +-- writes audit events

CLI controllers
      |
      +-- migration planning
      +-- logs
      +-- restart preview/apply
      +-- backup plan/run
      +-- Cloudflare plan/apply, if approved

Workloads
      |
      +-- docker compose projects
      +-- canonical roots under /srv/oreo-cloud/workloads/<id>
```

### 8.2 Config Ownership

```text
workloads.json  -> app identity, runtime, health, paths
privacy.json    -> privacy classification
access.json     -> desired/effective access
policy.json     -> guardrails and allowed transitions
routes.json     -> route definitions
exposure.json   -> Cloudflare/Tailscale provider planning
monitoring.json -> monitoring settings
```

### 8.3 Desired vs Effective Access

`desired` means what the operator requested.

`effective` means what is currently active.

Example:

```json
{
  "desired": "cloudflare-protected",
  "effective": "tailnet"
}
```

This means the operator requested Cloudflare protected access, but Oreo Cloud has not successfully applied it yet.

---

## 9. GitHub Workflow

P1 should follow the PR-per-phase workflow created in P0.

### 9.1 Branch Naming

Use branches like:

```text
p1/01-baseline-verification
p1/02-workload-manifest-schema
p1/03-migrate-first-workload
p1/04-logs-cli
p1/05-restart-cli
p1/06-backup-planning
p1/07-dashboard-v2
p1/08-cloudflare-protected-demo
p1/09-smoke-test-updates
```

### 9.2 Commit Rules

- Commit after each successful phase.
- Use small commits.
- Do not commit secrets.
- Do not commit runtime files.
- Do not use `git add .` unless `.gitignore` is verified and status is reviewed.
- Prefer targeted `git add`.

Safe add pattern:

```bash
git add README.md AGENTS.md .gitignore .gitattributes
git add config docs scripts systemd cloudflare control-plane
git add workloads/*/README.md workloads/*/manifest.json
```

### 9.3 PR Rules

Every PR should include:

- summary
- changed files
- test output
- smoke test output
- security notes
- rollback notes
- screenshots for dashboard changes, if possible

---

## 10. P1 Implementation Phases

## Phase 1 - Baseline Re-Verification

### Goal

Confirm P0 is still healthy before starting P1.

### Tasks

Run:

```bash
cd /srv/oreo-cloud
git status --short
oreo-cloud-smoke-test
systemctl is-active oreo-control-api.service
systemctl is-active oreo-metrics.timer
sudo caddy validate --config /etc/caddy/Caddyfile
tailscale funnel status || true
ss -tulpen | grep -E '8099|8088' || true
```

### Deliverables

Create:

```text
docs/P1_BASELINE.md
```

Include:

- Git state
- smoke test result
- service state
- Caddy validation
- Tailscale Funnel status
- listening ports
- known open P1 issues

### Acceptance Criteria

- Smoke test passes.
- API is local-only.
- Dashboard route is Tailscale-only.
- Funnel is disabled.
- No unexpected public exposure is found.

---

## Phase 2 - Workload Manifest Schema Upgrade

### Goal

Make workload manifests strong enough for operations, backups, and migration state.

### Tasks

Update or create manifest schema documentation:

```text
docs/WORKLOAD_MANIFEST.md
config/schemas/workload-manifest.schema.example.json
```

Each workload manifest should support:

```json
{
  "id": "demo-app",
  "name": "Demo App",
  "canonicalRoot": "/srv/oreo-cloud/workloads/demo-app",
  "sourcePath": "/srv/oreo-cloud/workloads/demo-app/source",
  "runtime": {
    "type": "docker-compose",
    "composePath": "/srv/oreo-cloud/workloads/demo-app/source/docker-compose.yml",
    "composeProject": "demo-app",
    "service": ""
  },
  "migration": {
    "status": "planned",
    "originalPath": "",
    "backupPath": "",
    "compatibilitySymlink": false,
    "migratedAt": "",
    "lastHealthCheck": ""
  },
  "operations": {
    "logsAllowed": false,
    "restartAllowed": false,
    "backupAllowed": false,
    "dashboardActionsAllowed": false
  },
  "backup": {
    "status": "planned",
    "source": false,
    "env": false,
    "namedVolumes": [],
    "bindMounts": [],
    "database": {
      "type": "none",
      "dumpCommand": "",
      "restoreCommand": ""
    },
    "destination": "/srv/oreo-cloud/runtime/backups/demo-app",
    "retention": "manual",
    "restoreTested": false
  },
  "security": {
    "trackedByOreoCloudGit": false,
    "notes": []
  }
}
```

### Acceptance Criteria

- Manifest schema docs exist.
- Existing manifests still validate manually.
- Registry and dashboard can read the new fields without breaking.

---

## Phase 3 - Workload Migration: First Low-Risk Workload

### Goal

Move one low-risk workload into the canonical layout to prove the pattern.

### Workload Selection Rules

Prefer a non-company, non-infra, low-risk workload.

Avoid as first migration:

- Intake OS
- Uptime Kuma
- PostgreSQL
- Oreo Cloud itself
- anything with critical data

### Required Pre-Migration Discovery

Run:

```bash
docker ps --format 'table {{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}\t{{.Label "com.docker.compose.project.config_files"}}' || true

docker inspect \
  --format '{{.Name}} {{range .Mounts}}{{.Type}}:{{.Source}}->{{.Destination}}; {{end}}' \
  $(docker ps -q) 2>/dev/null || true

find /home /srv -maxdepth 5 \
  \( -iname 'docker-compose*.yml' -o -iname 'docker-compose*.yaml' -o -iname 'compose.yml' -o -iname 'compose.yaml' \) \
  2>/dev/null | sort || true
```

Do not print `.env` contents.

### Migration Pattern

Use the migration planner first:

```bash
oreo-migrate-workload-plan <workload-id>
```

Then:

1. Copy old path to new path.
2. Create manifest.
3. Validate Compose at new path.
4. Stop old project only if cutover requires it.
5. Move old path to migration backup.
6. Create compatibility symlink.
7. Start using canonical Compose path with explicit project name.
8. Run health checks.
9. Update registries.
10. Regenerate dashboard.
11. Run smoke test.

### Acceptance Criteria

- First workload lives under `/srv/oreo-cloud/workloads/<id>/source`.
- Old path is preserved or documented.
- Compose project name is unchanged.
- Health check passes.
- Dashboard shows migration status.
- No source/env/runtime/backups are tracked by Oreo Cloud Git.

---

## Phase 4 - Workload Logs CLI

### Goal

Add safe log access by workload ID.

### Deliverable

Create:

```text
scripts/oreo-logs
```

Symlink:

```bash
sudo ln -sf /srv/oreo-cloud/scripts/oreo-logs /usr/local/bin/oreo-logs
sudo chmod +x /srv/oreo-cloud/scripts/oreo-logs
```

### Behavior

```bash
oreo-logs <workload-id>
oreo-logs <workload-id> --tail 100
oreo-logs <workload-id> --follow
```

Requirements:

- Read workload runtime config from `workloads.json` and manifest.
- Refuse unknown workload IDs.
- Use explicit Compose project name.
- Use configured Compose file path.
- Respect `operations.logsAllowed`.
- If logs are not allowed, print a clear message.
- Do not print env files.
- Do not call `docker inspect` by default.
- Write audit event if configured.

Example implementation behavior:

```bash
docker compose -f "$COMPOSE_PATH" -p "$PROJECT" logs --tail "$TAIL" "$SERVICE"
```

### Acceptance Criteria

- `oreo-logs <id>` works for approved workload.
- `oreo-logs unknown` exits nonzero.
- Logs are blocked for workloads where `logsAllowed=false`.
- Audit event is written when logs are viewed.

---

## Phase 5 - Workload Restart Preview and Apply

### Goal

Add safe restart operations for approved workloads.

### Deliverables

Create:

```text
scripts/oreo-restart-preview
scripts/oreo-restart
```

Symlink:

```bash
sudo ln -sf /srv/oreo-cloud/scripts/oreo-restart-preview /usr/local/bin/oreo-restart-preview
sudo ln -sf /srv/oreo-cloud/scripts/oreo-restart /usr/local/bin/oreo-restart
sudo chmod +x /srv/oreo-cloud/scripts/oreo-restart-preview
sudo chmod +x /srv/oreo-cloud/scripts/oreo-restart
```

### Preview Behavior

```bash
oreo-restart-preview <workload-id>
```

Print:

- workload ID
- name
- privacy state
- access state
- Compose file
- Compose project
- service
- current health
- restart allowed or blocked
- expected command
- post-restart health URL

Do not mutate anything.

### Apply Behavior

```bash
oreo-restart <workload-id>
```

Requirements:

- Refuse unknown workload.
- Check `operations.restartAllowed`.
- Check policy.
- Require exact workload ID confirmation.
- Use explicit Compose project name.
- Restart the configured service/project.
- Run health check after restart.
- Update audit log.
- Update dashboard state if needed.

### Acceptance Criteria

- Preview works without mutation.
- Restart is blocked when not allowed.
- Restart requires confirmation.
- Restart works for one approved low-risk workload.
- Health check runs after restart.
- Failure is reported clearly.

---

## Phase 6 - Backup and Restore Planning

### Goal

Document and partially automate backups per workload.

### Deliverables

Create:

```text
scripts/oreo-backup-plan
scripts/oreo-backup-run
scripts/oreo-restore-plan
docs/BACKUP_AND_RESTORE.md
```

Symlink:

```bash
sudo ln -sf /srv/oreo-cloud/scripts/oreo-backup-plan /usr/local/bin/oreo-backup-plan
sudo ln -sf /srv/oreo-cloud/scripts/oreo-backup-run /usr/local/bin/oreo-backup-run
sudo ln -sf /srv/oreo-cloud/scripts/oreo-restore-plan /usr/local/bin/oreo-restore-plan
sudo chmod +x /srv/oreo-cloud/scripts/oreo-backup-plan
sudo chmod +x /srv/oreo-cloud/scripts/oreo-backup-run
sudo chmod +x /srv/oreo-cloud/scripts/oreo-restore-plan
```

### Backup Plan Behavior

```bash
oreo-backup-plan <workload-id>
```

Print:

- source backup setting
- env backup setting
- named volumes
- bind mounts
- database type
- dump command, if configured
- destination
- retention
- restore status
- risks

No mutation.

### Backup Run Behavior

```bash
oreo-backup-run <workload-id>
```

P1 can implement this conservatively:

- only run if `backupAllowed=true`
- require confirmation
- create timestamped directory under runtime backups
- copy safe configured paths only
- do not back up secrets unless explicitly configured
- write audit event

### Acceptance Criteria

- Every migrated workload has a backup plan.
- Backup plan command works.
- Backup run is blocked unless explicitly allowed.
- Backups are not tracked by Git.
- Restore plan exists even if restore automation is not implemented.

---

## Phase 7 - Dashboard V2

### Goal

Make dashboard useful for daily workload operations.

### Tasks

Update dashboard generator and API to show:

- migration status
- backup status
- operation permissions
- last health check
- last audit event
- desired access
- effective access
- privacy state
- Cloudflare plan state
- logs availability
- restart availability

Add UI sections:

```text
Workloads
Monitor
Events
Access Plan
Backups
System
```

### Dashboard Modes

Unauthenticated mode:

- view workload cards
- view health
- open allowed links
- view monitor
- view non-sensitive events

Admin mode:

- change privacy
- preview access
- apply allowed access changes
- preview restart
- trigger allowed restart, if implemented
- view logs, if allowed

### Acceptance Criteria

- Dashboard works on phone.
- No secrets in generated HTML/JS.
- Admin token is not stored in localStorage.
- View-only mode cannot mutate config.
- Dashboard still works if API is unavailable, with degraded read-only output.

---

## Phase 8 - Event and Audit Improvements

### Goal

Make operations traceable.

### Deliverables

Create or improve:

```text
scripts/oreo-events
runtime/audit.log
docs/AUDIT.md
```

Audit events should be JSONL.

Example:

```json
{"timestamp":"2026-06-30T12:00:00Z","actor":"oreo","action":"restart","workloadId":"demo-app","result":"success","details":"health check passed"}
```

Events to record:

- privacy change
- access desired change
- access apply
- restart preview
- restart apply
- logs viewed
- backup plan viewed
- backup run
- migration plan
- migration cutover
- Cloudflare plan generation

### Acceptance Criteria

- `oreo-events` prints recent events.
- Dashboard can show recent non-sensitive events.
- Audit log is ignored by Git.
- Events do not contain secrets.

---

## Phase 9 - Cloudflare Protected Demo Workload

### Goal

Prove Cloudflare protected access on one approved low-risk workload.

### Preconditions

Proceed only if all are true:

- A low-risk demo workload exists.
- Workload privacy is `unclassified`, `personal`, or approved `internal`.
- Policy allows `cloudflare-protected`.
- Cloudflare provider is configured intentionally.
- Required hostname is configured.
- Cloudflare auth/access requirement is documented.
- Smoke test passes before change.

### Must Not Use

Do not use:

- Intake OS
- Uptime Kuma
- Oreo Cloud dashboard
- PostgreSQL
- Docker socket
- SSH
- admin dashboards
- restricted workloads
- sensitive workloads

### Tasks

1. Mark demo workload desired access as `cloudflare-protected`.
2. Run `oreo-access-preview`.
3. Generate Cloudflare ingress plan.
4. Validate planned ingress.
5. Apply only after explicit confirmation.
6. Update effective access only after successful verification.
7. Write audit event.
8. Run smoke test.

### Acceptance Criteria

- Protected demo workload is reachable only through approved protected access.
- No disallowed workload is exposed.
- Smoke test detects exposure state.
- Dashboard shows Cloudflare state correctly.

---

## Phase 10 - Smoke Test Expansion

### Goal

Make P1 behavior verifiable.

Update:

```text
scripts/smoke-test
```

Add checks:

- workload manifests valid
- no workload source tracked by Git unless explicitly allowed
- no `.env` tracked
- no runtime backup tracked
- no audit log tracked
- migration status valid
- backup plans exist for migrated workloads
- operations permissions valid
- restart commands exist
- logs command exists
- dashboard V2 generated
- API local-only
- Caddy still validates
- Funnel disabled
- Cloudflare plan does not expose blocked workloads
- effective access does not violate policy

### Acceptance Criteria

```bash
oreo-cloud-smoke-test
```

passes with:

```text
0 failure(s)
```

Warnings are allowed only if explicitly documented, but the final P1 closeout should aim for `0 warning(s)`.

---

## Phase 11 - P1 Closeout

### Goal

Close P1 cleanly.

### Deliverables

Create:

```text
docs/P1_CLOSEOUT.md
```

Include:

- completed phases
- migrated workloads
- operations added
- dashboard changes
- backup status
- Cloudflare status
- smoke test result
- known limitations
- P2 recommendations

Tag release:

```bash
git tag -a p1-complete -m "Oreo Cloud P1 complete"
```

Push tag only if appropriate:

```bash
git push origin p1-complete
```

### Acceptance Criteria

- P1 closeout doc exists.
- Final smoke test passes.
- GitHub P1 issues are closed or explicitly deferred.
- P2 backlog exists.

---

## 11. Config Updates

### 11.1 `workloads.json`

P1 should keep workloads neutral.

Example:

```json
{
  "version": 1,
  "workloads": [
    {
      "id": "demo-app",
      "name": "Demo App",
      "description": "Low-risk demo workload.",
      "lifecycle": "active",
      "kind": "web-app",
      "paths": {
        "root": "/srv/oreo-cloud/workloads/demo-app",
        "source": "/srv/oreo-cloud/workloads/demo-app/source",
        "manifest": "/srv/oreo-cloud/workloads/demo-app/manifest.json",
        "legacy": "/home/oreo/demo-app"
      },
      "runtime": {
        "type": "docker-compose",
        "composePath": "/srv/oreo-cloud/workloads/demo-app/source/docker-compose.yml",
        "composeProject": "demo-app",
        "service": ""
      },
      "network": {
        "localUrl": "http://127.0.0.1:8090",
        "internalPort": 8090
      },
      "health": {
        "enabled": true,
        "url": "http://127.0.0.1:8090/health",
        "expectedStatus": 200,
        "timeoutSeconds": 3
      },
      "actions": {
        "open": true,
        "health": true,
        "logs": true,
        "restart": true,
        "deploy": false,
        "accessToggle": true,
        "privacyToggle": true
      }
    }
  ]
}
```

### 11.2 `privacy.json`

Example:

```json
{
  "version": 1,
  "defaultPrivacy": "unclassified",
  "states": [
    "unclassified",
    "personal",
    "internal",
    "sensitive",
    "restricted"
  ],
  "workloads": {
    "demo-app": {
      "privacy": "unclassified",
      "reason": "Low-risk demo workload.",
      "updatedAt": "",
      "updatedBy": "oreo-cloud"
    }
  }
}
```

### 11.3 `access.json`

Example:

```json
{
  "version": 1,
  "defaultAccess": "tailnet",
  "states": [
    "none",
    "local",
    "tailnet",
    "cloudflare-protected",
    "cloudflare-public"
  ],
  "workloads": {
    "demo-app": {
      "desired": "tailnet",
      "effective": "tailnet",
      "urls": {
        "local": "http://127.0.0.1:8090",
        "tailnet": "http://oreochiserver:8090",
        "cloudflare": ""
      },
      "lastAppliedAt": "",
      "lastError": ""
    }
  }
}
```

### 11.4 `policy.json`

P1 should keep strong defaults:

```json
{
  "version": 1,
  "defaultDecision": "deny-public",
  "rules": {
    "allowDashboardPrivacyToggle": true,
    "allowDashboardAccessToggle": true,
    "requireConfirmationForRestart": true,
    "requireConfirmationForBackupRun": true,
    "requireConfirmationForCloudflareProtected": true,
    "requireConfirmationForCloudflarePublic": true,
    "requireSecondConfirmationForRestrictedPublic": true,
    "requireAuthForDashboardMutations": true,
    "allowRestrictedToCloudflarePublic": false,
    "allowSensitiveToCloudflarePublic": false,
    "allowRestrictedToCloudflareProtected": false,
    "allowSensitiveToCloudflareProtected": false,
    "allowInternalToCloudflareProtected": true,
    "allowUnclassifiedToCloudflarePublic": true,
    "allowTailnetForAll": true
  },
  "blockedTargets": [
    "postgres",
    "docker-socket",
    "host-ssh",
    "control-api",
    "oreo-dashboard",
    "uptime-kuma"
  ]
}
```

---

## 12. Dashboard V2 Requirements

### 12.1 Workload Card

Each card should render:

```text
Name
ID
Lifecycle
Runtime
Migration
Privacy
Desired access
Effective access
Health
Backup status
Last operation
URLs
Actions
```

### 12.2 Operation Buttons

Allowed buttons in view-only mode:

```text
Open
View details
Show monitor
```

Allowed buttons in admin mode, if policy allows:

```text
Change privacy
Preview access
Apply access
View logs
Preview restart
Restart
View backup plan
Run backup
```

### 12.3 Safety UI

Dangerous actions must show:

- current state
- requested state
- exact command or route impact
- policy decision
- confirmation phrase
- expected rollback

---

## 13. CLI Specification

### 13.1 `oreo-workload-status`

Usage:

```bash
oreo-workload-status <workload-id>
```

Shows:

- workload metadata
- privacy
- access
- migration
- health
- runtime
- backup status
- last event

### 13.2 `oreo-logs`

Usage:

```bash
oreo-logs <workload-id> [--tail N] [--follow]
```

Safe logs via Compose.

### 13.3 `oreo-restart-preview`

Usage:

```bash
oreo-restart-preview <workload-id>
```

No mutation.

### 13.4 `oreo-restart`

Usage:

```bash
oreo-restart <workload-id>
```

Requires confirmation and policy approval.

### 13.5 `oreo-backup-plan`

Usage:

```bash
oreo-backup-plan <workload-id>
```

No mutation.

### 13.6 `oreo-backup-run`

Usage:

```bash
oreo-backup-run <workload-id>
```

Requires confirmation and explicit allow flag.

### 13.7 `oreo-restore-plan`

Usage:

```bash
oreo-restore-plan <workload-id>
```

No mutation in P1.

---

## 14. Security Requirements

### 14.1 Files That Must Never Be Tracked

- `.env`
- `.env.*`
- `*.key`
- `*.pem`
- `*.p12`
- `*.pfx`
- Cloudflare credentials
- control API token
- runtime audit log
- runtime backups
- metrics output
- database dumps
- workload data directories
- workload source unless explicitly safe

### 14.2 Public Exposure Rules

P1 may create protected Cloudflare access for one low-risk workload, but must not expose:

- Oreo Cloud dashboard
- control API
- Uptime Kuma
- Intake OS
- PostgreSQL
- Docker socket
- SSH
- admin dashboards
- restricted workloads
- sensitive workloads

### 14.3 Dashboard API Rules

- API binds only to `127.0.0.1:8099`.
- API is exposed only via Tailscale-bound Caddy route.
- Mutations require admin token.
- Token is stored in `/etc/oreo-cloud/control-token`.
- Token is never committed.
- Token is never printed.
- Token is never written to generated HTML.
- Browser uses session storage only, not local storage.

---

## 15. Smoke Test Requirements

P1 smoke test must check:

```text
[ ] Git repo exists
[ ] working tree state is understandable
[ ] JSON configs validate
[ ] manifests validate
[ ] dashboard generates
[ ] metrics collector works
[ ] control API is active
[ ] control API is local-only
[ ] Caddy validates
[ ] Tailscale Funnel disabled
[ ] Cloudflare plan does not expose blocked workloads
[ ] access effective state does not violate policy
[ ] no .env tracked
[ ] no secrets tracked
[ ] no runtime backups tracked
[ ] no audit logs tracked
[ ] no workload source tracked unless explicitly allowed
[ ] migrated workloads have backup plans
[ ] logs CLI exists
[ ] restart preview CLI exists
[ ] restart CLI exists
[ ] backup plan CLI exists
[ ] events CLI exists
```

---

## 16. Rollback Requirements

Each phase must define rollback.

### 16.1 Migration Rollback

If migrated workload fails:

1. Stop new Compose project.
2. Remove compatibility symlink.
3. Restore old path from migration backup.
4. Start using old Compose file and same project name.
5. Mark migration as `rolled-back`.
6. Write audit event.
7. Run smoke test.

### 16.2 CLI Rollback

If a CLI breaks:

1. Revert PR or commit.
2. Remove symlink if needed.
3. Run smoke test.

### 16.3 Dashboard Rollback

If dashboard breaks:

1. Revert generator change.
2. Regenerate dashboard.
3. Reload Caddy only if config changed.
4. Run smoke test.

### 16.4 Cloudflare Rollback

If Cloudflare exposure is incorrect:

1. Disable ingress route.
2. Update effective access to previous state.
3. Validate no disallowed hostname routes remain.
4. Write audit event.
5. Run smoke test.

---

## 17. P1 Acceptance Criteria

P1 is complete when:

```text
[ ] P0 baseline re-verified
[ ] at least one low-risk workload migrated or migration intentionally deferred with reason
[ ] every migrated workload has README.md
[ ] every migrated workload has manifest.json
[ ] every migrated workload has backup plan
[ ] Compose project names preserved
[ ] named volumes preserved
[ ] old paths preserved or documented
[ ] workload source/env/data/backups ignored by Git
[ ] logs CLI works for approved workload
[ ] restart preview works
[ ] restart apply works for approved low-risk workload or is intentionally deferred
[ ] backup plan CLI works
[ ] backup run is blocked unless explicitly allowed
[ ] dashboard V2 shows migration, backup, privacy, access, and operation state
[ ] monitor toggle still works
[ ] audit events are written for operations
[ ] Cloudflare protected demo either completed or explicitly deferred
[ ] no disallowed workload is publicly exposed
[ ] control API remains local-only
[ ] Caddy remains valid
[ ] Tailscale Funnel remains disabled
[ ] smoke test passes
[ ] P1 closeout doc exists
[ ] P1 release tag exists locally
```

---

## 18. Codex Task Prompts

### Task 1 - P1 Baseline Verification

```text
You are working on Oreo Cloud P1.

Start with baseline verification only.

Run read-only checks:
- git status
- oreo-cloud-smoke-test
- oreo-control-api.service status
- oreo-metrics.timer status
- Caddy validation
- Tailscale Funnel status
- listening ports for 8088 and 8099

Do not edit files.
Do not restart services.
Do not expose anything.
Do not print secrets.

Create docs/P1_BASELINE.md with the results.
Open a PR for this phase.
```

### Task 2 - Workload Manifest Schema

```text
Create the P1 workload manifest schema documentation.

Add:
- docs/WORKLOAD_MANIFEST.md
- config/schemas/workload-manifest.schema.example.json

The schema must support migration, operations, backup, runtime, and security metadata.
Do not migrate workloads yet.
Do not edit service configs.

Run smoke test.
Open a PR.
```

### Task 3 - First Workload Migration

```text
Plan and migrate one low-risk workload into:
/srv/oreo-cloud/workloads/<id>/source

Do not choose Intake OS, Uptime Kuma, PostgreSQL, Oreo Cloud, or any sensitive workload as the first migration.

Steps:
1. Run migration planner.
2. Copy first.
3. Validate Compose from the new path.
4. Preserve Compose project name.
5. Preserve old path with symlink or document why not.
6. Run health checks.
7. Update manifest and registries.
8. Regenerate dashboard.
9. Run smoke test.

Do not commit source, env, runtime data, or backups.
Open a PR.
```

### Task 4 - Logs CLI

```text
Add safe logs CLI.

Create:
- scripts/oreo-logs

It must read workload config, respect operations.logsAllowed, use Compose project names, and refuse unknown workloads.

Do not expose logs in dashboard yet unless read-only and safe.
Run smoke test.
Open a PR.
```

### Task 5 - Restart Preview and Apply

```text
Add restart preview and restart apply CLI.

Create:
- scripts/oreo-restart-preview
- scripts/oreo-restart

Requirements:
- preview mutates nothing
- apply requires exact workload ID confirmation
- use explicit Compose project name
- check policy and operations.restartAllowed
- run health check after restart
- write audit event

Test only on approved low-risk workload.
Run smoke test.
Open a PR.
```

### Task 6 - Backup and Restore Planning

```text
Add backup and restore planning.

Create:
- scripts/oreo-backup-plan
- scripts/oreo-backup-run
- scripts/oreo-restore-plan
- docs/BACKUP_AND_RESTORE.md

Backup run must be blocked unless backupAllowed=true.
Backups must go under runtime paths ignored by Git.
Do not back up secrets unless explicitly configured.
Run smoke test.
Open a PR.
```

### Task 7 - Dashboard V2

```text
Upgrade dashboard for P1.

Show:
- migration status
- backup status
- operation permissions
- last health check
- last audit event
- desired access
- effective access
- privacy state
- Cloudflare plan state

Unauthenticated dashboard remains view-only.
Admin mode may preview allowed operations.
Do not expose secrets.
Run smoke test.
Open a PR.
```

### Task 8 - Audit Events

```text
Improve audit events.

Create or update:
- scripts/oreo-events
- docs/AUDIT.md

Audit events should be JSONL and must not contain secrets.
Record operations such as logs viewed, restart preview, restart apply, backup plan, backup run, migration, privacy changes, and access changes.
Run smoke test.
Open a PR.
```

### Task 9 - Cloudflare Protected Demo

```text
Plan Cloudflare protected access for one approved low-risk demo workload only.

Do not use:
- Intake OS
- Uptime Kuma
- Oreo Cloud dashboard
- PostgreSQL
- Docker socket
- SSH
- sensitive workloads
- restricted workloads

Use access desired/effective model.
Run access preview first.
Generate plan.
Apply only with explicit approval.
Run smoke test.
Open a PR.
```

### Task 10 - Smoke Test Expansion

```text
Expand oreo-cloud-smoke-test for P1.

Add checks for:
- manifests
- tracked secrets
- tracked source
- migration status
- backup plans
- operation scripts
- dashboard V2
- policy violations
- Cloudflare blocked workloads

Run final smoke test.
Open a PR.
```

### Task 11 - P1 Closeout

```text
Create docs/P1_CLOSEOUT.md.

Include:
- completed phases
- migrated workloads
- operation commands added
- dashboard changes
- backup status
- Cloudflare status
- final smoke test output
- known limitations
- P2 recommendations

Tag local release:
p1-complete

Open final PR or closeout issue.
```

---

## 19. Recommended P1 GitHub Issues

Create issues:

1. P1 baseline verification
2. Workload manifest schema upgrade
3. First low-risk workload migration
4. Logs CLI
5. Restart preview and apply CLI
6. Backup and restore planning
7. Dashboard V2
8. Audit/event improvements
9. Cloudflare protected demo workload
10. P1 smoke test expansion
11. P1 closeout

Labels:

```text
P1
oreo-cloud
infra
security
operations
```

Use extra labels as needed:

```text
migration
cloudflare
dashboard
backup
monitoring
cli
```

---

## 20. P2 Recommendations

P2 can include:

- Browser-based logs view.
- Browser-based restart for approved workloads.
- Deployment workflow.
- GitHub webhook deploys.
- Better backup automation.
- Restore drill automation.
- Cloudflare protected access for more workloads.
- Auth improvements.
- Role-based access.
- Notification hooks.
- Uptime Kuma API integration.
- Workload creation wizard.
- Internal Docker registry.
- CI runner integration.

---

## 21. Final P1 Definition

P1 is not about making everything public or fully automated.

P1 is complete when Oreo Cloud becomes the safe daily operating layer for the server:

- workloads are organized
- operations are policy-gated
- logs and restarts are safer
- backups are planned
- dashboard is useful from a phone
- Cloudflare is tested only where appropriate
- the platform remains private-first
- smoke tests prove the safety model still holds

