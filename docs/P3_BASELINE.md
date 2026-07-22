# Argus P3 Baseline

P3 baseline recorded from `oreochiserver` before P3 implementation work.

- Verified on: 2026-06-30T22:00Z
- Server path: `/srv/argus`
- Branch: `main`
- Commit: `c2d3018`
- Required prior tag: `p2-complete`
- P3 issue: `#77`
- Roadmap source: `docs/roadmap/docs/roadmap/P3_PROTECTED_EXTERNAL_ACCESS.md`

## Baseline Result

P3 can begin.

The live server is on `main`, the `p2-complete` tag exists, operator links are
installed, manifests validate, doctor passes, smoke passes, and no Funnel or
Cloudflare tunnel is active.

## Verification Commands

```bash
cd /srv/argus
git checkout main
git pull --ff-only
git status --short --branch
git rev-parse --short HEAD
git tag --list "p2-complete"
scripts/install-operator-links --check
scripts/validate-manifests
scripts/argus-doctor --json
systemctl is-active argus-control-api.service
systemctl is-active argus-metrics.timer
systemctl is-active caddy
systemctl is-active cloudflared
tailscale funnel status
scripts/smoke-test
git status --short --branch
```

## Server State

```text
## main...origin/main
c2d3018
p2-complete
```

Services:

```text
argus-control-api.service active
argus-metrics.timer active
caddy active
cloudflared inactive
```

Tailscale Funnel:

```text
No serve config
```

## Operator Links

`scripts/install-operator-links --check` passed for all approved operator
links:

```text
PASS /usr/local/bin/argus-logs -> /srv/argus/scripts/argus-logs
PASS /usr/local/bin/argus-backup-plan -> /srv/argus/scripts/argus-backup-plan
PASS /usr/local/bin/argus-backup-run -> /srv/argus/scripts/argus-backup-run
PASS /usr/local/bin/argus-restore-plan -> /srv/argus/scripts/argus-restore-plan
PASS /usr/local/bin/argus-events -> /srv/argus/scripts/argus-events
PASS /usr/local/bin/argus-smoke-test -> /srv/argus/scripts/smoke-test
PASS /usr/local/bin/argus-access-preview -> /srv/argus/scripts/argus-access-preview
PASS /usr/local/bin/argus-access-apply -> /srv/argus/scripts/argus-access-apply
PASS /usr/local/bin/argus-access-reconcile -> /srv/argus/scripts/argus-access-reconcile
PASS /usr/local/bin/argus-cloudflare-plan -> /srv/argus/scripts/argus-cloudflare-plan
PASS /usr/local/bin/argus-cloudflare-activate-preview -> /srv/argus/scripts/argus-cloudflare-activate-preview
PASS /usr/local/bin/argus-cloudflare-activate -> /srv/argus/scripts/argus-cloudflare-activate
PASS /usr/local/bin/argus-cloudflare-rollback -> /srv/argus/scripts/argus-cloudflare-rollback
```

## Manifest And Doctor

Manifest validation:

```text
PASS hello-nginx manifest valid
```

Doctor summary:

```text
ok= True failures= 0 checks= 21
```

## Smoke Summary

Final smoke tail:

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

## Access And Exposure Baseline

- Dashboard route remains private.
- Control API remains local-only.
- `cloudflared` is inactive.
- No Tailscale Funnel/Serve config is present.
- `hello-nginx` desired access remains `cloudflare-protected`.
- `hello-nginx` effective access remains `local`.
- Cloudflare activation remains deferred until external prerequisites exist.

## Workload Baseline

| Workload | Migration | Privacy | Desired Access | Effective Access | P3 Note |
| --- | --- | --- | --- | --- | --- |
| `hello-nginx` | migrated | unclassified | cloudflare-protected | local | Approved P3 restore drill and possible protected activation candidate. |
| `intake-os` | planned | sensitive | tailnet | local | Do not migrate or expose in P3. |
| `hastur` | planned | sensitive | tailnet | local | Do not migrate or expose in P3. |
| `uptime-kuma` | planned | restricted | tailnet | local | Do not migrate or expose in P3. |
| `review-ui` | needs-discovery | internal | tailnet | local | Discovery-only candidate. |
| `dozzle` | needs-discovery | restricted | local | local | Admin tool with Docker socket; do not expose. |

## P3 Starting Order

Per the roadmap, P3 should proceed in this order:

```text
P3-00 baseline and p2 tag verification
P3-01 hello-nginx restore drill
P3-02 tailnet-only routing review
P3-03 real Cloudflare protected activation prerequisites
P3-04 real Cloudflare protected activation for hello-nginx or deferral
P3-05 access reconciliation and rollback proof
P3-06 next workload discovery only
P3-07 P3 smoke and closeout
```

Restore confidence comes before external access.
