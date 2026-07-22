# P4 Restore Drills

P4-04 extends the restore drill pattern for backup-enabled workloads. At P4
start, `hello-nginx` is the only workload with backup execution enabled, so the
P4 drill reruns a non-destructive `hello-nginx` restore test and records the
pattern future stateful workloads must satisfy before `restoreAllowed` can be
enabled.

- Verified on: 2026-07-01T12:41Z
- Server: `oreochiserver`
- Server branch during drill: `main`
- Server commit: `049009b`
- P4 issue: `#101`

## Backup-Enabled Workloads

| Workload | Backup Allowed | Restore Allowed | P4 Drill |
| --- | --- | --- | --- |
| `hello-nginx` | true | false | Non-destructive restore drill completed. |
| `review-ui` | false | false | Not eligible; backup strategy is planned only. |
| `dozzle` | false | false | Not eligible; backup disabled. |
| `uptime-kuma` | false | false | Not eligible; stateful backup strategy not tested. |
| `hastur` | false | false | Not eligible; sensitive backup strategy not approved. |
| `intake-os` | false | false | Not eligible; sensitive/database backup strategy not approved. |

## hello-nginx Drill

Latest approved artifact:

```text
runtime/backups/hello-nginx/20260630-202443
```

Restore test directory:

```text
runtime/restore-tests/hello-nginx/p4-20260701-124142
```

Checksum validation:

```text
CHECKSUMS_OK true
```

Restored files:

```text
runtime/restore-tests/hello-nginx/p4-20260701-124142/backup-summary.json
runtime/restore-tests/hello-nginx/p4-20260701-124142/extracted/source/docker-compose.yml
runtime/restore-tests/hello-nginx/p4-20260701-124142/manifest.json
runtime/restore-tests/hello-nginx/p4-20260701-124142/restore-plan.md
```

The restored Compose file matched the live tracked Compose file:

```text
c5bf9d7674fa25a4498b0ea7d9b9ef369009bc351c1f4ca0b4391c1c4553c0e7  workloads/hello-nginx/source/docker-compose.yml
c5bf9d7674fa25a4498b0ea7d9b9ef369009bc351c1f4ca0b4391c1c4553c0e7  runtime/restore-tests/hello-nginx/p4-20260701-124142/extracted/source/docker-compose.yml
```

The restore-test path is ignored:

```text
.gitignore:2:runtime/*  runtime/restore-tests/hello-nginx/p4-20260701-124142
.gitignore:2:runtime/*  runtime/restore-tests/hello-nginx/p4-20260701-124142/extracted/source/docker-compose.yml
```

Live health remained good:

```text
status=200 url=http://127.0.0.1:18080
```

Server Git status remained clean:

```text
## main...origin/main
```

Server smoke after the drill:

```text
PASS P3 Cloudflare activation remains deferred
PASS P3 deferral evidence recorded
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

## Stateful Restore Drill Requirements

Future stateful restore drills must meet this bar before backup execution or
restore execution is enabled:

- restore into `/srv/argus/runtime/restore-tests/<id>/...`
- validate artifact checksums before extraction
- keep restore-test artifacts ignored by Git
- avoid overwriting live bind mounts, volumes, databases, env files, or auth
  paths
- document expected recovered files or volumes
- prove live service health is unaffected
- run server smoke afterward

## Result

P4-04 acceptance is satisfied:

- restore drill is non-destructive
- evidence is documented
- live service is unaffected
- smoke passes
