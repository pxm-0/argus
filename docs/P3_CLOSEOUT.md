# Argus P3 Closeout

P3 status: complete when this closeout PR is merged and `p3-complete` is tagged
on `main`.

Verified locally before closeout PR: 2026-06-30T22:17Z.

## Completed Scope

| Phase | Result |
| --- | --- |
| P3-00 baseline | PR #78 records the P3 baseline from `oreochiserver` and verifies `p2-complete`. |
| P3-01 restore drill | PR #80 documents a non-destructive `hello-nginx` restore drill from the latest approved backup artifact. |
| P3-02 tailnet routing | PR #82 documents that dashboard routing remains Tailscale-bound and the control API remains localhost-only. |
| P3-03 Cloudflare prerequisites | PR #84 records missing real Cloudflare prerequisites and defers activation. |
| P3-04 activation or deferral | PR #86 documents safe activation deferral for `hello-nginx`. |
| P3-05 rollback proof | PR #88 documents rollback preview and clean effective access reconciliation. |
| P3-06 next workload discovery | PR #90 documents read-only discovery for remaining workloads without migration. |
| P3-07 smoke and closeout | This PR adds P3 smoke/doctor checks and this closeout record. |

## P3 Outcome

- `hello-nginx` restore confidence is documented.
- The dashboard remains private on the tailnet route.
- The control API remains localhost-only.
- Cloudflare protected activation remains deferred because the real hostname,
  named tunnel, credentials, DNS route, and Access policy evidence are missing.
- `hello-nginx` effective access remains `local`.
- Blocked, sensitive, restricted, and admin workloads remain local and are not
  exposed through Cloudflare.
- Rollback preview works even though no activation occurred.
- Next-workload discovery recommends `review-ui` as the least-bad future
  candidate only after more provenance and bind-mount review.

## Workloads

| Workload | Migration | Privacy | Desired Access | Effective Access | P3 Result |
| --- | --- | --- | --- | --- | --- |
| `hello-nginx` | migrated | unclassified | cloudflare-protected | local | Restore drilled; Cloudflare activation deferred. |
| `review-ui` | needs-discovery | internal | tailnet | local | Discovery-only; no migration in P3. |
| `dozzle` | needs-discovery | restricted | local | local | Deferred; Docker socket admin tool. |
| `uptime-kuma` | planned | restricted | tailnet | local | Deferred; stateful monitoring workload. |
| `hastur` | planned | sensitive | tailnet | local | Deferred; SSH/auth/data bind mounts. |
| `intake-os` | planned | sensitive | tailnet | local | Deferred; company/sensitive stateful workload. |

## Cloudflare

- Provider enabled: false
- Provider provisioned: false
- Named tunnels allowed: false
- Quick tunnels allowed: false
- Planned hostname: `hello-nginx.argus.invalid`
- Access/Auth evidence: absent, so activation is deferred
- DNS route: absent
- `cloudflared`: inactive
- Public unauthenticated route: none

P3 did not start `cloudflared`, create DNS records, commit credentials, open
router ports, enable Funnel, or promote any workload to Cloudflare effective
access.

## Smoke And Doctor Expansion

P3 adds smoke checks for:

- required P3 evidence docs
- restore drill evidence
- Cloudflare activation deferral state
- Cloudflare deferral evidence

P3 adds doctor coverage for:

- Cloudflare protected effective access requiring runtime Access/Auth evidence
  when a workload is ever promoted to `cloudflare-protected`

## Local Verification

```text
scripts/validate-manifests
PASS hello-nginx manifest valid
```

```text
scripts/argus-doctor --json
ok=True failures=0 checks=22
```

```text
scripts/smoke-test --offline
PASS P3 evidence docs exist
PASS P3 restore drill evidence recorded
PASS P3 Cloudflare activation remains deferred
PASS P3 deferral evidence recorded

Smoke summary: 0 failure(s), 7 warning(s)
```

The offline smoke warnings are expected on the Mac because live server checks
for backup artifacts, operator links, API bind, Funnel, `cloudflared`, health,
and Caddy are skipped or unavailable locally.

## Final Server Closeout

After this PR merges, run on `oreochiserver`:

```bash
cd /srv/argus
git checkout main
git pull --ff-only
scripts/install-operator-links --check
scripts/validate-manifests
scripts/argus-doctor --json
scripts/smoke-test
git status --short
git tag -a p3-complete -m "Argus P3 complete"
git push origin p3-complete
```

P3 is complete only after final server smoke passes with `0 failure(s), 0
warning(s)` on `main` and the `p3-complete` tag is pushed.

## P4 Recommendations

- Treat `review-ui` as the first future candidate only after source/build
  provenance, bind-mount ownership, backup needs, and env handling are clear.
- Keep `dozzle`, `uptime-kuma`, `hastur`, and `intake-os` out of external
  exposure by default.
- Do not activate Cloudflare until a real hostname, named tunnel credentials,
  DNS route, and Cloudflare Access policy evidence exist.
- Keep using restore drills before migration or access promotion.
