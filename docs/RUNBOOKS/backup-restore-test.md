# Backup Restore Test: hello-nginx

P2 backup execution is enabled only for `hello-nginx`.

## Backup Command

```bash
cd /srv/argus
scripts/argus-backup-run hello-nginx --confirm hello-nginx
```

Expected artifact shape:

```text
/srv/argus/runtime/backups/hello-nginx/YYYYMMDD-HHMMSS/
├── manifest.json
├── files.tar.gz
├── checksums.sha256
├── restore-plan.md
└── backup-summary.json
```

## Non-Destructive Restore Test

Do not replace the live workload. Extract the latest backup into ignored runtime
restore-test space:

```bash
latest="$(find /srv/argus/runtime/backups/hello-nginx -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
restore_dir="/srv/argus/runtime/restore-tests/hello-nginx/$(basename "$latest")"
mkdir -p "$restore_dir"
tar -xzf "$latest/files.tar.gz" -C "$restore_dir"
test -f "$restore_dir/source/docker-compose.yml"
python3 -m json.tool "$latest/manifest.json" >/dev/null
python3 -m json.tool "$latest/backup-summary.json" >/dev/null
```

## P2 Result

The P2 PR records the exact backup artifact path and restore-test directory from
`oreochiserver`.
