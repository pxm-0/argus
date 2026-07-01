# Oreo Cloud P4 Closeout

P4 status: complete when this closeout PR is merged and `p4-complete` is tagged
on `main`.

Verified locally before closeout PR: 2026-07-01T12:45Z.

## Completed Scope

| Phase | Result |
| --- | --- |
| P4-00 baseline | PR #94 records the P4 baseline from `oreochiserver` and verifies `p3-complete`. |
| P4-01 workload risk matrix | PR #96 documents remaining workload risk and selects `review-ui` only as a gated candidate. |
| P4-02 backup strategy | PR #98 adds plan-only manifests and keeps backup/restore execution disabled for stateful workloads. |
| P4-03 migration or deferral | PR #100 explicitly defers `review-ui` migration for P4 and marks its manifest migration status `skipped`. |
| P4-04 restore drills | PR #102 documents a fresh non-destructive `hello-nginx` restore drill and future stateful restore requirements. |
| P4-05 internal routing | PR #104 documents internal routing state without adding routes or exposure. |
| P4-06 smoke and closeout | This PR adds P4 smoke invariants and this closeout record. |

## P4 Outcome

P4 intentionally prioritizes readiness over migration:

- no new workload was migrated because `review-ui` did not clear provenance,
  bind-mount, env-key, and backup gates
- plan-only manifests now exist for `review-ui`, `dozzle`, `uptime-kuma`,
  `hastur`, and `intake-os`
- backup execution remains disabled for newly documented stateful, sensitive,
  restricted, and admin workloads
- `hello-nginx` remains the only backup-enabled workload and passed a fresh
  non-destructive restore drill
- no internal routing changes were applied
- no public admin surface was created

## Workload State

| Workload | Privacy | P4 Migration | Backup Allowed | Restore Allowed | Effective Access | P4 Result |
| --- | --- | --- | --- | --- | --- | --- |
| `hello-nginx` | unclassified | migrated before P4 | true | false | local | Restore drill reference. |
| `review-ui` | internal | skipped | false | false | local | Deferred until provenance/state gates clear. |
| `dozzle` | restricted | skipped | false | false | local | Docker socket admin tool; do not expose. |
| `uptime-kuma` | restricted | planned | false | false | local | Stateful monitoring; backup strategy only. |
| `hastur` | sensitive | planned | false | false | local | Sensitive SSH/auth/data; defer. |
| `intake-os` | sensitive | planned | false | false | local | Sensitive company/database workload; defer. |

## Safety State

- Tailscale Funnel remains disabled.
- `cloudflared` remains inactive.
- Cloudflare activation remains deferred.
- Dashboard remains bound to the Tailscale IP.
- Control API remains localhost-only.
- Sensitive/restricted/admin workloads are not exposed through Oreo Cloud
  routes.
- No source, env, runtime data, backups, or secrets were committed.

Known legacy exposure risks carried forward:

- `hastur` still has wildcard host bind on `:4173`
- `uptime-kuma` still has wildcard host bind on `:54321`
- host Caddy still has a default `:80` site

These are documented P4 risks, not new P4 changes.

## Smoke And Doctor Expansion

P4 adds smoke checks for:

- required P4 evidence docs
- backup and restore execution remaining disabled for newly documented
  stateful/admin workloads
- `review-ui` migration being explicitly deferred for P4

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
scripts/oreo-doctor --json
ok=True failures=0 checks=22
```

```text
scripts/smoke-test --offline
PASS P4 evidence docs exist
PASS P4 stateful backup execution remains disabled
PASS P4 review-ui migration explicitly deferred

Smoke summary: 0 failure(s), 7 warning(s)
```

The offline smoke warnings are expected on the Mac because live server checks
for backup artifacts, operator links, API bind, Funnel, `cloudflared`, health,
and Caddy are skipped or unavailable locally.

## Final Server Closeout

After this PR merges, run on `oreochiserver`:

```bash
cd /srv/oreo-cloud
git checkout main
git pull --ff-only
scripts/validate-manifests
scripts/oreo-doctor --json
scripts/smoke-test
git status --short
git tag -a p4-complete -m "Oreo Cloud P4 complete"
git push origin p4-complete
```

P4 is complete only after final server smoke passes with `0 failure(s), 0
warning(s)` on `main` and the `p4-complete` tag is pushed.

## P5 Recommendations

- Add scheduled smoke tests and alerting.
- Add backup retention policy and pruning.
- Add richer restore runbooks for stateful workloads before enabling backups.
- Build a safer policy editor and dashboard UX for access/backup state.
- Revisit legacy wildcard binds as explicit remediation work.
