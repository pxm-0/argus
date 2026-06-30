# Oreo Cloud P2 Specification

Status: draft for P2 execution
Target repo: `/srv/oreo-cloud`
Target branch model: GitHub PR-per-phase, merge to `main`, tag `p2-complete` at closeout
Baseline: P1 closeout verified on `oreochiserver` at `2026-06-30T18:56Z`

---

## 1. Executive Summary

P2 turns Oreo Cloud from an operational foundation into a safer daily-use platform.

P0 created the private control plane. P1 proved that the platform can manage a low-risk workload, show richer dashboard context, run safe operation commands, and plan Cloudflare protected access without exposing anything publicly.

P2 focuses on five outcomes:

1. Make operator commands usable everywhere with consistent symlinks and permissions.
2. Replace loose manifest checks with first-class validation.
3. Stop tracked dashboard artifacts from getting dirtied by runtime/event rendering.
4. Add a safe dashboard action layer for previews and approved operations.
5. Activate one real protected Cloudflare route for an approved demo workload, with Cloudflare Access required and effective access updated only after verification.

P2 should still be conservative. It should not convert Oreo Cloud into a public admin panel, general-purpose deployment system, or Kubernetes replacement.

---

## 2. P1 Baseline Assumptions

P2 assumes the following live state from P1:

```text
/srv/oreo-cloud exists and is a Git repo.
oreo-control-api.service is active.
oreo-metrics.timer is active.
API listens only on 127.0.0.1:8099.
Caddy validates.
Tailscale Funnel is disabled.
cloudflared is not active.
Cloudflare remains plan-only.
scripts/smoke-test passes with 0 failure(s), 0 warning(s).
```

P2 also assumes one migrated low-risk workload:

```text
Workload: hello-nginx
Canonical root: /srv/oreo-cloud/workloads/hello-nginx
Source path: /srv/oreo-cloud/workloads/hello-nginx/source
Legacy compatibility path: /srv/apps/hello-nginx
Runtime: Docker Compose project hello-nginx, service web
Health URL: http://127.0.0.1:18080
Migration status: migrated
Privacy: unclassified
Effective access: local
Desired access: cloudflare-protected
Cloudflare hostname in P1: hello-nginx.oreo-cloud.invalid
```

The P1 `.invalid` hostname is intentionally not reachable and must be replaced with a real hostname only in the Cloudflare activation phase.

---

## 3. P2 Goals

### 3.1 Operational Hygiene

Make the platform easier to operate from SSH and from the private dashboard.

Required:

```text
- all approved CLI commands available by short name
- symlink creation tracked by a repeatable install script
- smoke test validates symlink state
- operation permissions are consistent
```

### 3.2 Manifest Validation

Move from shape-only checks to explicit manifest validation.

Required:

```text
- manifest schema documented
- manifest validator implemented
- smoke test fails on invalid manifests
- migrated workloads must have valid manifests
```

### 3.3 Dashboard Runtime Cleanliness

Keep tracked static dashboard assets clean.

Required:

```text
- dashboard regeneration must not dirty tracked runtime/event output
- runtime events should come from API or ignored runtime files
- tracked index.html/style.css/app.js should only change when source changes
```

### 3.4 Safe Dashboard Action Layer

Add dashboard previews for operations without exposing raw shell access.

Required:

```text
- auth required for all mutations
- preview before apply
- no raw shell command execution from browser
- logs output sanitized and capped
- restart requires exact confirmation
- backup execution remains gated by manifest
- all operations write audit events
```

### 3.5 Backup Execution and Restore Test for an Approved Workload

Enable backup execution for one low-risk workload only.

Recommended initial workload:

```text
hello-nginx
```

Required:

```text
- manifest explicitly enables backup execution
- backup plan validates destination
- backup run produces a timestamped artifact
- restore plan is generated
- restore test is documented
```

### 3.6 Real Cloudflare Protected Demo Activation

Activate one protected Cloudflare route for one approved demo workload only.

Recommended initial workload:

```text
hello-nginx
```

Required:

```text
- named tunnel only
- credentials stored outside Git
- Cloudflare Access required
- no cloudflare-public state in P2
- no dashboard/Uptime Kuma/PostgreSQL/Docker exposure
- desired access and effective access reconciled after verification
```

---

## 4. P2 Non-Goals

Do not implement these in P2:

```text
- Kubernetes
- multi-node scheduling
- browser terminal
- generic shell execution
- unrestricted dashboard logs
- public unauthenticated Cloudflare routes
- Tailscale Funnel activation
- Cloudflare exposure for dashboard, Uptime Kuma, PostgreSQL, Docker socket, host SSH, or sensitive workloads
- automated migration of sensitive/company workloads
- automatic DNS/provider mutation without explicit operator approval
- automatic secret generation committed to Git
- high-availability cloudflared replicas beyond a basic documented path
```

---

## 5. Hard Safety Rules

Codex and operators must follow these rules:

```text
1. Do not enable Tailscale Funnel.
2. Do not expose the dashboard publicly.
3. Do not expose the control API publicly.
4. Do not expose Uptime Kuma publicly.
5. Do not expose PostgreSQL publicly.
6. Do not expose the Docker socket.
7. Do not expose host SSH through Cloudflare in P2.
8. Do not use cloudflare-public in P2.
9. Do not store Cloudflare tokens or credentials in Git.
10. Do not store control API tokens in Git.
11. Do not track .env files.
12. Do not track runtime metrics, backups, audit logs, or migration backups.
13. Do not display env vars or process command-line args in dashboard monitoring.
14. Do not display raw shell output in dashboard action responses.
15. Do not restart workloads from dashboard without preview, auth, policy validation, exact confirmation, and audit event.
16. Do not update effective access until apply and verification succeed.
```

---

## 6. Source-of-Truth Model

P2 keeps the P1 model:

