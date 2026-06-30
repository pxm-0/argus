# Effective Access Reconciliation

P2-08 makes desired/effective access state checkable instead of trusting stale
discovery records.

## Server Evidence

Read-only discovery was run on `oreochiserver` before changing access state:

```bash
cd /srv/oreo-cloud
git status --short --branch
tailscale funnel status
systemctl is-active cloudflared
ss -tulpen | grep -E ':(8099|8088|18080|8765)'
```

Result:

```text
## main...origin/main
No serve config
inactive
127.0.0.1:8765
127.0.0.1:8099
127.0.0.1:18080
```

That evidence shows the checked-in Tailscale Funnel observation for
`review-ui` was stale. P2-08 reconciles it by recording Funnel as not observed
and lowering `review-ui` effective access to `local`. Desired access remains
`tailnet` for future private routing work.

## Command

Run:

```bash
scripts/oreo-access-reconcile
```

For local/offline CI:

```bash
scripts/oreo-access-reconcile --offline --json
```

The command:

- reads `access.json`, `routes.json`, `exposure.json`, `privacy.json`, and
  `workloads.json`
- detects forbidden `cloudflare-public` effective state
- fails if Cloudflare effective access lacks route, provider, named tunnel,
  real hostname, or activation evidence
- fails if tracked config still reports Tailscale Funnel enabled
- warns, but does not fail, when app HTTP probes are unavailable
- never raises exposure automatically

## Apply Mode

Apply mode is intentionally narrow:

```bash
scripts/oreo-access-reconcile --apply
```

It may only lower `cloudflare-protected` effective access back to `local` when
drift is detected. It does not enable Tailnet, Cloudflare, DNS, Funnel, router
ports, or public routes.

## P2-08 Result

Current reconciled state:

- `review-ui` desired: `tailnet`
- `review-ui` effective: `local`
- Tailscale Funnel observed: `false`
- `cloudflared`: inactive
- `hello-nginx` desired: `cloudflare-protected`
- `hello-nginx` effective: `local`

`hello-nginx` remains planned until P2-07 external prerequisites are provided
and activation verifies Cloudflare Access protection.
