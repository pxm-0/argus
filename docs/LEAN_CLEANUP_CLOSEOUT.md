# Lean Cleanup Closeout

This cleanup removes generated artifacts and duplicate operator surfaces that
had drifted away from the source-of-truth model.

## Completed Locally

- removed tracked generated dashboard assets
- removed tracked generated Caddy and Cloudflare plan outputs
- ignored generated dashboard, Caddy, and Cloudflare output files
- removed the P0 combined mega-doc now covered by split canonical docs
- removed legacy restart CLI wrappers in favor of `oreo-action-preview restart`
  and `oreo-action-apply restart`
- removed the runpy-only smoke wrapper while keeping the operator symlink target
  as `scripts/smoke-test`
- centralized dashboard state, recent audit events, operator command lists, and
  YAML quoting helpers
- updated docs to reflect generated-output source of truth

## Local Verification

```text
scripts/validate-manifests
PASS dozzle manifest valid
PASS hastur manifest valid
PASS hello-nginx manifest valid
PASS intake-os manifest valid
PASS review-ui manifest valid
PASS uptime-kuma manifest valid
```

```text
scripts/smoke-test --offline
PASS dashboard index.html ignored
PASS dashboard style.css ignored
PASS dashboard app.js ignored
PASS dashboard generation clean
PASS runtime dashboard state ignored

Smoke summary: 0 failure(s), 7 warning(s)
```

The warnings are expected on the Mac because live server checks are skipped or
unavailable locally.
