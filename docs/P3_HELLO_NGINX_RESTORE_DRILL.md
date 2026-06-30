# P3 hello-nginx Restore Drill

P3-01 proves the latest approved `hello-nginx` backup artifact can be restored
into an ignored runtime test directory without replacing the live workload.

- Verified on: 2026-06-30T22:03Z
- Server: `oreochiserver`
- Branch during drill: `main`
- Backup artifact: `/srv/oreo-cloud/runtime/backups/hello-nginx/20260630-202443`
- Restore test directory: `/srv/oreo-cloud/runtime/restore-tests/hello-nginx/20260630-220308`
- P3 issue: `#79`

## Backup Artifact

Latest artifact:

```text
runtime/backups/hello-nginx/20260630-202443
```

Artifact files:

```text
backup-summary.json
checksums.sha256
files.tar.gz
manifest.json
restore-plan.md
```

Backup summary:

```json
{
  "artifactPath": "/srv/oreo-cloud/runtime/backups/hello-nginx/20260630-202443",
  "createdAt": "2026-06-30T20:24:43Z",
  "databaseIncluded": false,
  "destination": "/srv/oreo-cloud/runtime/backups/hello-nginx",
  "envIncluded": false,
  "redacted": true,
  "sourceIncluded": true,
  "version": 1,
  "volumesIncluded": false,
  "workloadId": "hello-nginx"
}
```

Checksums:

```text
3b02d9dbc382b08ce10c03623224d1275c811c64ff0edad3997b04263d7162dc  backup-summary.json
b3c8b58ad427e2566fbbca43e40f7f7a8ebf86795ff338d928d09920fefb8d5e  files.tar.gz
d6691d9b502a75a568e9d51644ba530bdb890ec03e85a443213de835528451bb  manifest.json
f2adc05c10c6888609a4ac627afc7318828678c990fa8d77448df89929a5ed9c  restore-plan.md
```

## Drill Commands

```bash
cd /srv/oreo-cloud
latest=$(find runtime/backups/hello-nginx -maxdepth 1 -mindepth 1 -type d -print | sort | tail -1)
restore_dir="runtime/restore-tests/hello-nginx/20260630-220308"
mkdir -p "$restore_dir/extracted"
python3 - <<'PY' "$latest"
import hashlib, sys
from pathlib import Path

root = Path(sys.argv[1])
for line in (root / "checksums.sha256").read_text().splitlines():
    expected, _, name = line.partition("  ")
    path = root / name
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"checksum mismatch: {name}")
print("CHECKSUMS_OK true")
PY
cp "$latest/manifest.json" "$restore_dir/manifest.json"
cp "$latest/backup-summary.json" "$restore_dir/backup-summary.json"
cp "$latest/restore-plan.md" "$restore_dir/restore-plan.md"
tar -xzf "$latest/files.tar.gz" -C "$restore_dir/extracted"
```

## Restored Files

```text
runtime/restore-tests/hello-nginx/20260630-220308/backup-summary.json
runtime/restore-tests/hello-nginx/20260630-220308/extracted/source/docker-compose.yml
runtime/restore-tests/hello-nginx/20260630-220308/manifest.json
runtime/restore-tests/hello-nginx/20260630-220308/restore-plan.md
```

Expected source file was recovered:

```text
source/docker-compose.yml present
```

The restored compose file matched the live tracked compose file:

```text
c5bf9d7674fa25a4498b0ea7d9b9ef369009bc351c1f4ca0b4391c1c4553c0e7  workloads/hello-nginx/source/docker-compose.yml
c5bf9d7674fa25a4498b0ea7d9b9ef369009bc351c1f4ca0b4391c1c4553c0e7  runtime/restore-tests/hello-nginx/20260630-220308/extracted/source/docker-compose.yml
```

## Git Safety

The restore-test directory is ignored by Git:

```text
.gitignore:2:runtime/*  runtime/restore-tests/hello-nginx/20260630-220308
.gitignore:2:runtime/*  runtime/restore-tests/hello-nginx/20260630-220308/extracted/source/docker-compose.yml
```

The drill did not replace the live workload, restart containers, expose any
service, copy secrets, or restore into production.

## Post-Drill Verification

`scripts/smoke-test` passed on `oreochiserver` after the restore drill:

```text
PASS Cloudflare rollback preview works
PASS effective access reconcile clean
PASS no Funnel detected
PASS no unexpected cloudflared active
PASS no tracked secrets
PASS doctor security audit clean
PASS workload CLI works
PASS health CLI works
PASS Caddy dashboard route generated
PASS Caddy route is private
PASS planned Caddy route validates
PASS live Caddy validates

Smoke summary: 0 failure(s), 0 warning(s)
```

Server status remained clean:

```text
## main...origin/main
```

## Result

P3-01 acceptance is satisfied:

- backup artifact exists
- checksums validate
- restore test is non-destructive
- expected source files were recovered
- restore-test artifacts are ignored
- smoke passes afterward
