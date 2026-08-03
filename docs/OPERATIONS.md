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

`server-read-only` — `argus estate refresh`

`local-read-only` — `argus estate coverage`

Status and coverage truthfully report that the current legacy refresh is
rootful-Compose-container-only. Refresh refuses until the approved D1-D5 source
registry and collectors can report whole configured-estate completeness.

```bash
argus estate status --json
argus estate coverage --json
argus estate refresh --json
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

## Workload moves

`local-read-only` — `argus workload move preview <id>`

`server-read-only` — `argus workload move preflight <id>`

`server-mutation` — `argus workload move apply <id>`

`server-read-only` — `argus workload move status <id>`

`server-mutation` — `argus workload move rollback <id>`

Preview and status always name current authority, phase, blockers, and retry
safety, plus the migration ID (or explicit `null` before creation), derived
eligible-target list, and exact status/recovery commands. The current CLI
returns no eligible targets and refuses preflight and mutation because fresh
configured-source coverage and the approved parent/child migration kernel do
not exist yet. After those gates land, apply/rollback will additionally require
an exact `--confirm <id>` at the final reviewed boundary.

```bash
argus workload move preview nodens --json
argus workload move preflight nodens --json
argus workload move status nodens --json
```

Do not run an old migration script after this refusal.

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