```text
workloads.json  = neutral app/runtime identity
privacy.json    = current privacy classification
access.json     = desired/effective access state
policy.json     = transition guardrails
exposure.json   = provider capability and planning
routes.json     = actual/planned route information
manifest.json   = per-workload operational metadata
```

Workloads remain agnostic by default. Privacy and access are policy states controlled by Oreo Cloud.

---

## 7. P2 Access State Rules

Access states remain:

```text
none
local
tailnet
cloudflare-protected
cloudflare-public
```

P2 allowed effective states:

```text
none
local
tailnet
cloudflare-protected
```

P2 disallowed effective state:

```text
cloudflare-public
```

For Cloudflare activation:

```text
- desired may be cloudflare-protected
- effective may become cloudflare-protected only after named tunnel, ingress validation, Access protection verification, and external probe succeed
- effective must remain local or tailnet if verification fails
```

---

## 8. Privacy State Rules

Privacy states remain:

```text
unclassified
personal
internal
sensitive
restricted
```

P2 Cloudflare policy:

```text
unclassified -> cloudflare-protected allowed with confirmation
personal     -> cloudflare-protected allowed with confirmation
internal     -> cloudflare-protected allowed only if policy explicitly allows
sensitive    -> cloudflare-protected blocked by default
restricted   -> cloudflare-protected blocked by default
any          -> cloudflare-public blocked in P2
```

---

## 9. Target File Additions and Changes

P2 adds or updates these files:

```text
/srv/oreo-cloud/
├── docs/
│   ├── OREO_CLOUD_P2.md
│   ├── P2_BASELINE.md
│   ├── MANIFEST_SCHEMA.md
│   ├── DASHBOARD_RUNTIME.md
│   ├── DASHBOARD_ACTIONS.md
│   ├── BACKUP_EXECUTION.md
│   ├── CLOUDFLARE_ACTIVATION.md
│   ├── P2_CLOSEOUT.md
│   └── RUNBOOKS/
│       ├── cloudflare-protected-activation.md
│       ├── cloudflare-rollback.md
│       ├── backup-restore-test.md
│       └── dashboard-action-safety.md
│
├── config/
│   └── schemas/
│       ├── workload-manifest.schema.json
│       ├── access.schema.json
│       ├── privacy.schema.json
│       └── exposure.schema.json
│
├── scripts/
│   ├── install-operator-links
│   ├── validate-manifests
│   ├── validate-configs
│   ├── oreo-dashboard-state
│   ├── oreo-action-preview
│   ├── oreo-action-apply
│   ├── oreo-cloudflare-activate-preview
│   ├── oreo-cloudflare-activate
│   ├── oreo-cloudflare-rollback
│   └── smoke-test
│
├── control-plane/
│   ├── api/
│   │   └── server.py
│   └── dashboard/
│       ├── generate_dashboard.py
│       └── public/
│           ├── index.html
│           ├── style.css
│           └── app.js
│
├── cloudflare/
│   ├── activation-plan.yml
│   ├── generated-ingress.yml
│   └── README.md
│
└── runtime/
    ├── dashboard-state.json          # ignored
    ├── action-previews/              # ignored
    ├── backups/                      # ignored
    └── cloudflare-activation/         # ignored
```

---

## 10. Git Ignore Updates

Ensure these are ignored:

```gitignore
# Runtime dashboard state
runtime/dashboard-state.json
runtime/action-previews/
runtime/cloudflare-activation/

# Cloudflare credentials and runtime state
cloudflare/*.credentials.json
cloudflare/*token*
cloudflare/*secret*
/etc/cloudflared/
**/.cloudflared/

# Backup artifacts
runtime/backups/
workloads/*/backups/

# Control/API tokens
*.token
control-token

# Workload secrets and local data
workloads/*/source/.env
workloads/*/source/.env.*
workloads/*/env/
workloads/*/data/
workloads/*/runtime/
workloads/*/logs/
```

Do not use `git add .` during P2 unless `git status --short` has been reviewed and ignored paths verified.

---

## 11. GitHub Workflow

Every P2 phase gets:

```text
- one issue
- one branch
- one PR
- one smoke test or targeted verification note
- merge to main only after review
```

Branch naming:

```text
p2/00-closeout-baseline
p2/01-operator-links
p2/02-manifest-schema
p2/03-dashboard-runtime-cleanliness
p2/04-dashboard-action-layer
p2/05-backup-execution
p2/06-next-workload-migration
p2/07-cloudflare-protected-activation
p2/08-effective-access-reconcile
p2/09-smoke-expansion
p2/10-closeout
```

Commit style:

```text
P2-01 add operator link installer
P2-02 add manifest schema validation
P2-03 separate dashboard runtime state
P2-04 add safe dashboard action layer
P2-05 enable backup execution for hello-nginx
P2-07 activate protected Cloudflare demo route
```

---

## 12. Phase P2-00 — Baseline and Release Hygiene

### Goal

Start P2 from a clean P1-complete state.

### Tasks

```text
1. Confirm p1-complete tag exists on main.
2. Record live baseline in docs/P2_BASELINE.md.
3. Run smoke test.
4. Record service status.
5. Record current open issues and P2 labels.
6. Confirm no unexpected Git dirtiness.
```

### Commands

```bash
cd /srv/oreo-cloud
git checkout main
git pull --ff-only
git tag --list | grep p1-complete
scripts/smoke-test
git status --short
systemctl is-active oreo-control-api.service || true
systemctl is-active oreo-metrics.timer || true
systemctl is-active cloudflared || true
tailscale funnel status || true
ss -tulpen | grep -E '8099|8088|cloudflared|caddy' || true
```

### Deliverables

```text
docs/P2_BASELINE.md
```

### Acceptance Criteria

```text
[ ] p1-complete tag exists
[ ] smoke test passes at start of P2
[ ] control API still binds localhost only
[ ] dashboard route remains private
[ ] cloudflared is not unexpectedly active
[ ] Funnel remains disabled
```

