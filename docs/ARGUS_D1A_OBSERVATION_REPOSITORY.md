# D1a Configured-Estate Observation Repository

Issue: `#301`

Repository schema: current `2`, previous readable `1`

Normalized observation envelope: current `2`, previous readable `1`

## Boundary and outcome

D1a provides a deterministic, vendor-neutral repository contract. It does not
run collectors, schedule refreshes, reconcile canonical state, admit workloads,
decide policy or effective access, authorize operations, or mutate anything.
The production registry starts empty and therefore reports `not-configured`;
later collector PRs must add reviewed sources before completeness can become
true. There is no AI, model, advisory-import, network, or arbitrary-command path.

The canonical trust-domain denominator is derived from the reviewed workload
and legacy classification files. `hostSources` adds reviewed host-level expected
source IDs. A missing domain or expected host source is a visible
`configuration-gap`; an empty registry is never treated as complete.

## Source registry

Registry version `1` remains readable by D1a. D1b promotes
`config/argus/observation-sources.json` to version `2` by adding an exact local
transport binding. Every configured source declares:

- stable source, host, owner, trust-domain, scope, and privilege identity;
- freshness SLO plus source schema and collector protocol versions;
- numeric execution UID/GID;
- exact argv/API allowlists (collector configuration only);
- timeout, output, record-count, and record-size ceilings;
- allowed resource kinds and per-kind attribute allowlists;
- explicit bootstrap and removal procedures;
- optional exclusion owner, reason, and expiry.

The SQLite `sources` row stores the allowlist/bootstrap/removal digests, not the
command, API, or procedure text. An exclusion stays visible and never counts as
fresh. After expiry it becomes `never_observed` plus `expired-exclusion`; a new
successful run is required. Removing a source marks it inactive and retains its
bounded history.

## Normalized identity and minimization

An observation is identified by:

```text
(source_id, resource_kind, native_id, collection_run)
```

Native IDs are never globally unique. The only record fields are version,
resource kind, native ID, observation time, allowlisted attributes, and bounded
adapter provenance. Unknown fields and versions fail closed. Raw command lines,
environment, file content, Git remotes, credentials, secret markers, and
non-allowlisted attributes are rejected. The reference adapter is the only code
that knows its fixture's native field names; repository and snapshot consumers
receive only normalized records.

Canonical identity, privacy, policy, desired/effective access, authorization,
and mutation authority cannot be written through this API and have no columns in
the observation database. A reconciliation link is evidence only and cannot
grant any of those authorities.

## Atomic runs and source state

Each run starts as non-current inside one SQLite transaction. Records are
normalized, bounded, sorted, and digested before the terminal state is written.
Only a validated `completed` run with a higher source sequence atomically moves
the source's `current_run_id`. A valid empty completed run may become current.
`partial` and `failed` runs record a source-specific gap and retain the
last-known-good pointer. Interrupted `collecting` rows recover as `failed` with
`restart-interrupted`; they never become current. Older successful arrivals are
recorded as superseded without replacing newer evidence.

The coverage states are exactly `never_observed`, `fresh`, `stale`, `failed`,
and `excluded`. Only `fresh` contributes to the numerator. The caller supplies
the explicit clock used for freshness and exclusion decisions.

## Migration, rollback, and retention

Before migration, use SQLite's consistent backup API and store the backup outside
the live database path with operator-only permissions. Version `1` remains
readable during rolling deployment. The version `1 -> 2` migration adds removal,
supersession, and evidence-only reconciliation-link support in one transaction.
Unknown or future versions fail closed. Rollback stops all writers, validates the
backup with `PRAGMA integrity_check`, atomically restores it, and reopens it with
the previous reader. After a version-2-only write is accepted by another
component, forward repair is safer than schema downgrade; the pre-migration
backup is the last safe rollback point.

Retention keeps at least the current and one prior completed snapshot per source
plus one failed run. Defaults retain 20 completed and 20 partial/failed runs.
Pruning never deletes the current pointer. The database ceiling is 8 MiB; ingest
rolls back if SQLite page usage crosses it. The acceptance command measures three
fresh migration/ingest/rollback runs on `oreochiserver`; the ceiling is the
greater of a conservative 8 MiB floor or four times the measured fixture maximum.
Live-collector PRs must repeat sizing with their bounded fixtures and lower
per-source limits or raise the ceiling only through review.

## Build versus integrate

| Concern | D1a decision | Follow-on owner |
| --- | --- | --- |
| SQLite repository, migration, atomic pointer | Build with Python stdlib | D1a |
| Native fixture normalization | Build one conformance adapter | D1a |
| Collector socket, paging, peer identity | Implemented above D1a | D1b |
| Docker/systemd/cron collectors | Not present | D2-D4 |
| Reconciliation to canonical workloads | Evidence table only; no admission | D5 |
| Completeness API and UI | Stable repository/coverage contract only | D5/D6 |
| Scheduling and concurrent refresh | Implemented above D1a | D1b |
| Migration or workload mutation | Forbidden | Epic M |
| AI or advisory analysis | Forbidden and absent | Separate future read-only boundary/ADR |

## Verification and recovery

Local conformance:

```text
python3 -m unittest tests.test_argus_observations -v
scripts/argus-check
```

Server acceptance uses only temporary files and pinned fixtures; it does not
touch the deployed database, configuration, collectors, services, or workloads:

```text
scripts/argus-observation-repository-acceptance \
  --root <reviewed-checkout> \
  --source-revision <commit> \
  --captured-at <UTC timestamp> \
  --target oreochiserver > <operator-only-summary.json>
scripts/argus-acceptance-summary --input <operator-only-summary.json> --format markdown
```

If any run fails, retain the deployed repository version, do not add collectors,
and inspect only local operator-owned logs. Never paste raw observations or the
database into a PR.
