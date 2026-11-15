# Cloudflare Workspace

This directory contains planning artifacts for Cloudflare exposure guardrails.

Argus must not:

- run `cloudflared` outside the allowlisted activation flow below
- create tunnels or DNS records (operator steps at Cloudflare)
- store tokens or credentials
- expose the dashboard or control API
- use quick tunnels
- publish any workload or hostname outside `cloudflare.publicAllowlist`
  (see `docs/CLOUDFLARE.md` and D027)

Run:

```bash
argus-cloudflare-plan
```

The command rewrites `cloudflare/planned-ingress.yml` from the current config and
prints requested, blocked, and generated routes.

Activation of an allowlisted route uses `argus-cloudflare-activate-preview`,
`argus-cloudflare-activate` and `argus-cloudflare-rollback`; see
`docs/CLOUDFLARE.md`. The former `hello-nginx` activation is historical; see
`docs/RETIRED_HELLO_NGINX.md`.