---

## 13. Phase P2-01 — Operator Symlink Installer

### Goal

Make approved operation commands available by short name, repeatably and safely.

### Add Script

```text
scripts/install-operator-links
```

### Managed Symlinks

```text
/usr/local/bin/oreo-logs                  -> /srv/oreo-cloud/scripts/oreo-logs
/usr/local/bin/oreo-restart-preview       -> /srv/oreo-cloud/scripts/oreo-restart-preview
/usr/local/bin/oreo-restart               -> /srv/oreo-cloud/scripts/oreo-restart
/usr/local/bin/oreo-backup-plan           -> /srv/oreo-cloud/scripts/oreo-backup-plan
/usr/local/bin/oreo-backup-run            -> /srv/oreo-cloud/scripts/oreo-backup-run
/usr/local/bin/oreo-restore-plan          -> /srv/oreo-cloud/scripts/oreo-restore-plan
/usr/local/bin/oreo-events                -> /srv/oreo-cloud/scripts/oreo-events
/usr/local/bin/oreo-cloud-smoke-test      -> /srv/oreo-cloud/scripts/smoke-test
/usr/local/bin/oreo-access-preview        -> /srv/oreo-cloud/scripts/oreo-access-preview
/usr/local/bin/oreo-access-apply          -> /srv/oreo-cloud/scripts/oreo-access-apply
/usr/local/bin/oreo-cloudflare-plan       -> /srv/oreo-cloud/scripts/oreo-cloudflare-plan
```

### Behavior

```text
- must require sudo or root when writing /usr/local/bin
- must refuse to overwrite non-symlink files unless --force is provided
- must verify target exists and is executable
- must print all installed links
- must not alter workload configs
- must not restart services
```

### Smoke Additions

```text
PASS operator links exist
PASS operator link targets executable
PASS operator links do not point outside /srv/oreo-cloud/scripts
```

### Acceptance Criteria

```text
[ ] install-operator-links exists
[ ] all approved commands work by short name
[ ] smoke covers symlink state
[ ] no non-symlink file is overwritten
```

---

## 14. Phase P2-02 — First-Class Manifest Schema Validation

### Goal

Make workload manifests enforceable, not just documented.

### Add Schema

```text
config/schemas/workload-manifest.schema.json
```

### Required Manifest Fields

```text
id
name
schemaVersion
canonicalRoot
sourcePath
runtime.type
runtime.compose.project
runtime.compose.service
health.url
health.expectedStatus
migration.status
operations.logs.allowed
operations.restart.allowed
backup.backupAllowed
backup.restoreAllowed
security.publicAllowed
security.notes
```

### Enums

```text
schemaVersion: 1
runtime.type: docker-compose | external | static | unknown
migration.status: planned | migrated | external | rolled-back | skipped
privacyCompatibility: unclassified | personal | internal | sensitive | restricted
accessCompatibility: none | local | tailnet | cloudflare-protected | cloudflare-public
```

### Add Validator

```text
scripts/validate-manifests
```

### Validator Behavior

```text
- discover /srv/oreo-cloud/workloads/*/manifest.json
- validate JSON syntax
- validate required keys
- validate enum values
- validate path consistency
- validate no backup destination is outside approved runtime/backup roots unless explicitly allowed
- validate no publicAllowed true when privacy is sensitive/restricted
- exit nonzero on invalid manifest
- print concise errors with workload id and field path
```

No external Python packages are required. Use Python standard library.

### Example Output

```text
PASS hello-nginx manifest valid
FAIL demo-app manifest invalid: backup.destination missing
```

### Smoke Additions

```text
PASS workload manifests schema-valid
PASS workload manifest paths valid
PASS workload manifest operation policy valid
```

### Acceptance Criteria

```text
[ ] schema file exists
[ ] validate-manifests exists
[ ] hello-nginx manifest passes
[ ] smoke fails if a manifest is invalid
[ ] docs/MANIFEST_SCHEMA.md exists
```

---

## 15. Phase P2-03 — Dashboard Runtime Cleanliness

### Goal

Stop dashboard regeneration from dirtying tracked static artifacts when only runtime data changes.

### Current Problem

P1 notes that server-side regeneration can dirty tracked static artifacts because runtime events may be rendered into generated dashboard output.

### Target Model

```text
Tracked static assets:
- control-plane/dashboard/public/index.html
- control-plane/dashboard/public/style.css
- control-plane/dashboard/public/app.js

Ignored runtime state:
- runtime/dashboard-state.json
- runtime/events.json
- control-plane/dashboard/public/metrics.json if already ignored
```

### API Model

Add or update API endpoints:

```text
GET /api/dashboard-state
GET /api/events
GET /api/metrics
```

The dashboard should fetch dynamic state at runtime instead of embedding audit events in tracked HTML.

### Add Script

```text
scripts/oreo-dashboard-state
```

Behavior:

```text
- read workloads/access/privacy/routes/exposure/manifest/event data
- write runtime/dashboard-state.json
- redact secrets
- include last sanitized audit event per workload
- include migration status
- include backup status
- include operations status
- include effective/desired access
```

### Dashboard Generator Change

`generate_dashboard.py` should only generate static shell assets.

It should not embed:

```text
- audit event bodies
- runtime health snapshots
- runtime metrics
- action preview output
- Cloudflare activation runtime logs
```

### Acceptance Criteria

```text
[ ] generate_dashboard.py creates static assets only
[ ] runtime/dashboard-state.json is ignored by Git
[ ] dashboard loads dynamic state through API
[ ] running metrics/events/dashboard-state refresh does not dirty Git
[ ] smoke includes dashboard artifact cleanliness check
```

### Verification

