# Oreo Cloud P2 Closeout

P2 status: complete when this closeout PR is merged and `p2-complete` is tagged
on `main`.

Verified on `oreochiserver`: 2026-06-30T21:15Z.

## Completed Phases

| Phase | Result |
| --- | --- |
| P2-00 baseline | Merged in PR #55. Recorded P2 baseline from `oreochiserver`. |
| P2-01 operator links | Merged in PR #57. Installed and verified all approved `/usr/local/bin` operator links on `oreochiserver`. |
| P2-02 manifest schema | Merged in replacement PR #75 after original stacked PR #59 closed during base cleanup. Added schema validation and manifest docs. |
| P2-03 dashboard runtime cleanliness | Merged in PR #61. Static dashboard generation no longer embeds runtime state. |
| P2-04 dashboard action layer | Merged in PR #63. Added authenticated, structured preview/apply action APIs. |
| P2-05 backup execution | Merged in PR #65. Enabled source-only backup execution and non-destructive restore-test docs for `hello-nginx`. |
| P2-06 workload migration | Merged in PR #67. Documented safe deferral because no additional low-risk workload was suitable for P2. |
| P2-07 Cloudflare protected activation | Merged in PR #69. Added guarded activation, preview, and rollback commands; real activation remains blocked on external prerequisites. |
| P2-08 access reconcile | Merged in PR #71. Added effective access reconciliation and reconciled stale Funnel observation. |
| P2-09 smoke expansion | Merged in PR #73. Expanded smoke and `oreo-doctor` security audit coverage. |

## Live Server State

- `/srv/oreo-cloud` is on `main` at commit `11e542d`.
- `scripts/install-operator-links --check` passes for all approved operator links.
- `scripts/validate-manifests` passes.
- `scripts/oreo-doctor --json` reports `ok=true`, `failures=0`, `checks=21`.
- `scripts/smoke-test` passes with `0 failure(s), 0 warning(s)`.
- The control API binds only to localhost.
- Caddy planned and live validation pass.
- Tailscale Funnel is not detected.
- `cloudflared` is inactive, as expected for the current guarded/non-activated Cloudflare state.

## Workloads

| Workload | Migration | Privacy | Desired Access | Effective Access | Backup | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `hello-nginx` | migrated | unclassified | cloudflare-protected | local | enabled | Approved demo workload. Cloudflare remains planned until real hostname, Access policy, named tunnel, and credentials exist. |
| `intake-os` | planned | sensitive | tailnet | local | not enabled | Deferred to P3 due sensitive/company data and stateful risks. |
| `hastur` | planned | sensitive | tailnet | local | not enabled | Deferred to P3 due sensitive SSH/auth/data bind mounts. |
| `uptime-kuma` | planned | restricted | tailnet | local | not enabled | Deferred to P3 due restricted monitoring state. |
| `review-ui` | needs-discovery | internal | tailnet | local | not enabled | Stale Funnel observation reconciled to no observed Funnel. |
| `dozzle` | needs-discovery | restricted | local | local | not enabled | Admin tool with Docker socket access; not externally exposed. |

## Cloudflare

- Provider enabled: false
- Named tunnel active: false
- Quick tunnels allowed: false
- Planned hostname: `hello-nginx.oreo-cloud.invalid`
- Access protection verified: false, because no real Cloudflare activation occurred in P2
- Public unauthenticated route: none
- Blocked workloads exposed: none

P2 landed activation guardrails only. It did not start Cloudflare, create DNS,
enable a tunnel, or update effective access to Cloudflare.

## Backup Status

`hello-nginx` backup execution is enabled for source-only backup. Final server
smoke validated the latest approved backup artifact successfully.

## Dashboard And API

- Dashboard runtime state is generated under ignored runtime paths.
- Static dashboard assets remain tracked and clean.
- Action endpoints require authentication.
- Restart and backup previews are non-mutating.
- Action API responses omit raw shell commands.
- Logs preview remains capped and sanitized.

## Final Smoke Test

```text
PASS Cloudflare rollback preview works
PASS effective access reconcile clean
PASS no Funnel detected
PASS no unexpected cloudflared active
PASS no tracked secrets
PASS doctor security audit clean
PASS workload CLI works
PASS health CLI works
PASS Caddy dashboard route generated
PASS Caddy route is private
PASS planned Caddy route validates
PASS live Caddy validates

Smoke summary: 0 failure(s), 0 warning(s)
```

## Known Limitations

- Cloudflare protected access is not activated yet because P2 did not receive a
  real hostname, named tunnel credentials, DNS setup, or Cloudflare Access
  policy evidence.
- Only `hello-nginx` is migrated and backup-enabled.
- Remaining workloads require P3 discovery and workload-specific migration,
  rollback, and backup plans.
- A server-local dirty worktree discovered during closeout was preserved in a
  stash and an ignored runtime backup before final `main` verification.

## P3 Recommendations

- Complete real Cloudflare protected activation for `hello-nginx` after external
  prerequisites exist.
- Plan workload-specific migrations for remaining non-sensitive candidates after
  state, data, and rollback are documented.
- Add richer restore drills for stateful workloads before migration.
- Revisit Tailnet-only private routing for internal services.
- Periodically run `scripts/oreo-doctor` and `scripts/smoke-test` from
  `oreochiserver` as the platform evolves.
