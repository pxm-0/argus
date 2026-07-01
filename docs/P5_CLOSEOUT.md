# Oreo Cloud P5 Closeout

P5 status: local implementation complete; server closeout remains required
before tagging from `main`.

## Scope

P5 turns the P4 safety baseline into repeatable operational maturity without
changing exposure posture.

Completed locally:

- added scheduled smoke runner: `scripts/oreo-smoke-scheduled`
- added scheduled smoke systemd units and templates
- added backup retention preview/apply command: `scripts/oreo-backup-prune`
- added stateful restore gate runbook
- added P5 smoke invariants

## Safety State

- No Tailscale Funnel was enabled.
- No Cloudflare tunnel was started.
- No DNS records were created.
- No router ports were opened.
- No PostgreSQL, Docker socket, dashboard, control API, or admin workload was
  exposed publicly.
- Backup execution remains disabled for P4 stateful, sensitive, restricted,
  and admin workloads.

## Local Verification

```text
scripts/oreo-backup-prune --json
ok=True totalPrunable=0 confirmationPhrase="prune oreo backups"
```

```text
scripts/oreo-backup-prune --apply --json
exit=2 reason="confirmation required"
```

```text
scripts/oreo-smoke-scheduled --offline
ok=True failures=0 warnings=7
```

```text
scripts/smoke-test --offline
PASS P5 maturity assets exist
PASS backup prune previews by default
PASS backup retention policy recognized

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
scripts/validate-manifests
scripts/oreo-doctor --json
scripts/smoke-test
scripts/oreo-backup-prune --json
scripts/oreo-smoke-scheduled
git status --short
```

P5 is complete only after server smoke passes with `0 failure(s), 0 warning(s)`
and the P5 tag is pushed from `main`.
