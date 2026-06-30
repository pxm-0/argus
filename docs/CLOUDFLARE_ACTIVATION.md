# P2 Cloudflare Protected Activation

P2-07 adds the guarded activation path for the `hello-nginx` protected
Cloudflare demo route.

Current status: blocked by external prerequisites.

No tunnel, DNS record, public route, or service restart is created by this
documentation or by activation preview.

## Current Blockers

The checked-in P2 config still uses the planning hostname:

```text
hello-nginx.oreo-cloud.invalid
```

Activation must not proceed until an operator provides:

- a real approved hostname
- a Cloudflare named tunnel
- tunnel credentials stored outside Git
- Cloudflare Access application and policy for the hostname
- confirmation that unauthenticated requests are blocked by Access

Quick tunnels, `cloudflare-public`, dashboard routes, the control API,
PostgreSQL, Docker socket targets, host SSH, admin tools, restricted workloads,
and sensitive workloads remain forbidden for P2 activation.

## Preview

Run:

```bash
scripts/oreo-cloudflare-activate-preview hello-nginx
```

The preview reads:

- `config/access.json`
- `config/routes.json`
- `config/exposure.json`
- `config/privacy.json`
- `config/policy.json`

It prints blockers, planned ingress, required manual Cloudflare checks, and
modifies nothing. In the current repo state it must exit blocked because the
hostname is `.invalid`, Cloudflare is not provisioned, and named tunnels are not
enabled in exposure policy.

## Activation

After external prerequisites are satisfied, activation requires exact
confirmations:

```bash
scripts/oreo-cloudflare-activate hello-nginx \
  --confirm-workload hello-nginx \
  --confirm-hostname hello-nginx.example.com \
  --confirm-access-protected "cloudflare access protects this hostname"
```

The activation command refuses to continue unless preview has no blockers. When
unblocked, it writes the generated ingress config outside Git, validates it with
`cloudflared tunnel ingress validate`, reloads `cloudflared`, probes the
external hostname unauthenticated, and updates effective access only if the
probe is blocked by Cloudflare Access.

Activation evidence is written under:

```text
runtime/cloudflare-activation/
```

The runtime evidence directory is ignored by Git.

## Rollback

Preview rollback:

```bash
scripts/oreo-cloudflare-rollback hello-nginx
```

Apply rollback only after confirmation:

```bash
scripts/oreo-cloudflare-rollback hello-nginx \
  --apply \
  --confirm-workload hello-nginx
```

Rollback lowers effective access back to `local`, preserves prior activation
evidence, writes an audit event, regenerates dashboard state, and reloads
`cloudflared` unless `--no-reload` is provided.

## P2-07 Result

Because the real hostname and Cloudflare Access prerequisites are not present in
the repo or on the server, P2-07 lands the activation guardrails and records the
blocker. It does not substitute an unauthenticated public route.
