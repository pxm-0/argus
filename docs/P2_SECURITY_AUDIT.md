# P2 Smoke and Security Audit

P2-09 expands continuous safety checks for Oreo Cloud.

## Smoke Additions

`scripts/smoke-test` now checks:

- `p1-complete` tag exists
- workload manifests validate
- dashboard generation does not dirty tracked static assets
- runtime dashboard state is ignored
- action endpoints require authentication
- logs preview remains capped and sanitized
- backup execution is gated by manifest policy
- Cloudflare activation blocks placeholder hostnames
- quick tunnels remain disabled
- rollback preview is available
- effective access reconcile is clean
- `oreo-doctor` security audit is clean

## Doctor Coverage

`scripts/oreo-doctor` audits:

- JSON config validity
- tracked secret-shaped files
- tracked runtime artifacts
- tracked workload source/runtime data
- control API localhost-only config
- dashboard Caddy route not wildcard-bound
- Funnel disabled in policy and observed config
- quick tunnels disabled
- `cloudflare-public` absent from P2 desired/effective access
- sensitive, restricted, and admin workloads not externally exposed
- blocked workloads absent from planned Cloudflare ingress
- effective access reconcile clean

Run text output:

```bash
scripts/oreo-doctor
```

Run machine-readable output:

```bash
scripts/oreo-doctor --json
```

## P2-09 Result

The audit remains non-mutating. It does not start services, enable Funnel,
activate Cloudflare, create DNS, open ports, or write runtime evidence.
