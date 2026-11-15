# Cloudflare Exposure

## Goal

Cloudflare is a per-workload access provider, never the default platform access
method. Everything stays deny-by-default. The only routes that may become
reachable through Cloudflare are the entries in `cloudflare.publicAllowlist` in
`config/exposure.json`, as authorized by decision
[D027](ARGUS_V1_DECISIONS.md). Its threat model and rollback are in
[NODENS_PUBLIC_ROUTE.md](NODENS_PUBLIC_ROUTE.md).

## Standing Rules

- Named tunnels only. Quick Tunnels (`allowQuickTunnels`) stay `false`.
- Tunnel credentials stay on the server, outside Git.
- Creating the tunnel and its DNS records are operator steps at Cloudflare;
  Argus never creates them.
- Never expose the dashboard, the control API, PostgreSQL, the Docker socket or
  host SSH. The control API still accepts only `none`, `local` and `tailnet`;
  Cloudflare states are CLI-only.
- Every ingress config ends in an `http_status:404` catch-all and names only
  allowlisted hostnames.

## Access States

```text
cloudflare-protected   behind Cloudflare Access, limited to the operator
cloudflare-public      reachable without authentication
```

Either state can be requested (desired) and planned for any workload policy
allows. It becomes effective only when all of these hold:

1. the workload and its route hostname are in `cloudflare.publicAllowlist`;
2. the provider is `enabled`, `provisioned` and `allowNamedTunnels`, with Quick
   Tunnels off;
3. activation evidence is recorded under `runtime/cloudflare-activation/`: a
   protected-stage probe answering 401/403 without an Access session, and for
   `cloudflare-public` also a later public-stage probe answering 200.

Policy, `argus-doctor`, `argus-access-reconcile` and `smoke-test` all apply this
rule, so a workload or hostname outside the allowlist fails closed. Smoke also
fails if the provider is enabled with an empty allowlist, or if `cloudflared` is
running while the provider is disabled or with ingress hostnames outside the
allowlist.

## Allowlist

```json
"publicAllowlist": [
  {"workloadId": "example-site", "hostnames": ["example.com", "www.example.com"]}
]
```

Hostnames are exact lowercase DNS names (no wildcards, no `.invalid`). Any
malformed entry allows nothing. The allowlist ships empty; adding an entry needs
its own reviewed decision and pull request.

## Planned Ingress Generator

`argus-cloudflare-plan` runs `cloudflare/generate_cloudflare_config.py`, which
reads the workload, access, route and exposure config, keeps workloads whose
desired access is a Cloudflare state that policy allows, requires a hostname,
appends the `http_status:404` catch-all and rewrites
`cloudflare/planned-ingress.yml`. It is plan-only: it never runs `cloudflared`,
touches DNS or writes credentials. `argus-doctor` fails when that plan names a
hostname that is not allowlisted for the workload whose route names it, or when
the catch-all is missing.

## Activation

Run on the server, one stage at a time:

```bash
scripts/argus-cloudflare-activate-preview <workload> --mode protected
scripts/argus-cloudflare-activate <workload> --mode protected \
  --confirm-workload <workload> --confirm-hostname <hostname> \
  --confirm-phrase "cloudflare access protects this hostname"
```

Activation refuses any workload or hostname outside the allowlist. It rewrites
only that workload's rules in the cloudflared config (keeping the tunnel
settings and the catch-all), validates the candidate with
`cloudflared tunnel ingress validate` before installing it, reloads the
connector and probes the hostname without credentials. Protected mode needs a
401/403 answer. If the probe or reload fails, the previous ingress is restored.
On success it writes evidence, sets the effective state through the policy gate
and records an audit event.

`--mode public` additionally requires recorded protected-stage evidence for the
same workload and hostname, a route with `mode: public` and
`requiresAuth: false`, a manifest with `security.publicAllowed: true`, and the
policy phrase `publish publicly`. Its probe must answer 200.

## Rollback

```bash
scripts/argus-cloudflare-rollback <workload>
scripts/argus-cloudflare-rollback <workload> --apply --confirm-workload <workload>
```

The first command previews. `--apply` removes the workload's hostnames from the
ingress (leaving the catch-all), validates, reloads the connector and lowers the
effective access to `tailnet`. Evidence is kept. Stopping the connector service
also cuts all Cloudflare traffic at once.

## Policy Requirements

- `restricted` or `sensitive` -> `cloudflare-public`: blocked.
- `cloudflare-public` effective additionally requires `unclassified` or
  `personal` privacy.
- `cloudflare-protected` and `cloudflare-public` both require their typed
  confirmation phrase.