```bash
cd /srv/oreo-cloud
git status --short
scripts/oreo-dashboard-state
python3 control-plane/dashboard/generate_dashboard.py
git status --short
```

Expected:

```text
No tracked file changes unless source files changed intentionally.
```

---

## 16. Phase P2-04 — Safe Dashboard Action Layer

### Goal

Expose safe operation previews through the private dashboard without exposing raw shell access.

### Add API Endpoints

```text
GET  /api/actions
POST /api/workloads/<id>/logs/preview
POST /api/workloads/<id>/restart/preview
POST /api/workloads/<id>/restart/apply
POST /api/workloads/<id>/backup/preview
POST /api/workloads/<id>/backup/apply
```

### Auth Rules

```text
- all POST endpoints require Authorization: Bearer <token>
- token file remains /etc/oreo-cloud/control-token
- token is never printed
- token is never embedded in HTML
- token is never stored in localStorage
- dashboard stores token in sessionStorage only
```

### Logs Preview

Allowed:

```text
- capped line count
- sanitized output
- service-specific logs only
- no env vars
- no docker inspect
- no host logs
```

Defaults:

```text
maxLines: 100
maxBytes: 65536
```

Sanitization:

```text
- redact lines containing obvious secret markers
- redact token-like key/value pairs
- strip terminal control sequences
- truncate long lines
```

### Restart Preview

Preview should show:

```text
- workload id
- compose project
- compose service
- current health
- command class, not raw shell string
- policy decision
- confirmation phrase
```

### Restart Apply

Requirements:

```text
- exact workload id confirmation
- operation allowed in manifest
- policy permits restart
- execute existing CLI or shared operation function
- run health check after restart
- write audit event
- update runtime dashboard state
```

### Backup Preview and Apply

Backup apply requirements:

```text
- backup.backupAllowed true in manifest
- destination under approved backup root
- sufficient free disk check
- backup plan exists
- exact workload id confirmation
- audit event written
```

### Dashboard UI

Each workload card may show:

```text
Operations
- View logs preview
- Restart preview
- Backup preview
```

Apply buttons should appear only in admin mode and only if policy allows.

### Acceptance Criteria

```text
[ ] unauthenticated users cannot call mutation endpoints
[ ] logs preview is capped and sanitized
[ ] restart preview does not mutate
[ ] restart apply requires exact confirmation
[ ] backup apply requires manifest backupAllowed true
[ ] all operations write audit events
[ ] dashboard never displays raw shell command strings
[ ] smoke tests API auth/mutation boundaries
```

---

## 17. Phase P2-05 — Backup Execution and Restore Test

### Goal

Enable backup execution for one approved low-risk workload and prove restore planning.

### Initial Workload

```text
hello-nginx
```

### Manifest Change

Set only for `hello-nginx`:

```json
{
  "backup": {
    "backupAllowed": true,
    "restoreAllowed": false,
    "destination": "/srv/oreo-cloud/runtime/backups/hello-nginx",
    "include": {
      "source": true,
      "env": false,
      "volumes": false,
      "database": false
    },
    "retention": {
      "keepLast": 5
    }
  }
}
```

### Backup Artifact Format

```text
/srv/oreo-cloud/runtime/backups/hello-nginx/YYYYMMDD-HHMMSS/
├── manifest.json
├── files.tar.gz
├── checksums.sha256
└── restore-plan.md
```

### Backup Run Behavior

```text
- validate manifest first
- refuse if backupAllowed false
- refuse if destination is not under /srv/oreo-cloud/runtime/backups/<id>
- create timestamped directory
- archive approved paths only
- do not include .env files unless explicitly allowed
- write checksums
- write audit event
```

### Restore Test

P2 does not need automated destructive restore into production.

Required restore test:

```text
- generate restore plan
- extract backup into temporary runtime restore-test directory
- verify expected files exist
- do not replace live workload
- document result in docs/RUNBOOKS/backup-restore-test.md
```

### Acceptance Criteria

```text
[ ] hello-nginx backupAllowed true
[ ] oreo-backup-run hello-nginx creates timestamped artifact
[ ] artifact excludes secrets/env files
[ ] checksum file exists
[ ] restore plan exists
[ ] restore test extraction documented
[ ] smoke validates backup artifact shape or latest backup presence
```

---

## 18. Phase P2-06 — Next Low-Risk Workload Migration

### Goal

Migrate one additional low-risk workload, if available, using the P1 migration model plus P2 manifest validation.

### Candidate Selection Criteria

Allowed candidate:

```text
- low-risk
- non-company
- non-admin
- no database or simple disposable data
- health endpoint or simple HTTP root check
- Docker Compose project name identifiable
- rollback path clear
```

Disallowed candidates:

```text
- Intake OS or company work
- Uptime Kuma
- PostgreSQL
- dashboards/admin panels
- anything with unclear volumes or database state
```

### Process

```text
1. Run discovery.
2. Run oreo-migrate-workload-plan <id>.
3. Create manifest before cutover.
4. Validate manifest.
5. Copy first.
6. Validate Compose from new path.
7. Preserve project name with -p or COMPOSE_PROJECT_NAME.
8. Cut over.
9. Health check.
10. Update registry/access/privacy/routes.
11. Run smoke test.
12. Document rollback notes.
```

Docker Compose project names must be preserved explicitly because Compose defaults are directory-dependent.

### Acceptance Criteria

```text
[ ] one additional low-risk workload migrated or documented as no suitable candidate
[ ] manifest validates
[ ] health check passes
[ ] old path symlink or rollback note exists
[ ] no source/env/runtime data tracked
[ ] smoke passes
```

If no suitable candidate exists, this phase may close with a documented deferral rather than forcing a risky migration.

---

## 19. Phase P2-07 — Real Cloudflare Protected Activation

### Goal

Activate one real protected Cloudflare route for `hello-nginx` using a named tunnel and Cloudflare Access.

### External Prerequisites

