# Cloudflare Plan-Only Workspace

This directory contains planning artifacts for a future Cloudflare exposure phase.
P0 generates files only.

P0 must not:

- start `cloudflared`
- create a tunnel
- create DNS records
- store tokens or credentials
- expose the dashboard or control API

Run:

```bash
oreo-cloudflare-plan
```

The command rewrites `cloudflare/planned-ingress.yml` from the current config and
prints requested, blocked, and generated routes.

Credentials belong outside Git, such as `/etc/cloudflared`, in a later explicit
activation phase.
