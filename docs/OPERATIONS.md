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
- A mutation is allowed only at the final typed `apply`, `rollback`, or
  `recover` boundary after preview, fresh preconditions, and exact confirmation.
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

```bash
argus estate status --json
argus estate coverage --json
argus estate refresh --json
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

Git stores only a reviewed Compose template. Before a workload can run or move,
the root-owned materializer verifies the template's immutable image, loopback
port contract, health check, and secret-free fields, then writes the ignored
runtime source plus a digest-bound journal. Do not add a workload's generated
`source/` directory to Git.

```bash
sudo ./scripts/argus-workload-source-materialize --workload hello-nginx --preflight
sudo ./scripts/argus-workload-source-materialize --workload hello-nginx --apply \
  --acknowledge-source-materialization
```

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

## Durable operations

`server-read-only` — `argus operation show <operation-id>`

`server-mutation` — `argus operation recover <operation-id>`

Show reads the compatible operation ledger without migration or writes.
Recovery fails closed unless the exact ID is confirmed and a typed recovery is
approved; generic recovery is intentionally unavailable.

```bash
argus operation show 00000000-0000-0000-0000-000000000000 --json
```

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

## Compatibility aliases

The dispatcher currently maps these aliases with an explicit deprecation notice:

- `argus workloads` → `argus workload list`
- `argus health` → `argus estate status`
- `argus migration-plan <id>` → `argus workload move preview <id>`

Repository-relative scripts under `scripts/` are compatibility internals. When
a historical runbook must be reproduced, open a linked issue and restate the
safe current command, privilege, evidence, and recovery contract first.
