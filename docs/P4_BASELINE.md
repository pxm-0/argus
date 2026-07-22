# P4 Baseline

P4 starts from the completed P3 state and focuses on stateful workload
readiness, backup/restore confidence, internal routing, and safe deferral where
needed. P4 is not an exposure phase.

- Verified on: 2026-07-01T12:34Z
- Server: `oreochiserver`
- Server branch: `main`
- Server commit: `049009b`
- P4 issue: `#93`

## Release Baseline

`p3-complete` exists and peels to the current P3 closeout commit:

```text
a8623bf46b53b8f738da410e9276421c0a9b72cd refs/tags/p3-complete
049009beb10dfe934ae4d1ef901cfa4a807c4644
```

Server Git status:

```text
## main...origin/main
```

## Server Checks

Operator links:

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

Manifest validation:

```text
PASS hello-nginx manifest valid
```

Doctor:

```text
ok=True failures=0 checks=22
```

Smoke:

```text
Smoke summary: 0 failure(s), 0 warning(s)
```

## Service State

```text
argus-control-api.service active
caddy active
cloudflared inactive
```

Tailscale Funnel:

```text
No serve config
```

## Exposure Baseline

Relevant listeners at P4 start:

```text
100.75.210.83:8088  Argus dashboard, Tailscale-bound Caddy route
127.0.0.1:8099      Argus control API
127.0.0.1:8765      review-ui
127.0.0.1:8080      intake-os local proxy
127.0.0.1:8081      dozzle
127.0.0.1:18080     hello-nginx
0.0.0.0:4173        hastur legacy host bind
[::]:4173           hastur legacy host bind
0.0.0.0:54321       uptime-kuma legacy host bind
[::]:54321          uptime-kuma legacy host bind
*:80                existing default Caddy site
```

No unexpected Argus public exposure was found:

- dashboard remains bound to the Tailscale IP on `:8088`
- control API remains bound to `127.0.0.1:8099`
- `cloudflared` is inactive
- no Tailscale Funnel/Serve config is present
- Cloudflare activation remains deferred

The wildcard listeners for `hastur`, `uptime-kuma`, and the default Caddy
`:80` site are known legacy/host-level exposure risks carried into P4. They are
not new P4 changes and should be handled through P4 risk, backup, and internal
routing review rather than accidental exposure expansion.

## Workload Baseline

| Workload | Migration | Privacy | Desired Access | Effective Access | P4 Posture |
| --- | --- | --- | --- | --- | --- |
| `hello-nginx` | migrated | unclassified | cloudflare-protected | local | Regression and restore-drill reference. |
| `review-ui` | needs-discovery | internal | tailnet | local | Possible next candidate after provenance and bind-mount review. |
| `dozzle` | needs-discovery | restricted | local | local | Admin tool; do not expose. |
| `uptime-kuma` | planned | restricted | tailnet | local | Discovery and backup strategy only. |
| `hastur` | planned | sensitive | tailnet | local | Discovery only; SSH/auth/data bind risks. |
| `intake-os` | planned | sensitive | tailnet | local | Discovery only unless explicitly rescoped. |

## P4 Starting Order

Per the roadmap, P4 should proceed in this order:

```text
P4-00 baseline
P4-01 workload risk matrix
P4-02 stateful backup strategy
P4-03 next low-risk migration or safe deferral
P4-04 restore drill extension
P4-05 internal routing review
P4-06 smoke and closeout
```

P4 should prove readiness for realistic stateful workloads before migrating or
exposing anything new.

## Result

P4-00 acceptance is satisfied:

- `p3-complete` tag exists
- smoke passes
- doctor passes
- no unexpected Argus public exposure found
