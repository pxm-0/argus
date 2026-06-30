# Cloudflare Workspace

This directory contains planning artifacts for Cloudflare exposure and P2
protected activation guardrails.

Oreo Cloud must not:

- start `cloudflared`
- create a tunnel
- create DNS records
- store tokens or credentials
- expose the dashboard or control API
- use quick tunnels
- use `cloudflare-public` in P2

Run:

```bash
oreo-cloudflare-plan
oreo-cloudflare-activate-preview hello-nginx
```

The command rewrites `cloudflare/planned-ingress.yml` from the current config and
prints requested, blocked, and generated routes.

Activation remains blocked until a real hostname, named tunnel credentials, and
Cloudflare Access policy are provided outside Git. See
`docs/CLOUDFLARE_ACTIVATION.md`.