Operator must provide:

```text
- Cloudflare account access
- approved zone/domain
- intended hostname, e.g. hello-nginx.<real-domain>
- Cloudflare Access policy decision
- cloudflared installed or approved to install
- tunnel credentials stored outside Git
```

If these are not available, this phase must stop with a documented blocker. Do not substitute a public unauthenticated route.

### Explicitly Not Allowed

```text
- quick tunnel for P2 activation
- cloudflare-public
- dashboard hostname
- Uptime Kuma hostname
- PostgreSQL
- Docker socket
- host SSH
- sensitive/restricted workloads
```

### Config Updates

Update `access.json` for `hello-nginx`:

```json
{
  "desired": "cloudflare-protected",
  "effective": "local",
  "urls": {
    "local": "http://127.0.0.1:18080",
    "tailnet": "",
    "cloudflare": "https://hello-nginx.<real-domain>"
  }
}
```

Effective remains `local` until verification succeeds.

Update `routes.json`:

```json
{
  "workloadRoutes": {
    "hello-nginx": {
      "cloudflare": {
        "enabled": true,
        "hostname": "hello-nginx.<real-domain>",
        "mode": "protected",
        "requiresAuth": true,
        "service": "http://127.0.0.1:18080"
      }
    }
  }
}
```

### cloudflared Config

Generated ingress should include only approved workload routes:

```yaml
ingress:
  - hostname: hello-nginx.<real-domain>
    service: http://127.0.0.1:18080
  - service: http_status:404
```

The catch-all `http_status:404` rule must remain last.

### Activation Preview Script

Add:

```text
scripts/oreo-cloudflare-activate-preview
```

Behavior:

```text
- read config/access.json/routes.json/exposure.json/privacy.json/policy.json
- confirm workload desired state is cloudflare-protected
- confirm privacy permits protected external route
- confirm hostname is not .invalid
- confirm workload is not dashboard/admin/database/sensitive/restricted unless policy explicitly allows
- generate planned ingress
- run cloudflared tunnel ingress validate if cloudflared is available and config path exists
- print required manual Cloudflare Access checks
- modify nothing
```

### Activation Script

Add:

```text
scripts/oreo-cloudflare-activate
```

Behavior:

```text
- require exact workload id confirmation
- require hostname confirmation
- require Access-protection confirmation
- validate ingress
- install/update cloudflared config outside Git
- start or reload cloudflared only for named tunnel
- run local health check
- run unauthenticated external probe expecting Access block/redirect, not public 200
- write activation evidence to runtime/cloudflare-activation/<timestamp>.json
- update access effective state to cloudflare-protected only after verification succeeds
- write audit event
- regenerate dashboard runtime state
```

### Access Verification

Unauthenticated probe should not return public app content.

Acceptable results:

```text
- HTTP redirect to Cloudflare Access login
- HTTP 403/401 Access block
- other clear Cloudflare Access challenge/block behavior
```

Unacceptable:

```text
- HTTP 200 with app content for unauthenticated request
- direct origin exposure
- cloudflare-public state
```

### Rollback Script

Add:

```text
scripts/oreo-cloudflare-rollback
```

Behavior:

```text
- remove or disable hello-nginx ingress rule
- validate config
- reload/restart cloudflared if active
- update effective access back to local or tailnet
- write audit event
- preserve activation evidence
```

### Acceptance Criteria

```text
[ ] real hostname replaces .invalid
[ ] cloudflared credentials stored outside Git
[ ] generated ingress validates
[ ] Cloudflare Access app/policy exists
[ ] unauthenticated request does not return app content
[ ] authenticated operator can reach app through Access
[ ] effective access updates only after verification
[ ] rollback path documented and tested at least as preview
[ ] smoke confirms no blocked workloads exposed
```

---

## 20. Phase P2-08 — Effective Access Reconciliation

### Goal

Make desired/effective access state trustworthy.

### Add Reconciler

```text
scripts/oreo-access-reconcile
```

Behavior:

```text
- read desired/effective state
- probe local URLs
- probe tailnet URLs when available
- inspect Cloudflare plan/activation state
- inspect cloudflared active state
- verify effective state matches reality
- detect drift
- never expose anything
- never mutate unless --apply is explicitly provided
```

### Drift Examples

```text
Desired: cloudflare-protected
Effective: cloudflare-protected
Reality: cloudflared inactive
Result: FAIL drift detected
```

```text
Desired: local
Effective: local
Reality: Cloudflare route still active
Result: FAIL external exposure drift
```

### Apply Mode

```text
oreo-access-reconcile --apply
```

Only allowed to lower effective access automatically:

```text
cloudflare-protected -> local
cloudflare-protected -> tailnet
```

It must not raise exposure automatically.

### Acceptance Criteria

```text
[ ] drift detection works
[ ] smoke includes access reconcile check
[ ] effective access cannot silently claim protected route if cloudflared inactive
[ ] lowering effective access writes audit event
```

---

## 21. Phase P2-09 — Expanded Smoke and Security Audit

### Goal

Make P2 invariants continuously testable.

### Smoke Test Additions

Add checks:

```text
PASS p1-complete tag exists
PASS operator links installed
PASS manifest schemas exist
PASS manifests schema-valid
PASS dashboard generation clean
PASS runtime dashboard state ignored
PASS control API action endpoints require auth
PASS logs preview capped/sanitized
PASS restart preview non-mutating
PASS backup execution gated by manifest
PASS latest approved backup artifact valid
PASS Cloudflare hostname is not .invalid if activation enabled
PASS Cloudflare Access protection evidence exists if effective cloudflare-protected
PASS no blocked workload in Cloudflare ingress
PASS cloudflare-public absent in P2
PASS effective access reconcile clean
PASS no tracked secrets
PASS no tracked runtime artifacts
PASS no Funnel detected
PASS no dashboard public route
```

