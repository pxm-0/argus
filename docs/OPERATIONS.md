# Current Argus Operator Contract

This is the current command surface. Historical milestone commands remain in
the repository for compatibility and audit archaeology, but they are not public
operator commands and must not substitute for a refused stable command.

The only installed public executable is `argus`. Discover the private route
with `argus dashboard url`; never copy a deployment-specific host or port from
historical evidence.

## Command rules

- Human mode writes result data to stdout and diagnostics to stderr.
- `--json` emits one schema-versioned envelope on stdout.
- Read-only status and preview commands never mutate.
- A mutation is allowed only at the final typed `apply` or `rollback` boundary
  (or an `api-session` create) after preview, fresh preconditions, and exact
  confirmation.
- A refused or unavailable command means stop. A milestone script is not a
  workaround.

Exit classes are stable: `0` success, `1` internal/check failure, `2` invalid
invocation, `3` safe refusal/precondition, `4` unavailable/transient, and `5`
indeterminate/recovery required.

## Dashboard

`local-read-only` — `argus dashboard url`

Prints the configured private HTTPS URL and labels live effective state
unverified. It also fails closed unless Funnel is recorded disabled.

```bash
argus dashboard url
argus dashboard url --json
```

## Estate

`local-read-only` — `argus estate status`

`local-refresh-request` — `argus estate refresh`

`local-read-only` — `argus estate coverage`

Refresh queues an inert, status-addressable request for the D1–D5 coordinator;
it cannot change workload authority. Status and coverage report the last
completed whole-estate reconciliation, including any missing or stale source.
Explicitly terminal Docker history (`exited` or `dead`) remains observable but
does not claim current workload authority; an unknown or transitional state
continues to block movement.

```bash
argus estate status --json
argus estate coverage --json
argus estate refresh --json
```

The installed `argus-estate-refresh.service` is the only supported way to run
the timer worker manually, because it uses the pinned `oreo` collector identity
required by peer-authenticated source sockets. Do not invoke its `--timer` mode
with `sudo` directly.

```bash
sudo systemctl start argus-estate-refresh.service
```

### Server collector activation

`server-mutation` — `scripts/argus-collector-deploy`

The D1–D5 collector estate is installed only from the reviewed `/srv/argus`
checkout. It writes one-source, root-owned registry projections and the
reviewed systemd units, creates the dedicated rootful read-only account only if
needed, and then starts a bounded refresh. It never grants a collector access
to a mutation agent, operation ledger, capability issuer, or workload Docker
socket outside its assigned source.

```bash
sudo ./scripts/argus-collector-deploy --preflight
sudo ./scripts/argus-collector-deploy --apply --acknowledge-estate-collectors
sudo ./scripts/argus-collector-deploy --status
```

If the controlled activation must be reversed, use the exact backup path
reported by `--apply`; rollback restores only files and service states captured
by that activation.

```bash
sudo ./scripts/argus-collector-deploy --rollback /var/backups/argus-estate-collectors/<timestamp> --acknowledge-estate-collectors-rollback
```

### Reviewed source materialization

`server-mutation` — `scripts/argus-workload-source-materialize`

Git stores reviewed Compose templates rather than generated runtime sources.
Before an approved workload can run or move, the root-owned materializer
verifies its immutable image, loopback-port contract, health check, and
secret-free fields, then writes the ignored runtime source plus a digest-bound
journal. Do not add a workload's generated `source/` directory to Git.

No active workload currently requires source materialization. The prior
`hello-nginx` materialization is retired; see
[`RETIRED_HELLO_NGINX.md`](RETIRED_HELLO_NGINX.md).

## Workloads

`local-read-only` — `argus workload list`

`local-read-only` — `argus workload show <id>`

These commands return canonical registry identity and sanitized policy state;
they do not expose workload source, secrets, or raw runtime observations.

```bash
argus workload list
argus workload show nodens --json
```

### Reviewed onboarding and admission drift

`scripts/argus-workload-onboard preview` writes only an ignored, digest-bound
review plan. `apply` accepts that exact plan and workload-ID confirmation,
backs up all six canonical files outside Git, and either commits the complete
default-deny candidate or recovers/rolls it back. It never adopts or starts a
discovered runtime, and every generated mutation capability remains denied.

```bash
scripts/argus-workload-onboard preview \
  --id example --name "Example" --kind web-app --runtime docker-compose \
  --compose-project example --realm personal --zone sandbox --stage none \
  --trust-domain personal-sandbox
scripts/argus-workload-onboard apply \
  --plan-digest sha256:<reviewed-digest> --confirm example
```

