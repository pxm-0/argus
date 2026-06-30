# Oreo Cloud Manifest Schema

P2 makes workload manifests enforceable. The machine-readable schema lives at:

```text
config/schemas/workload-manifest.schema.json
```

The local validator is:

```bash
scripts/validate-manifests
```

The validator uses the Python standard library. It does not require `jq` or an external JSON Schema package.

## Required Fields

Every tracked workload manifest must include:

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
operations.backup.allowed
backup.backupAllowed
backup.restoreAllowed
security.publicAllowed
security.notes
```

## Enums

```text
schemaVersion: 1
runtime.type: docker-compose | external | static | unknown
migration.status: planned | migrated | external | rolled-back | skipped
privacyCompatibility: unclassified | personal | internal | sensitive | restricted
accessCompatibility: none | local | tailnet | cloudflare-protected | cloudflare-public
```

## Path Rules

For workload `<id>`, these paths must match:

```text
canonicalRoot = /srv/oreo-cloud/workloads/<id>
sourcePath = /srv/oreo-cloud/workloads/<id>/source
backup.destination = /srv/oreo-cloud/runtime/backups/<id>...
```

Docker Compose manifests must keep compose files under `sourcePath` and must name the Compose project explicitly. This preserves project names during migration.

## Safety Rules

- `backup.destination` must stay under `/srv/oreo-cloud/runtime/backups/<id>`.
- `backup.destination` is required when `backup.backupAllowed` is true.
- `security.publicAllowed` cannot be true for sensitive or restricted workloads.
- Manifest validation fails closed; smoke fails if any tracked manifest is invalid.

## Compatibility

P2 keeps P1 compatibility fields such as `runtime.composeProject`, `runtime.composePath`, `operations.logsAllowed`, and `security.publicExposureAllowed` while introducing first-class P2 fields. Existing CLIs can continue reading the P1 fields until later phases migrate shared helpers.