### Security Audit Script

Add or extend:

```text
scripts/oreo-doctor
```

Checks:

```text
- no `.env` tracked
- no Cloudflare credentials tracked
- no runtime backups tracked
- no dashboard API public bind
- no Caddy dashboard wildcard bind
- no Funnel config
- no blocked workloads in Cloudflare ingress
- no sensitive/restricted workload externally exposed
- cloudflare-public not used
```

### Acceptance Criteria

```text
[ ] smoke passes with 0 failures
[ ] warnings are documented or fixed
[ ] doctor flags deliberate unsafe local test configs
[ ] P2 closeout can cite final smoke output
```

---

## 22. Phase P2-10 — P2 Closeout

### Goal

Document completion, merge closeout PR, and tag `p2-complete`.

### Closeout Doc

Create:

```text
docs/P2_CLOSEOUT.md
```

Include:

```text
- completed PRs
- final migrated workloads
- final Cloudflare status
- backup status
- dashboard/API status
- final smoke output
- known limitations
- P3 recommendations
```

### Tag Commands

After closeout PR merges:

```bash
cd /srv/oreo-cloud
git checkout main
git pull --ff-only
scripts/smoke-test
git tag -a p2-complete -m "Oreo Cloud P2 complete"
git push origin p2-complete
```

### Acceptance Criteria

```text
[ ] closeout PR merged
[ ] final smoke passes
[ ] p2-complete tag exists on main
[ ] open P2 issues are closed or explicitly deferred to P3
```

---

## 23. Dashboard V3 Requirements

P2 dashboard becomes Dashboard V3.

### Required Sections

```text
System
Workloads
Operations
Backups
Access
Cloudflare
Events
Monitoring
```

### Per-Workload Card

Show:

```text
- name
- id
- runtime
- migration status
- manifest validation status
- health
- privacy state
- desired access
- effective access
- local/tailnet/cloudflare URLs
- backup status
- operation status
- last audit event
```

### Admin Mode Actions

Admin mode may show:

```text
- logs preview
- restart preview
- backup preview
- Cloudflare activation preview
```

Apply buttons require:

```text
- token
- policy pass
- preview generated
- exact confirmation
```

### UX Rules

```text
- monitor panel hidden by default
- action panels collapsed by default
- destructive/external actions visually distinct
- no secrets in DOM
- no raw command strings in UI
- no external CDN
- no remote fonts
```

---

## 24. API Requirements

### Existing API

```text
GET  /api/workloads
GET  /api/access
GET  /api/privacy
GET  /api/metrics
GET  /api/events
POST /api/workloads/<id>/privacy
POST /api/workloads/<id>/access/preview
POST /api/workloads/<id>/access/apply
```

### P2 API Additions

```text
GET  /api/dashboard-state
GET  /api/actions
POST /api/workloads/<id>/logs/preview
POST /api/workloads/<id>/restart/preview
POST /api/workloads/<id>/restart/apply
POST /api/workloads/<id>/backup/preview
POST /api/workloads/<id>/backup/apply
POST /api/workloads/<id>/cloudflare/preview
POST /api/workloads/<id>/cloudflare/apply
```

### Binding Requirement

API must bind only to:

```text
127.0.0.1:8099
```

Caddy may proxy `/api/*` only from the Tailscale-bound private dashboard route.

### API Response Requirements

All operation responses must be structured JSON:

```json
{
  "ok": true,
  "workloadId": "hello-nginx",
  "operation": "restart-preview",
  "allowed": true,
  "requiresConfirmation": true,
  "confirmationPhrase": "hello-nginx",
  "summary": "Restart is allowed for service web in project hello-nginx.",
  "warnings": [],
  "redacted": true
}
```

Do not return raw command strings.

---

## 25. CLI Requirements

### Existing P1 Commands

```text
oreo-logs
oreo-restart-preview
oreo-restart
oreo-backup-plan
oreo-backup-run
oreo-restore-plan
oreo-events
```

### New P2 Commands

```text
install-operator-links
validate-manifests
validate-configs
oreo-dashboard-state
oreo-action-preview
oreo-action-apply
oreo-cloudflare-activate-preview
oreo-cloudflare-activate
oreo-cloudflare-rollback
oreo-access-reconcile
```

### Common CLI Rules

```text
- use Python standard library unless already existing scripts use shell safely
- no jq dependency
- no raw secrets in output
- no env var dumps
- no docker inspect unless output is tightly filtered
- exit nonzero on validation failure
- write audit events for apply actions
```

---

## 26. Backup Requirements

### Backup Roots

Approved backup root:

```text
/srv/oreo-cloud/runtime/backups
```

Per-workload backup root:

```text
/srv/oreo-cloud/runtime/backups/<workload-id>
```

### Backup Metadata

Each backup artifact must include:

```text
manifest.json
checksums.sha256
restore-plan.md
backup-summary.json
```

### Backup Summary Shape

```json
{
  "version": 1,
  "workloadId": "hello-nginx",
  "createdAt": "2026-06-30T00:00:00Z",
  "sourceIncluded": true,
  "envIncluded": false,
  "volumesIncluded": false,
  "databaseIncluded": false,
  "artifactPath": "/srv/oreo-cloud/runtime/backups/hello-nginx/20260630-000000",
  "redacted": true
}
```

---

## 27. Cloudflare Requirements

### P2 Cloudflare Mode

Only this mode is allowed:

```text
cloudflare-protected
```

Disallowed:

```text
cloudflare-public
quick tunnel as final state
```

### Named Tunnel Requirements

```text
- tunnel credentials outside Git
- ingress config validated
- catch-all 404 ingress rule
- Access application/policy configured
- unauthenticated request must not return app content
```

### Evidence File

Write activation evidence to:

```text
/srv/oreo-cloud/runtime/cloudflare-activation/<timestamp>.json
```

Example:

