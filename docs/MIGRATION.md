# Workload Migration Plan

## Goal

Allow existing workload files to move into Argus's canonical organization:

```text
/srv/argus/workloads/<workload-id>/source
```

while preserving runtime behavior, volumes, paths, and rollback options.

## Canonical Layout

```text
/srv/argus/workloads/<id>/
├── README.md
├── manifest.json
└── source/          # ignored by Argus Git
```

Optional ignored directories:

```text
data/
env/
backups/
runtime/
logs/
```

## Migration Rules

1. Move one workload at a time.
2. Discover Compose project name before moving.
3. Discover Compose file path before moving.
4. Discover bind mounts and named volumes before moving.
5. Copy first, validate, then cut over.
6. Preserve old path with a symlink when useful.
7. Preserve Compose project name using `-p` or `COMPOSE_PROJECT_NAME`.
8. Preserve named volumes.
9. Do not commit workload source, `.env`, secrets, runtime data, database files, or backups.
10. Run health checks after migration.
11. Roll back if health fails.

## Discovery Commands

```bash
echo "## Compose labels"
docker ps --format 'table {{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}\t{{.Label "com.docker.compose.project.config_files"}}' || true

echo "## Container mounts"
docker inspect \
  --format '{{.Name}} {{range .Mounts}}{{.Type}}:{{.Source}}->{{.Destination}}; {{end}}' \
  $(docker ps -q) 2>/dev/null || true

echo "## Existing compose files"
find /home /srv -maxdepth 5 \( -iname 'docker-compose*.yml' -o -iname 'docker-compose*.yaml' -o -iname 'compose.yml' -o -iname 'compose.yaml' \) 2>/dev/null | sort || true

echo "## Existing env files, names only"
find /home /srv -maxdepth 5 \( -iname '.env' -o -iname '.env.*' \) 2>/dev/null | sort || true
```

Do not print `.env` contents.

## Migration Plan Command

Create:

```text
scripts/argus-migrate-workload-plan
```

Usage:

```bash
argus-migrate-workload-plan intake-os
```

Output must include:

- current root
- target root
- source path
- Compose file
- Compose project name
- health URL
- legacy path
- bind mount risks
- named volume risks
- suggested copy command
- suggested validation command
- suggested cutover command
- rollback command

The planner must not move files or restart services.

## Copy-Validate-Cutover Pattern

Example variables:

```bash
WORKLOAD_ID="intake-os"
OLD_ROOT="/home/oreo/intake-os"
NEW_ROOT="/srv/argus/workloads/intake-os"
NEW_SOURCE="/srv/argus/workloads/intake-os/source"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="/srv/argus/runtime/migration-backups/${WORKLOAD_ID}.${TIMESTAMP}"
```

Copy:

```bash
sudo install -d -o argus -g argus "$NEW_ROOT"
rsync -aH --numeric-ids "$OLD_ROOT/" "$NEW_SOURCE/"
```

Validate Compose:

```bash
docker compose \
  -f "$NEW_SOURCE/docker-compose.server.yml" \
  -p intake-os \
  config >/tmp/intake-os.compose.validated.yml
```

Cut over only after validation.

```bash
docker compose \
  -f "$OLD_ROOT/docker-compose.server.yml" \
  -p intake-os \
  down

sudo mv "$OLD_ROOT" "$BACKUP_ROOT"
sudo ln -s "$NEW_SOURCE" "$OLD_ROOT"
sudo chown -h argus:argus "$OLD_ROOT"

docker compose \
  -f "$NEW_SOURCE/docker-compose.server.yml" \
  -p intake-os \
  up -d
```

Health check:

```bash
argus-health
docker compose -f "$NEW_SOURCE/docker-compose.server.yml" -p intake-os ps
```

## Rollback Pattern

```bash
docker compose \
  -f "$NEW_SOURCE/docker-compose.server.yml" \
  -p intake-os \
  down || true

sudo rm "$OLD_ROOT"
sudo mv "$BACKUP_ROOT" "$OLD_ROOT"

docker compose \
  -f "$OLD_ROOT/docker-compose.server.yml" \
  -p intake-os \
  up -d
```

## Manifest

Each workload should have:

```text
/srv/argus/workloads/<id>/manifest.json
```

Example:

```json
{
  "id": "intake-os",
  "name": "Intake OS",
  "canonicalRoot": "/srv/argus/workloads/intake-os",
  "sourcePath": "/srv/argus/workloads/intake-os/source",
  "legacyPaths": ["/home/oreo/intake-os"],
  "compose": {
    "enabled": true,
    "path": "/srv/argus/workloads/intake-os/source/docker-compose.server.yml",
    "project": "intake-os",
    "service": ""
  },
  "migration": {
    "status": "planned",
    "originalPath": "/home/oreo/intake-os",
    "backupPath": "",
    "symlinkCreated": false,
    "migratedAt": "",
    "rollback": "Restore original directory from backup path and restart compose with preserved project name."
  },
  "git": {
    "trackedByArgusGit": false,
    "notes": ["Do not commit source, secrets, env, data, logs, or backups."]
  }
}
```
