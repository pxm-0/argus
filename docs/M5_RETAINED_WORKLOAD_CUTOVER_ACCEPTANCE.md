# M5 Retained Workload Cutover Acceptance

Issue: #256  
Pull request: #257  
Server: `oreochiserver`  
Accepted: 2026-07-29

## Accepted cutovers

| Workload | Trust domain | Tailnet URL | Final stage | Cutover time |
| --- | --- | --- | --- | --- |
| Nodens | `personal-sandbox` | `https://oreochiserver.tail0a3a58.ts.net:8444/` | `nodens-20260729t124613z-52dbc74d` | `2026-07-29T12:46:43Z` |
| Kadath | `personal-sandbox` | `https://oreochiserver.tail0a3a58.ts.net:8443/` | `kadath-20260729t130609z-4257bb53` | `2026-07-29T13:07:09Z` |
| Hastur | `personal-sandbox` | `https://oreochiserver.tail0a3a58.ts.net:8445/` | `hastur-20260729t132129z-cd6655bd` | `2026-07-29T13:23:54Z` |
| LociGraph | `personal-sandbox` | `https://oreochiserver.tail0a3a58.ts.net/` | `locigraph-20260729t133400z-1c09969b` | `2026-07-29T13:47:44Z` |
| Intake OS | `work-sandbox` | `https://oreochiserver.tail0a3a58.ts.net:8446/` | `intake-os-20260729t134907z-384659df` | `2026-07-29T13:51:08Z` |

## Acceptance invariants

- Each target is healthy and runs in its assigned rootless trust domain.
- Original Docker Compose project names are preserved.
- Target containers publish no host ports.
- Tailnet-only Tailscale Serve routes proxy to root-owned Unix sockets.
- Tailscale Funnel is disabled; no Cloudflare tunnel, DNS record, or router port was added.
- PostgreSQL and workload-internal services remain private.
- Legacy source containers are stopped and restart-fenced for rollback.
- The persistence timer is enabled and a post-cutover reconcile passed for every workload.
- Stateful automatic rollback is intentionally refused after target authority because target-side writes require explicit reconciliation.
- No secrets, runtime workload source, backups, or migration artifacts are committed.

## Recovery and rollback evidence

- Nodens: stateless rollback was rehearsed successfully, then the accepted cutover was reapplied.
- Kadath: a PostgreSQL identity mismatch was caught before acceptance; source authority was restored, identity/authentication checks were added, and the final restore fingerprint matched.
- Hastur: an offline startup dependency was caught before acceptance; source authority was restored, the exact package start command was normalized, and the final cutover passed.
- LociGraph: a PostgreSQL readiness race was caught before target authority; source writers were restored, readiness was tightened to the real server process, and PostgreSQL, Redis, and raw-volume parity passed.
- Intake OS: final staging, restore, health, fencing, and reconcile checks passed without recovery.

After acceptance, a legacy Intake OS cron self-heal attempted to restart the fenced source Compose project. Reconcile detected the source immediately. The source was stopped again, both periodic and `@reboot` entries were backed up under the root-only cutover evidence directory and removed, and the cutover guard was extended to refuse any source-owner crontab that can start the legacy Compose runtime. The new guard then found a dormant Hastur `@reboot` Compose entry; it was separately backed up and removed before reboot could resurrect that source. All five workloads subsequently passed guarded reconcile.

The stopped retained source stacks are rollback assets and are not deletion candidates. The previously retired uptime, Dozzle, publication/archive, and review UI workloads and their source were removed separately at the operator's request.

## UI state

The workload inventory, access plan, route plan, classification registry, privacy record, and canonical manifests record the accepted state. The dashboard exposes direct tailnet open links and disables migration preflight once a workload has status `migrated`. Generic access mutation and Compose-based health refresh remain disabled because the accepted routes and runtimes are root-owned migration assets; their dedicated reconcile path remains authoritative.