Onboarding edits only tracked config. After the onboarding PR merges and the
server pulls it, register the workload in private M1 with `sudo argus m1 sync`, then
`sudo argus m1 sync --apply --confirm <plan-digest>`, then `argus m1 verify`
(the legacy `scripts/argus-m1-reconcile-onboarded-workloads` still works). See `docs/ARGUS_M1_AUDIT_ANCHOR.md`.

`scripts/argus-admission-doctor --json` is read-only. By default on the server
it synchronously reuses the existing rootful Docker inventory helper and does
not persist inventory or require a daemon. Supplying both `--database` and
`--registry` selects the normalized observation repository for cross-domain
diagnostics. Explicit pre-onboarding observations may appear only in the
schema-validated `config/argus/runtime-quarantine.json`; those records remain
`admission=denied`, `access=none`, and linked to a disposition issue. The doctor
reports their count without adopting them. Any finding returns exit `1`;
invalid evidence returns exit `2`.

```bash
scripts/argus-admission-doctor --json
```

## Workload retirement

`local-write` — `argus workload retire <id>`

With `--dry-run` it prints the plan and writes nothing. Stage 1 only; it never touches the server. It removes every registry reference
under `config/` and `workloads/<id>/`, records the ID in
`config/argus/retired-workloads.json`, generates `docs/RETIRED_<ID>.md` from
`docs/RETIRED_TEMPLATE.md`, runs `argus check`, and opens a PR with a numbered
server teardown runbook as a comment. Remaining text references (docs, tests,
scripts) are listed for manual review. After merge and teardown, run
`scripts/argus-m1-reconcile-retired-workloads` (preview), then the same with
`--apply --acknowledge-retired-workload-reconciliation`, on the server.

## Workload moves

`local-read-only` — `argus workload move preview <id>`

`server-read-only` — `argus workload move preflight <id>`

`server-mutation` — `argus workload move apply <id>`

`server-read-only` — `argus workload move status <id>`

`server-mutation` — `argus workload move rollback <id>`

Preview and status always name current authority, phase, blockers, and retry
safety, plus the migration ID (or explicit `null` before creation), derived
eligible-target list, and exact status/recovery commands. The current CLI
recomputes the bounded preview against fresh configured-source coverage. `apply`
and `rollback` require exact confirmation but create only a 15-minute inert
dashboard handoff draft; they have no mutation authority and cannot bypass the
private operator session.

The private dashboard recomputes the same preview, requires step-up and the
exact migration phrase, then creates and approves one durable parent. The
coordinator advances its fenced child sequence: source fence, private target
prepare/start/health, desired-route reconciliation, final verification, and—on
a known forward failure—target stop, source restore, and source verification.
An unproven acknowledgement becomes `indeterminate`; it is never retried
automatically. Generic `production.promote` and historical direct-cutover
scripts are deliberately refused.

```bash
argus workload move preview nodens --json
argus workload move preflight nodens --json
argus workload move status nodens --json
```

Do not run an old migration script instead of this workflow.

## Operation API client

`api-session` — `argus op preview <workload> <type>`

`api-session` — `argus op create <workload> <type>`

`api-session` — `argus op show <operation-id>`

`api-session` — `argus op watch <operation-id>`

`api-session` — `argus workload deploy <id>`

`api-session` — `argus workload start <id>`

`api-session` — `argus workload stop <id>`

`api-session` — `argus workload restart <id>`

These use the private dashboard API (URL from `argus dashboard url`, or
`--base-url`) with the same tailnet identity, session, CSRF, Origin and
bootstrap-token step-up as the dashboard. The token is read only from
`/dev/tty`; with no terminal the command exits 2. `create` previews, then
requires the typed workload ID (or `--yes-digest <digest>` matching the
previewed digest), then steps up, creates, approves and watches to a terminal
state. Exit: succeeded 0; denied/expired 3; failed/rolled-back 4;
indeterminate or unobservable 5. The server binds approval and cancel to the
originating session, so there are no standalone `approve`/`cancel` verbs.
`--base-url` is accepted only for a `*.ts.net` https URL or loopback http.

```bash
argus op preview nodens workload.deploy --revision sha256:... --json
argus workload deploy nodens --revision sha256:...
```

## M1 state sync

`server-read-only` — `argus m1 sync`

`server-mutation` — `argus m1 sync --apply`

`server-read-only` — `argus m1 verify`

Server-only (root, private state); elsewhere they print the exact `ssh`
command to run. `sudo argus m1 sync` prints a diff-style plan (`+` add, `-`
remove, `~` drift) and a plan digest. `sudo argus m1 sync --apply --confirm
sha256:<digest>` applies it only if the digest matches the freshly recomputed
plan; it replaces both `--acknowledge-*` flags (the legacy scripts remain).
`argus doctor` reports `m1Drift` as a read-only warning.

```bash
sudo argus m1 sync
sudo argus m1 sync --apply --confirm sha256:<digest>
sudo argus m1 verify --json
```

