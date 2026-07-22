# Argus Templates

These templates are starter material for another private Argus-style
checkout. They are not deployment automation.

## Rules

- Replace placeholder hostnames, users, paths, and Tailscale IPs before use.
- Do not copy secrets into templates.
- Do not enable public routes by default.
- Do not enable Cloudflare tunnels, DNS, or Tailscale Funnel from templates.
- Validate JSON examples with `python3 -m json.tool`.
- Validate Caddy on the server before reload.

## Contents

- `config/`: example registry files.
- `systemd/`: service and timer unit templates.
- `caddy/`: private dashboard route example.
- `cloudflare/`: plan-only Cloudflare examples.
- `scripts/`: discovery/bootstrap examples.

Run from a checkout:

```bash
scripts/argus-template-check
```
