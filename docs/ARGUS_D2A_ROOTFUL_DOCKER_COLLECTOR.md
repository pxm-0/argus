# D2a Rootful Docker Collector

Issue: `#309`

Docker Engine API: fixed `1.40` (accepted server range at implementation: `1.40`–`1.54`)

## Outcome and boundary

D2a adds the first live configured-estate source. It observes the rootful Docker
daemon through a dedicated local process and returns only D1b normalized pages.
It does not enable `argus estate refresh`, reconcile observations to canonical
workloads, admit unknown resources, mutate Docker, expose the Docker socket to
the API, or add any public or AI/model path.

The collector runs as static UID `950`, primary `argus-control` GID `981`, and
supplementary Docker GID `983`. Docker-group access is root-equivalent, so this
identity has no operation ledger, issuer, replay database, signing key, shell,
state directory, public listener, IP networking, or mutation method. The
control API retains its explicit `InaccessiblePaths` block for both Docker
socket spellings.

The service cannot read the checked-in configuration, control-plane, runtime,
test, or documentation trees. The installer atomically projects only the one
reviewed source record to
`/etc/argus/collectors/rootful-docker-source.json` as `root:argus-control`
mode `0640`; the collector pins that file before parsing it.

## Exact collection contract

The adapter sends only HTTP `GET` to these routes:

```text
/version
/v1.40/containers/json?all=1&size=0
/v1.40/containers/{listed-id}/json?size=0
/v1.40/images/json?all=1&digests=1
/v1.40/networks
/v1.40/volumes
```

Container detail IDs must be 64 lowercase hexadecimal characters returned by
the same bounded all-container response. API `1.40` is deterministic across a
daemon upgrade: the collector fails closed if the daemon minimum rises above
it or the daemon maximum falls below it. The Docker socket type, numeric owner,
group, mode, inode, and daemon peer credentials are pinned for the run.

Each raw response is capped at 8 MiB before JSON allocation and the complete
run at 32 MiB. The reviewed source additionally caps the normalized snapshot at
1,000 records, 2 MiB total, and 16 KiB per record. Pages target 48 KiB of record
data and remain below the D1b 64 KiB frame ceiling. One explicit clock becomes
every observation timestamp; input order is canonicalized before provenance,
paging, and hashing.

## Minimization

The source reports running and stopped containers, images, networks, and
volumes. Container fields are limited to lifecycle, name, exact Compose project
and service labels, an opaque image reference, health state without health
logs, restart policy, network references, minimized mounts, published-port
scope, and host-capability flags. Host mount sources and noncanonical image
references are hashed locally.

The adapter drops environments, commands, arbitrary labels, raw host paths,
file content, registry credentials, Git metadata, logs, health output, Docker
raw responses, and unreviewed options. Docker evidence remains observation,
never canonical policy or authorization.

## Authentication and failure

The central D1b client pins the collector UID/GID, parent/socket identity, and
envelope source/host/domain. The collector independently pins the client UID
`1000` and effective GID `981` before reading a request. Any wrong peer,
version, ID, shape, bound, timeout, replacement, or secret-hostile normalized
value becomes a stable failed source run. It never replaces last-known-good
evidence.

## Installation and rollback

From a reviewed `/srv/argus` checkout:

```text
sudo scripts/argus-d2a-rootful-docker-collector --preflight
sudo scripts/argus-d2a-rootful-docker-collector \
  --apply --acknowledge-d2a-rootful-docker-collector
sudo scripts/argus-d2a-rootful-docker-collector --status
```

Preflight validates exact host identities, Docker socket binding, JSON, and the
systemd unit before reload. Apply backs up any prior unit, creates only the
dedicated identity when absent, installs the reviewed unit, and verifies that
both Docker socket aliases in the API mount namespace are inert `root:root 000`
masks that reject even a root connection. It does not restart or
alter Docker, Caddy, the API, or any workload.

Removal/rollback stops only the collector, removes its socket/unit and exact
dedicated user, and leaves Docker and retained observation history untouched:

```text
sudo scripts/argus-d2a-rootful-docker-collector \
  --rollback --acknowledge-d2a-rootful-docker-collector
```

Deploying the previous reviewed Argus revision removes the source from the
configured denominator. Removing only the service leaves an explicit failed
source gap rather than a false completeness claim.

## Verification

```text
python3 -m unittest tests.test_argus_docker_collector -v
scripts/argus-d2a-rootful-docker-acceptance \
  --root <reviewed-checkout> \
  --source-revision <commit> \
  --captured-at <UTC timestamp> \
  --target local-ci
scripts/argus-check
```

Authoritative acceptance installs the reviewed unit on `oreochiserver`, runs
the acceptance as UID `1000`/GID `981`, compares only safe aggregate counts,
checks the pre-change +20% duration budget, repeats three times, and emits the
allowlisted acceptance summary. Names, labels, paths, and raw Docker payloads
are never printed or attached to the PR.