```json
{
  "version": 1,
  "workloadId": "hello-nginx",
  "hostname": "hello-nginx.example.com",
  "activatedAt": "2026-06-30T00:00:00Z",
  "ingressValidated": true,
  "cloudflaredActive": true,
  "localHealthOk": true,
  "unauthenticatedProbe": {
    "ok": true,
    "status": 302,
    "looksAccessProtected": true
  },
  "effectiveAccessUpdated": true
}
```

This file is runtime evidence and must not be tracked by Git.

---

## 28. Policy Updates

Update `config/policy.json` with explicit P2 rules:

```json
{
  "p2": {
    "allowCloudflarePublic": false,
    "allowQuickTunnelActivation": false,
    "allowProtectedCloudflareForUnclassified": true,
    "allowProtectedCloudflareForPersonal": true,
    "allowProtectedCloudflareForInternal": false,
    "allowProtectedCloudflareForSensitive": false,
    "allowProtectedCloudflareForRestricted": false,
    "requireCloudflareAccess": true,
    "requireExternalProbe": true,
    "requireRollbackPlan": true,
    "requireEffectiveAccessReconcile": true
  }
}
```

---

## 29. Acceptance Criteria

P2 is complete when:

```text
[ ] p1-complete tag exists before P2 work begins
[ ] operator symlink installer exists
[ ] all approved operator commands work by short name
[ ] manifest schema exists
[ ] all manifests validate
[ ] dashboard runtime state is separated from tracked static assets
[ ] dashboard regeneration does not dirty Git
[ ] dashboard V3 shows operation/backup/access/Cloudflare state
[ ] control API action endpoints require auth
[ ] logs preview is capped and sanitized
[ ] restart preview/apply works for an approved workload
[ ] backup execution works for hello-nginx
[ ] restore test is documented
[ ] one additional low-risk workload is migrated or safely deferred with reason
[ ] real Cloudflare protected hostname is configured for hello-nginx, if external prerequisites exist
[ ] Cloudflare Access protection is verified before effective access is updated
[ ] cloudflare-public is not used
[ ] Tailscale Funnel remains disabled
[ ] no dashboard/Uptime Kuma/PostgreSQL/Docker/SSH exposure exists
[ ] access reconcile reports no drift
[ ] smoke test passes with 0 failures
[ ] closeout PR merged
[ ] p2-complete tag exists on main
```

---

## 30. P2 GitHub Issues

Create these issues:

### P2-00 — Baseline and Release Hygiene

```markdown
Record P2 baseline from p1-complete main.

Acceptance:
- docs/P2_BASELINE.md exists
- smoke passes
- no unexpected public exposure
```

### P2-01 — Operator Symlink Installer

```markdown
Add repeatable operator symlink installer and smoke checks.

Acceptance:
- approved CLI commands work by short name
- install script refuses unsafe overwrites
- smoke validates symlinks
```

### P2-02 — Manifest Schema Validation

```markdown
Add first-class manifest schema and validator.

Acceptance:
- schemas exist
- validate-manifests passes for hello-nginx
- smoke fails on invalid manifest
```

### P2-03 — Dashboard Runtime Cleanliness

```markdown
Separate runtime dashboard state from tracked static assets.

Acceptance:
- dynamic state served by API or ignored runtime JSON
- dashboard generation does not dirty Git
```

### P2-04 — Dashboard Safe Action Layer

```markdown
Add authenticated preview/apply endpoints for logs, restart, and backup.

Acceptance:
- unauthenticated mutations blocked
- logs sanitized/capped
- restart requires confirmation
- audit events written
```

### P2-05 — Backup Execution for hello-nginx

```markdown
Enable and test backup execution for hello-nginx.

Acceptance:
- backup artifact created
- checksums exist
- restore plan generated
- non-destructive restore test documented
```

### P2-06 — Next Low-Risk Workload Migration

```markdown
Migrate one additional low-risk workload or document safe deferral.

Acceptance:
- manifest validates
- health check passes
- no secrets/source/runtime data tracked
```

### P2-07 — Real Cloudflare Protected Activation

```markdown
Activate protected Cloudflare access for hello-nginx using named tunnel and Access.

Acceptance:
- real hostname
- Access protection verified
- effective access updated after verification
- rollback documented
```

### P2-08 — Effective Access Reconciliation

```markdown
Add reconcile command and smoke coverage for access drift.

Acceptance:
- drift detected
- no auto-raising exposure
- effective access matches reality
```

### P2-09 — Expanded Smoke and Security Audit

```markdown
Expand smoke/doctor checks for all P2 invariants.

Acceptance:
- smoke passes with 0 failures
- blocked exposures detected if introduced
```

### P2-10 — P2 Closeout

```markdown
Document P2 final state and tag p2-complete.

Acceptance:
- docs/P2_CLOSEOUT.md merged
- p2-complete tag pushed
```

---

## 31. Codex Task Prompts

### Task P2-00

```text
You are working in /srv/oreo-cloud.

Start P2 from the p1-complete baseline.

Do not mutate services except running read-only verification commands.
Do not expose anything.
Do not start Cloudflare.
Do not enable Funnel.

Create docs/P2_BASELINE.md with:
- git tag state
- smoke output
- service status
- API bind status
- Caddy validation result
- Funnel status
- cloudflared status
- current workload summary
```

### Task P2-01

```text
Add scripts/install-operator-links.

It should manage approved /usr/local/bin symlinks for Oreo Cloud commands.
It must refuse to overwrite non-symlink files unless --force is passed.
It must verify targets exist and are executable.
Update smoke-test to validate symlinks.
Do not restart services.
```

### Task P2-02

```text
Add first-class workload manifest validation.

Create config/schemas/workload-manifest.schema.json and docs/MANIFEST_SCHEMA.md.
Create scripts/validate-manifests using Python standard library.
Validate all workloads/*/manifest.json.
Update smoke-test to fail on invalid manifests.
```

