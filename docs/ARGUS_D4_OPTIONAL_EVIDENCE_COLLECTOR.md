# D4 optional evidence collectors

D4 adds three independently bounded, read-only sources to the observation
registry:

| Source | Evidence | Deliberate omission |
| --- | --- | --- |
| `oreochiserver.process-listeners` | stable daemon-class names/states and listener protocol/port/address scope | transient helpers, PIDs, addresses, command lines, environments, and payloads |
| `oreochiserver.proxy-overlay` | Caddy, Tailscale Serve/Funnel, and cloudflared availability/state | URLs, hosts, route paths, tokens, and provider payloads |
| `oreochiserver.configured-roots` | bounded counts, JSON validity, and content digests for the reviewed `workloads` and `config` roots | filesystem paths, filenames, file contents, and repository remotes |

Each source has its own command/API allowlist, output and record bounds,
attribute minimization, Unix socket identity, and gap code. A missing optional
provider is recorded as a sanitized provider state plus a stable partial gap;
the collector never starts a provider or changes a route.

The service template runs as `oreo:argus-control`, reads only the reviewed
configuration/workload roots, and exposes one socket per source. It has no
Docker socket, credentials, mutation API, or public network route.

## Acceptance

Run the fixture contract locally:

```text
PYTHONPATH=scripts scripts/argus-d4-optional-evidence-acceptance \
  --root . --source-revision <revision> \
  --captured-at 2026-08-11T00:00:00Z --target local-ci
```

Live acceptance is run only from a clean reviewed checkout on
`oreochiserver`, with temporary root-owned source projections and socket
parents. It repeats the scheduler three times and requires stable sanitized
measurements; provider gaps remain visible in the result.

## Removal

Stop and disable only the three `argus-optional-evidence-collector@*.service`
instances, remove their source projections after socket removal, and retain
the observation history as inactive. No workload, daemon, database, route,
DNS, Funnel, or Cloudflare mutation is part of D4.
