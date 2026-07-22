# Argus P6 Closeout

P6 status: complete. Server closeout verified on `oreochiserver`.

## Scope

P6 is optional productization. It makes templates safer to reuse without
turning Argus into a hosted product or one-command installer.

Completed locally:

- added `templates/README.md`
- added `scripts/argus-template-check`
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
scripts/argus-template-check --json
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
cd /srv/argus
git checkout main
git pull --ff-only
scripts/argus-template-check --json
scripts/smoke-test
git status --short
```

P6 is complete only after server smoke passes with `0 failure(s), 0 warning(s)`
and the P6 tag is pushed from `main`.

## Server Verification (complete)

Run on `oreochiserver` at commit `5efb620` on `main`:

```text
scripts/argus-template-check --json
ok=True failures=0

scripts/smoke-test
Smoke summary: 0 failure(s), 0 warning(s)

git status --short
(clean)
```

`p6-complete` was force-moved from the earlier PR #107 commit (which
predated this verification) to `5efb620`.
