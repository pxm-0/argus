# M5 Workload Backup and Staging

This phase creates a root-only backup and a non-serving restore drill for each
retained workload. It never stops a source Compose project, starts an
application target, publishes a port, or changes a route.

The fixed mapping is:

- `hastur`, `kadath`, `nodens`, and `locigraph` → `personal-sandbox`
- `intake-os` → `work-sandbox`

The script validates the canonical manifest, live Compose identity, container
health, image IDs, mounts, named volumes, networks, source health, target
emptiness, and capacity. Backups live below
`/var/backups/argus-m5-workload-staging`. Staged sources live below the
root-owned `/var/lib/argus/migration-staging` anchor; only the timestamp leaf is
handed to its sandbox identity.

Images are saved and verified by immutable image ID. PostgreSQL is dumped
logically, restored in a random labeled volume with `--network none`, and
compared using extensions, tables, exact row counts, and sequence values.
File-state archives preserve regular files, links, empty directories, modes,
owners, ACLs, and xattrs. Restore parity is derived from the fixed archive,
never from a second view of a changing source. GNU tar performs the native
content/metadata comparison against the restored target, and the checksummed
evidence records the exact source-archive digest.

Hastur is paused only while its live data bind is archived. LociGraph pauses
only `backend` and `worker` while the shared raw-data volume is archived.
Every paused container is unpaused before restore work continues, including
when archiving fails. PostgreSQL and Redis use logical hot snapshots and are
not paused.

The staged target Compose JSON preserves the project name and immutable image
IDs while removing environment values, published ports, unsafe privileges,
external networks, forbidden host mounts, and cross-domain binds. All target
networks are internal. The composition is rendered and validated but not
started. An identical root-owned copy is included in the checksum set. Cutover
must compare the domain leaf to that evidence digest and render it again; the
staged leaf is not trusted merely because staging once succeeded.

Environment and credential files excluded by the canonical workload policy
remain excluded:

- Hastur: `.env`, `auth`, SSH material
- Nodens: `.env`
- LociGraph: `.env`
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
