# D1b Authenticated Collector Protocol and Scheduler

Issue: `#307`

Collector protocol: current `2`, immediately previous `1`

Source registry: current `2`, immediately previous readable `1`

## Boundary and outcome

D1b adds deterministic, read-only local transport and bounded scheduling above
the D1a repository. It adds no live collector, API endpoint, UI, reconciliation
admission, operation authority, workload mutation, Docker socket, arbitrary
command execution, public route, or AI/model path. The production source registry
remains empty, so refresh remains visibly `not-configured` until separately
reviewed native collectors are installed.

## Exact local binding

Registry version 2 gives every source one absolute Unix-stream socket path and
its direct absolute parent. It pins parent and socket type, numeric UID/GID, and
octal mode, plus expected peer UID/GID and supported protocol versions. The
client rejects symlinked parents, changed socket inodes, and binding mismatches.
Linux verifies `SO_PEERCRED`; macOS verifies the fixed libc `getpeereid` symbol
through the explicitly declared native-load boundary. Either required platform
fails closed if its peer-credential primitive is unavailable.

Only a request-only `collect` method exists. The central process never receives
a native command, raw Docker socket, environment, file content, Git remote, or
credential. Collector bootstrap and removal remain reviewed source metadata;
D1b does not install or remove units.

## Request and pages

Requests bind protocol, refresh, run, source, host, trust domain, and explicit
clock. Each response page repeats that identity and adds an increasing sequence,
terminal marker/state, page and cumulative record/byte counts, a running digest,
an optional stable gap code, and normalized D1a records. Unknown fields and
values fail closed. A terminal `completed` page has no gap; `partial` retains
validated records and a gap; `failed` has a gap and no records. The collector
must close its write side immediately after the terminal frame; any trailing
byte, appended frame, or missing EOF fails closed.

The running digest is a canonical JSON hash chain. Its initial value is the D1a
`digest({"collectorRequest": <exact request>})`. Each page replaces it with
`digest({"previousDigest": <prior>, "sequence": <page sequence>,
"pageDigest": digest({"sourceId": <source>, "records": <normalized page>}),
"cumulativeRecordCount": <count>, "cumulativeByteCount": <bytes>})`. This
binds page partition, order, identity, and cumulative bounds without repeatedly
rehashing all prior records.

Each frame is limited to 64 KiB before JSON allocation. Registry record,
per-record, and cumulative byte bounds are re-applied after normalization. Page
count is bounded by `maxRecords + 1`, allowing one terminal page after the
maximum possible one-record pages; nonterminal empty pages are invalid. One
monotonic per-source deadline covers
connect, request, and all pages, so a peer cannot extend its budget by dripping
valid frames.

## Scheduling and replay

The scheduler accepts an explicit refresh ID and clock, caps workers at 32,
applies source and global deadlines, and collects independent sources in
parallel. It commits validated results in sorted source order. Sequence numbers
are allocated under the repository's `BEGIN IMMEDIATE` transaction, preventing
cross-process collisions. The per-source run ID is derived from refresh and
source identity; replay returns the already persisted terminal result.

A failed source never discards another source's completed result. Partial and
failed runs preserve the last-known-good current pointer and expose a
source-specific gap. Empty configured sources can complete successfully; an
empty production registry returns `not-configured`, never complete.

## Rolling deployment and recovery

Version 2 clients negotiate the highest common version from exactly versions 1
and 2. Deploy collectors that support both versions before removing version 1
from a source. Future, too-old, or identity-mismatched envelopes fail closed.
After a disconnect, timeout, restart, or protocol failure, retain the last-known-
good snapshot, inspect only operator-owned local logs, repair the collector, and
retry with a new refresh ID. Remove a collector by stopping its separately
reviewed unit, removing its socket, and then removing its reviewed source entry;
retained history becomes inactive under the D1a rules.

At exclusive scheduler startup, call D1a interrupted-run recovery before
accepting refresh requests. Per-refresh code must not run global recovery while
another scheduler process may own an active reservation.

## Verification

Local conformance:

```text
python3 -m unittest tests.test_argus_observations tests.test_argus_collectors -v
scripts/argus-collector-protocol-acceptance \
  --root <reviewed-checkout> \
  --source-revision <commit> \
  --captured-at <UTC timestamp> \
  --target local-ci
scripts/argus-check
```

Authoritative acceptance runs the same current/previous socket collectors and
scheduler three times from a clean reviewed checkout on `oreochiserver` with
temporary sockets and databases only. It does not touch deployed configuration,
services, collectors, workloads, or network exposure:

```text
scripts/argus-collector-protocol-acceptance \
  --root <reviewed-checkout> \
  --source-revision <commit> \
  --captured-at <UTC timestamp> \
  --target oreochiserver > <operator-only-summary.json>
scripts/argus-acceptance-summary --input <operator-only-summary.json> --format markdown
```
