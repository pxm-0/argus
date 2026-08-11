# D2b Rootless-Domain Docker Collectors

D2b adds one read-only collector for each configured rootless trust domain:

| Source | Daemon identity | Daemon socket | Collector socket |
| --- | ---: | --- | --- |
| `oreochiserver.personal-sandbox.rootless-docker` | `1002` / `argus-control` | `/var/lib/argus/personal-sandbox/docker.sock` | `/run/argus/collectors/personal-sandbox-rootless-docker/collector.sock` |
| `oreochiserver.work-sandbox.rootless-docker` | `1003` / `argus-control` | `/var/lib/argus/work-sandbox/docker.sock` | `/run/argus/collectors/work-sandbox-rootless-docker/collector.sock` |

The collectors reuse the bounded D2a Docker Engine GET allowlist and D1b
authenticated paging. Each source has its own execution identity, daemon
socket binding, source projection, collector socket, and systemd instance.
Missing or unhealthy domain daemons become source-specific gap evidence; they
do not become an estate-wide success.

## Review and installation

Run from the reviewed checkout on `oreochiserver`:

```text
ARGUS_ROOTLESS_DOMAIN=personal-sandbox sudo scripts/argus-d2b-rootless-docker-collector --preflight
ARGUS_ROOTLESS_DOMAIN=personal-sandbox sudo scripts/argus-d2b-rootless-docker-collector \
  --apply --acknowledge-d2b-rootless-docker-collector
ARGUS_ROOTLESS_DOMAIN=personal-sandbox sudo scripts/argus-d2b-rootless-docker-collector --status
```

Repeat for `work-sandbox`. The installer snapshots any existing reviewed unit,
source projection, and socket environment before replacement. Removal and
rollback are explicit acknowledged operations. It never stops, recreates, or
inspects workload containers.

The control API unit denies both rootless daemon sockets as well as the rootful
Docker aliases. It receives only the collector socket through the `argus-control`
group; the workload sockets are never mounted into the API namespace.

## Acceptance

Fixture acceptance is deterministic and does not contact a daemon:

```text
scripts/argus-d2b-rootless-docker-acceptance \
  --root . --source-revision <revision> \
  --captured-at 2026-08-05T00:00:00Z --target local-ci
```

After both reviewed instances are installed, run the same command on
`oreochiserver` as the pinned collector client with `--target oreochiserver`.
The command requires three identical completed runs for both sources and
emits only aggregate evidence and digests.

Estate refresh remains refused until D5 reconciliation consumes all required
host, domain, service, and route sources.
