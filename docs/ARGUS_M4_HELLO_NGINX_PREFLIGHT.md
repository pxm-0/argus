# Argus M4 hello-nginx Preflight

This is a read-only gate for the first M4 pilot: `hello-nginx` into the empty
`personal-sandbox` cell. It does not start, stop, import, copy, mount, expose,
or migrate a workload.

After creating a fresh source-only backup and matching non-destructive restore
test, run this only on `oreochiserver`:

```bash
cd /srv/oreo-cloud
sudo python3 scripts/argus-m4-hello-nginx-preflight \
  --backup /srv/oreo-cloud/runtime/backups/hello-nginx/YYYYMMDD-HHMMSS \
  --restore-test /srv/oreo-cloud/runtime/restore-tests/hello-nginx/YYYYMMDD-HHMMSS
```

The command verifies the backup archive checksum, restored Compose source,
source health, active target daemon and socket, empty target Docker state, and
the target namespace's lack of TCP listeners. It stores only the redacted result
at `runtime/argus/m4/hello-nginx-preflight.json` and still reports
`migrationApproved: false`.

The next step remains a reviewed, explicit cutover plan. In particular, it must
not use host-path mounts, host networking, published ports, or a public route.
