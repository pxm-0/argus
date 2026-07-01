# Oreo Cloud P6 Closeout

P6 status: local implementation complete; server closeout remains required
before tagging from `main`.

## Scope

P6 is optional productization. It makes templates safer to reuse without
turning Oreo Cloud into a hosted product or one-command installer.

Completed locally:

- added `templates/README.md`
- added `scripts/oreo-template-check`
- added `docs/P6_TEMPLATE_ONBOARDING.md`
- added P6 smoke invariants for productization assets and template validation

## Safety State

- No public service exposure was added.
- No Cloudflare tunnel activation was added.
- No DNS automation was added.
- No Tailscale Funnel was added.
- No secrets, runtime files, backups, or workload source were packaged.
- No one-command production installer was added.

## Local Verification

```text
scripts/oreo-template-check --json
ok=True failures=0
```

```text
scripts/smoke-test --offline
PASS P6 productization assets exist
PASS productization templates valid

Smoke summary: 0 failure(s), 7 warning(s)
```

The warnings are expected on the Mac because live server checks are skipped or
unavailable locally.

## Server Closeout Required

On `oreochiserver`, after merge to `main`:

```bash
cd /srv/oreo-cloud
git checkout main
git pull --ff-only
scripts/oreo-template-check --json
scripts/smoke-test
git status --short
```

P6 is complete only after server smoke passes with `0 failure(s), 0 warning(s)`
and the P6 tag is pushed from `main`.