## Alerts, smoke and backup evidence

`server-read-only` — `argus smoke status`

`server-read-only` — `argus backup list`

`server-read-only` — `argus backup freshness`

`server-read-only` — `argus alerts`

Run on the server. `argus smoke status [--last N]` shows the latest scheduled smoke and the capped 30-day history
(with the failed check names); `argus backup list|freshness` reads the snapshot pull directory and
`snapshot-last.json`; `argus alerts` shows what `argus-alert` holds open. Missing evidence is reported as
unavailable, never as healthy. See `docs/MONITORING.md`.

## Durable operations

`server-read-only` — `argus operation show <operation-id>`

Show reads the compatible operation ledger without migration or writes.
There is no generic recovery command; follow the typed recovery runbook named
by the operation.

```bash
argus operation show 00000000-0000-0000-0000-000000000000 --json
```

## Release pins and promotion

`server-mutation` — `argus release import <workload> --image <ref>`

`server-mutation` — `argus release pin <workload> --image <ref>`

`server-mutation` — `argus promote <staging-id> <production-id>`

`server-mutation` — `argus keys totp-enroll`

Root-only, TTY-only enrolment of one operator's TOTP second factor; see
`docs/RUNBOOKS/operator-session-diagnosis.md`.

Pin imports the allowlisted digest over `ssh $ARGUS_SSH_HOST sudo -n
$ARGUS_REMOTE_REPO/scripts/argus-image-import` (default `/srv/argus`), rewrites only the workload service's `image:` line, runs
`argus check`, and opens a PR; `--dry-run` prints the diff only. Promote
refuses unless `promotesTo` is registered, the two compose files differ only in
name, ingress path (managed or sandbox ingress dir) and secret refs, and a succeeded staging deploy of the image
ID is found in the operations ledger. The ledger is `argus-control` only, so when the local read fails the check runs
`ssh $ARGUS_SSH_HOST sudo -n $ARGUS_REMOTE_REPO/scripts/argus-promote-evidence` (read-only; needs this change pulled on the server); `--skip-evidence-check` bypasses it. Neither command deploys. See
`docs/ARGUS_M5_WORKLOAD_CUTOVER.md`.

## Doctor and contributor check

`local-read-only` — `argus doctor`

`local-read-only` — `argus check`

Doctor reports repository/deployed revision, operation schema, discovery schema,
collector protocol, deterministic core-boundary result, last completed
collection, last safe rollback point, compatibility state, and exact next
action. It omits credentials, private topology, raw command lines, and payloads.

Check runs the same deterministic validation used by CI and returns only a
sanitized output digest through the stable CLI envelope.

```bash
argus doctor --json
argus check --json
```

## Typed health observer

`argus-typed-health.timer` (every 5 minutes) runs `scripts/argus-typed-health` as the
non-human identity `argus-observer@machine.argus`. For each `lifecycle=active`
workload in a non-legacy trust domain whose manifest allows `health`, it creates and
approves one `health.refresh` through the control API, waits for the terminal state,
appends a `health.observed` audit line and exits non-zero if any is not healthy.
hastur, kadath and nodens stay on the M5 timers. The dashboard health tiles show the
newest finished `health.refresh` in the ledger and fall back to the static
`migration.lastHealthCheck`.

The observer has its own token (`/etc/argus/observer-token`, `root:argus-control`
0640), never the owner bootstrap token, and the API only lets it call
`health.refresh` preview, create, approve and read. One-time operator setup, in order:

1. Create the token without printing it: `sudo sh -c 'umask 037; head -c 32 /dev/urandom | base64 | tr -d "=+/\n" > /etc/argus/observer-token'; sudo chown root:argus-control /etc/argus/observer-token`.
2. Add `{"tailnetLogin": "argus-observer@machine.argus", "role": "owner", "enabled": true}`
   to `/etc/argus/operators.json` (the session store has one role; the API restricts
   this login by identity).
3. `sudo install` the two units from `systemd/`, `sudo systemctl daemon-reload`,
   `sudo systemctl enable --now argus-typed-health.timer`, and restart
   `argus-control-api` and `argus-operation-worker`.

`operation.finished` audit lines (operationId, workloadId, state, errorClass) are
written by the worker; the estate-refresh runner prunes status files to the newest 720
plus the newest per UTC day for 30 days.

## Compatibility aliases

The dispatcher currently maps these aliases with an explicit deprecation notice:

- `argus workloads` → `argus workload list`
- `argus health` → `argus estate status`
- `argus migration-plan <id>` → `argus workload move preview <id>`

Repository-relative scripts under `scripts/` are compatibility internals. When
a historical runbook must be reproduced, open a linked issue and restate the
safe current command, privilege, evidence, and recovery contract first.
