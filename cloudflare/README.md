# Cloudflare Workspace

This directory contains planning artifacts for Cloudflare exposure guardrails.

Argus must not:

- start `cloudflared`
- create a tunnel
- create DNS records
- store tokens or credentials
- expose the dashboard or control API
- use quick tunnels
- use `cloudflare-public` in P2

Run:

```bash
argus-cloudflare-plan
```

The command rewrites `cloudflare/planned-ingress.yml` from the current config and
prints requested, blocked, and generated routes.

No active Argus workload requests Cloudflare exposure. The former
`hello-nginx` activation path was retired with the workload; see
`docs/RETIRED_HELLO_NGINX.md`.