### Task P2-03

```text
Fix dashboard runtime artifact dirtiness.

Move dynamic events/health/runtime data out of tracked static HTML.
Create scripts/oreo-dashboard-state to write ignored runtime/dashboard-state.json.
Add GET /api/dashboard-state.
Update dashboard JS to fetch runtime state.
Ensure running dashboard generation does not dirty Git.
```

### Task P2-04

```text
Add safe dashboard action layer.

Add authenticated API endpoints for:
- logs preview
- restart preview/apply
- backup preview/apply

Rules:
- POST requires bearer token
- preview before apply
- exact confirmation for restart/backup apply
- no raw shell commands in API responses
- logs capped and sanitized
- audit events written
```

### Task P2-05

```text
Enable backup execution for hello-nginx only.

Update hello-nginx manifest backup.backupAllowed=true with source-only backup.
Run oreo-backup-run hello-nginx.
Create restore-plan and non-destructive restore-test documentation.
Update smoke-test to validate latest approved backup artifact.
Do not include .env files or secrets.
```

### Task P2-06

```text
Evaluate next low-risk workload migration.

Use migration planner first.
Do not migrate Intake OS, Uptime Kuma, PostgreSQL, admin dashboards, or sensitive workloads.
If a safe candidate exists, migrate one workload with manifest validation and smoke.
If no safe candidate exists, document deferral with evidence.
```

### Task P2-07

```text
Implement real Cloudflare protected activation for hello-nginx.

Do not use quick tunnel.
Do not use cloudflare-public.
Require real hostname and Cloudflare Access policy.
Store credentials outside Git.
Generate and validate named tunnel ingress.
Verify unauthenticated request does not return app content.
Update effective access only after verification succeeds.
Write activation evidence under runtime/cloudflare-activation.
```

### Task P2-08

```text
Add effective access reconciliation.

Create scripts/oreo-access-reconcile.
Detect drift between desired/effective config and actual route state.
Never raise exposure automatically.
Allow --apply only to lower effective access after drift.
Update smoke-test to run reconcile.
```

### Task P2-09

```text
Expand smoke-test and oreo-doctor for P2 invariants.

Include:
- symlinks
- manifest validation
- dashboard cleanliness
- action auth boundaries
- backup artifact validation
- Cloudflare Access evidence if active
- no cloudflare-public
- no Funnel
- no tracked secrets
- no blocked exposures
```

### Task P2-10

```text
Create docs/P2_CLOSEOUT.md after all P2 phases merge.

Include completed PRs, live verification, final smoke output, migrated workloads, Cloudflare status, backup status, known limitations, and P3 recommendations.
After closeout PR merges, tag main as p2-complete.
```

---

## 32. P2 Closeout Template

```markdown
# Oreo Cloud P2 Closeout

P2 status: complete when this closeout PR is merged and `p2-complete` is tagged on `main`.

Verified on `oreochiserver`: YYYY-MM-DDTHH:MMZ.

## Completed Phases

| Phase | Result |
| --- | --- |
| P2-00 baseline | ... |
| P2-01 operator links | ... |
| P2-02 manifest schema | ... |
| P2-03 dashboard runtime cleanliness | ... |
| P2-04 dashboard action layer | ... |
| P2-05 backup execution | ... |
| P2-06 workload migration | ... |
| P2-07 Cloudflare protected activation | ... |
| P2-08 access reconcile | ... |
| P2-09 smoke expansion | ... |

## Live Server State

- /srv/oreo-cloud is a Git repo.
- oreo-control-api.service: active/inactive
- oreo-metrics.timer: active/inactive
- API binds only to 127.0.0.1:8099.
- Caddy validates.
- Tailscale Funnel: disabled.
- cloudflared: active/inactive, expected: ...

## Workloads

| Workload | Migration | Privacy | Desired Access | Effective Access | Backup | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| hello-nginx | migrated | unclassified | cloudflare-protected | cloudflare-protected/local | enabled | ... |

## Cloudflare

- Provider enabled: true/false
- Named tunnel active: true/false
- Hostname: ...
- Access protection verified: true/false
- Public unauthenticated route: none
- Blocked workloads exposed: none

## Final Smoke Test

```text
...
Smoke summary: 0 failure(s), 0 warning(s)
```

## Known Limitations

- ...

## P3 Recommendations

- ...
```

---

## 33. P3 Recommendations

Likely P3 scope after P2:

```text
- dashboard apply actions for more operation types
- policy-managed workload promotion between local/tailnet/protected access
- backup scheduling and restore drills
- additional workload migrations
- optional Cloudflare Access API automation
- health notifications
- deployment workflows
- workload templates
- secrets inventory without secret values
- external uptime checks for protected workloads
```

---

## 34. Reference Notes

P2 implementation should align with these platform behaviors:

- Caddy `bind` controls the listener interface and accepts a host/interface without a port; the site address controls the port. This is why the private dashboard route must bind to the Tailscale IP instead of a wildcard listener.
- Docker Compose project names can depend on the Compose file directory or project directory. Workload migrations should preserve project names explicitly with `-p` or `COMPOSE_PROJECT_NAME`.
- Docker Compose `restart` restarts containers but does not apply changed Compose configuration such as new environment variables; P2 restart actions should be treated as restart-only, not deploy.
- Tailscale Funnel exposes services to the public internet, while tailnet-only access should use private Tailscale routing/Serve patterns. P2 must not enable Funnel.
- Cloudflare Tunnel uses `cloudflared` outbound connections and named tunnel ingress rules. P2 activation should use named tunnels, validate ingress, and keep credentials outside Git.
- Cloudflare Access self-hosted applications are deny-by-default with Allow policies, and account-level Access protection can block hostnames without a matching Access application. P2 Cloudflare activation should verify Access protection before updating effective access.
