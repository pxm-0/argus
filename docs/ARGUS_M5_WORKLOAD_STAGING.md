# M5 Workload Backup and Staging

This phase creates a root-only backup and a non-serving restore drill for each
retained workload. It never stops a source Compose project, starts an
application target, publishes a port, or changes a route.

The fixed mapping is:

- `hastur`, `kadath`, and `nodens` → `personal-sandbox`
- `intake-os` → `work-sandbox`

The script validates the canonical manifest, live Compose identity, container
health, image IDs, mounts, named volumes, networks, source health, target
emptiness, and capacity. Backups live below
`/var/backups/argus-m5-workload-staging`. Staged sources live below the
root-owned `/var/lib/argus/migration-staging` anchor; only the timestamp leaf is
handed to its sandbox identity.

Images are saved and verified by immutable image ID, then each workload image
is forced through a target-side unpack check. If a locally built OCI layer is
incompatible with the rootless UID map, staging exports a stopped, pristine
container created from that image (never the live workload container), imports
the root filesystem, reconstructs supported operational image configuration
through Compose, and records the checksummed artifact plus source-to-target
image mapping. The full live container environment is already captured for
root-only injection at cutover, so environment values never appear in import
arguments. Images with declared volumes or unsupported runtime metadata are
refused rather than flattened. Hastur's reviewed `pnpm start` package script is
validated against the root-owned staged `package.json` and normalized to its
exact `node src/server.mjs` command, so the sealed sandbox never downloads a
package manager at runtime; the override is recorded in evidence. PostgreSQL is
dumped logically. Its source
bootstrap role, database, password/auth mode, and relevant init settings are
passed to the isolated restore container through child-process environment
only—never command arguments or evidence—so the staged volume preserves the
database identity and host-authentication posture. The dump is restored in a
random labeled volume with `--network none`, and
compared using extensions, tables, exact row counts, and sequence values.
Application-style TCP authentication is tested on both source and target with
the captured credential, and an intentionally incorrect password proves
whether each side enforces password authentication. Password values remain in
child-process environment only. Restore waits for both `pg_isready` and
PostgreSQL as container PID 1, avoiding the image entrypoint's temporary
initialization-server readiness window.
File-state archives preserve regular files, links, empty directories, modes,
owners, ACLs, and xattrs. Restore parity is derived from the fixed archive,
never from a second view of a changing source. GNU tar performs the native
content/metadata comparison against the restored target, and the checksummed
evidence records the exact source-archive digest.

Hastur is paused only while its live data bind is archived.
Every paused container is unpaused before restore work continues, including
when archiving fails. PostgreSQL and Redis use logical hot snapshots and are
not paused.

The staged target Compose JSON preserves the project name and reviewed
source-to-target image identity while removing environment values, published
ports, unsafe privileges,
external networks, forbidden host mounts, and cross-domain binds. All target
networks are internal. The composition is rendered and validated but not
started. An identical root-owned copy is included in the checksum set. Cutover
must compare the domain leaf to that evidence digest and render it again; the
staged leaf is not trusted merely because staging once succeeded.

Environment and credential files excluded by the canonical workload policy
remain excluded:

- Hastur: `.env`, `auth`, SSH material
- Nodens: `.env`
- Intake OS: `.env.server`

Those credentials must be provisioned separately before cutover. Hastur auth
and SSH dependency remains an explicit cutover blocker; it is not silently
copied.

Run one workload at a time from the exact reviewed commit:

```bash
sudo ./scripts/argus-m5-workload-stage --workload nodens --preflight
sudo ./scripts/argus-m5-workload-stage \
  --workload nodens \
  --apply \
  --acknowledge-m5-workload-stage
```

Before a target project exists, rollback verifies every artifact checksum and
resource ownership label, then removes only the recorded staging volumes and
leaf:

```bash
sudo ./scripts/argus-m5-workload-stage \
  --workload nodens \
  --rollback /var/backups/argus-m5-workload-staging/nodens/<stage-id>/stage-summary.json \
  --acknowledge-m5-workload-stage-rollback
```

Transferred images remain cached after an explicit successful-stage rollback.
Failure cleanup removes only resources carrying the current random stage ID and
marks the retained root-only backup `FAILED`.
