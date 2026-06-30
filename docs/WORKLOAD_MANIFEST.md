# Workload Manifest

P1 workload manifests describe the safe metadata Oreo Cloud needs for migration,
operations, backup planning, and dashboard display.

Manifests live at:

```text
workloads/<workload-id>/manifest.json
```

On the server, the canonical workload layout is:

```text
/srv/oreo-cloud/workloads/<workload-id>/
├── README.md
├── manifest.json
├── source/
├── data/
├── env/
├── backups/
└── runtime/
```

Only safe metadata should be tracked by Oreo Cloud Git:

- `README.md`
- `manifest.json`
- optional templates
- docs and registry references

Do not track workload source, `.env` files, secrets, runtime data, database
files, logs, backups, or Cloudflare credentials.

## Required Fields

### Identity

- `id`: stable workload ID matching `config/workloads.json`
- `name`: human-readable name
- `description`: short operator-facing description
- `canonicalRoot`: `/srv/oreo-cloud/workloads/<id>`
- `sourcePath`: `/srv/oreo-cloud/workloads/<id>/source`

### Runtime

The `runtime` object tells CLIs how to operate the workload without guessing.

- `type`: `docker-compose`, `docker`, `static`, `external`, or `unknown`
- `composePath`: canonical Compose path when applicable
- `composeProject`: explicit Compose project name
- `service`: optional Compose service/container name
- `legacyComposePaths`: prior Compose paths retained for rollback context

Compose operations must use explicit `composePath` and `composeProject` values.

### Migration

The `migration` object records whether the workload has moved into the canonical
layout and how to roll it back.

- `status`: `planned`, `in-progress`, `migrated`, `deferred`, `rollback-required`, or `needs-discovery`
- `originalPath`: pre-migration path
- `backupPath`: migration backup path, if any
- `compatibilitySymlink`: whether the old path is now a symlink
- `migratedAt`: ISO-8601 timestamp when migration completed
- `lastHealthCheck`: ISO-8601 timestamp of the last migration health check
- `rollback`: short rollback note or command summary
- `notes`: safe operator notes

### Operations

The `operations` object is policy-facing. Commands must refuse actions that are
not explicitly allowed here.

- `logsAllowed`: allows `oreo-logs`
- `restartAllowed`: allows `oreo-restart`
- `backupAllowed`: allows `oreo-backup-run`
- `dashboardActionsAllowed`: allows authenticated dashboard operation previews
- `approvedForCloudflareProtectedDemo`: marks a low-risk demo candidate
- `requiresConfirmation`: requires exact workload ID confirmation for mutations

Defaults should be false unless the workload has been reviewed.

### Backup

The `backup` object describes what can be backed up and where planning output
should point.

- `status`: `planned`, `configured`, `blocked`, `not-applicable`, or `needs-discovery`
- `source`: whether source code should be backed up
- `env`: whether env files are explicitly included
- `namedVolumes`: Docker named volumes to include
- `bindMounts`: bind mounts to include
- `database`: database dump/restore metadata
- `destination`: ignored runtime backup destination
- `retention`: retention policy text
- `restoreTested`: whether restore was tested
- `lastBackupAt`: ISO-8601 timestamp of last backup
- `lastRestoreTestAt`: ISO-8601 timestamp of last restore test

Backups belong under ignored runtime paths such as:

```text
/srv/oreo-cloud/runtime/backups/<workload-id>
```

Backup commands must not include secrets unless explicitly configured and
documented for that workload.

### Security

The `security` object keeps sensitive boundaries visible.

- `trackedByOreoCloudGit`: normally false for source/runtime content
- `classification`: mirrors or summarizes privacy state
- `publicExposureAllowed`: normally false
- `forbiddenTargets`: blocked exposure targets such as `postgres`, `docker-socket`, or `ssh`
- `notes`: safe notes only

## Example

```json
{
  "id": "demo-app",
  "name": "Demo App",
  "description": "Low-risk demo workload.",
  "canonicalRoot": "/srv/oreo-cloud/workloads/demo-app",
  "sourcePath": "/srv/oreo-cloud/workloads/demo-app/source",
  "runtime": {
    "type": "docker-compose",
    "composePath": "/srv/oreo-cloud/workloads/demo-app/source/docker-compose.yml",
    "composeProject": "demo-app",
    "service": "",
    "legacyComposePaths": []
  },
  "migration": {
    "status": "planned",
    "originalPath": "",
    "backupPath": "",
    "compatibilitySymlink": false,
    "migratedAt": "",
    "lastHealthCheck": "",
    "rollback": "",
    "notes": []
  },
  "operations": {
    "logsAllowed": false,
    "restartAllowed": false,
    "backupAllowed": false,
    "dashboardActionsAllowed": false,
    "approvedForCloudflareProtectedDemo": false,
    "requiresConfirmation": true
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
    "restoreTested": false,
    "lastBackupAt": "",
    "lastRestoreTestAt": ""
  },
  "security": {
    "trackedByOreoCloudGit": false,
    "classification": "unclassified",
    "publicExposureAllowed": false,
    "forbiddenTargets": [],
    "notes": []
  }
}
```

## Compatibility With P0

P0 registries remain authoritative for dashboard cards:

- `config/workloads.json`
- `config/privacy.json`
- `config/access.json`
- `config/routes.json`

P1 manifests add richer per-workload metadata for operations and migration.
Dashboard and CLI code should treat missing manifest fields as safe defaults:

- operation permissions default to false
- backup status defaults to `planned` or `needs-discovery`
- migration status can fall back to `config/workloads.json`
- source tracking defaults to false

This lets P1 add manifests one workload at a time without breaking existing P0
dashboard and CLI behavior.
