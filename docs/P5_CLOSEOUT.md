# Argus P5 Closeout

P5 status: complete. Server closeout verified on `oreochiserver`.

## Scope

P5 turns the P4 safety baseline into repeatable operational maturity without
changing exposure posture.

Completed locally:

- added scheduled smoke runner: `scripts/argus-smoke-scheduled`
- added scheduled smoke systemd units and templates
- added backup retention preview/apply command: `scripts/argus-backup-prune`
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
scripts/argus-backup-prune --json
ok=True totalPrunable=0 confirmationPhrase="prune argus backups"
```

```text
scripts/argus-backup-prune --apply --json
exit=2 reason="confirmation required"
```

```text
scripts/argus-smoke-scheduled --offline
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
cd /srv/argus
git checkout main
git pull --ff-only
scripts/validate-manifests
scripts/argus-doctor --json
scripts/smoke-test
scripts/argus-backup-prune --json
scripts/argus-smoke-scheduled
git status --short
```

P5 is complete only after server smoke passes with `0 failure(s), 0 warning(s)`
and the P5 tag is pushed from `main`.

## Server Verification (complete)

Run on `oreochiserver` at commit `5efb620` on `main`:

```text
scripts/validate-manifests
PASS (all 7 workload manifests valid)

scripts/argus-doctor --json
ok=True failures=0

scripts/smoke-test
Smoke summary: 0 failure(s), 0 warning(s)

scripts/argus-backup-prune --json
ok=True totalPrunable=0 confirmationPhrase="prune argus backups"

scripts/argus-smoke-scheduled
ok=True exitCode=0 failures=0 warnings=0

git status --short
(clean)
```

The `smoke-test` run required fixing a false-positive Funnel check first
(see PR #114) — `check_funnel` was flagging the tailnet-only `serve` output
of `tailscale funnel status` as if Funnel were enabled. No Funnel, Cloudflare
tunnel, DNS record, or router port was ever active; this was a check bug,
not an exposure incident.

`p5-complete` was force-moved from the earlier PR #107 commit (which
predated this verification) to `5efb620`.
