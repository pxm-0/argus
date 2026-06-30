# P2 Workload Migration Evaluation

P2-06 evaluated whether Oreo Cloud should migrate one additional low-risk
workload after `hello-nginx`.

- GitHub issue: `#66`
- Verified on: `oreochiserver`
- Result: safely deferred

## Decision

No additional workload is suitable for P2 migration.

P2 should not force a migration when the remaining candidates are sensitive,
restricted, admin-facing, database-backed, or still require deeper discovery.
This preserves the P2 safety model and avoids moving company, admin, or
stateful workloads under deadline pressure.

## Candidate Evidence

| Workload | Privacy | Runtime | Migration State | Decision | Reason |
| --- | --- | --- | --- | --- | --- |
| `intake-os` | sensitive | docker-compose | planned | defer | Disallowed by P2 as company/sensitive work. It also has PostgreSQL/Caddy named volumes and a Caddy bind-mount risk. |
| `hastur` | sensitive | docker-compose | planned | defer | Sensitive workload with SSH/auth/data bind mounts. P2 disallows sensitive workload migration. |
| `uptime-kuma` | restricted | docker-compose | planned | defer | Explicitly disallowed by P2. It has monitoring state in a named volume. |
| `review-ui` | internal | docker | needs-discovery | defer | Not a Docker Compose migration candidate yet. It has runtime/job bind mounts and requires more discovery. |
| `dozzle` | restricted | docker | needs-discovery | defer | Admin tool with Docker socket access. P2 forbids exposing or casually migrating Docker socket surfaces. |
| `hello-nginx` | unclassified | docker-compose | migrated | already done | Low-risk migration was completed during P1 and is the approved P2 backup/Cloudflare demo workload. |

## Server Evidence Command

```bash
cd /srv/oreo-cloud
python3 - <<'PY'
import json
from pathlib import Path

root = Path("/srv/oreo-cloud")
workloads = json.loads((root / "config/workloads.json").read_text())["workloads"]
privacy = json.loads((root / "config/privacy.json").read_text())["workloads"]

for workload in workloads:
    wid = workload["id"]
    migration = workload.get("migration", {})
    print(
        wid,
        "kind=" + str(workload.get("kind")),
        "migration=" + str(migration.get("status")),
        "privacy=" + str(privacy.get(wid, {}).get("privacy")),
        "runtime=" + str(workload.get("runtime", {}).get("type")),
        "legacy=" + str(workload.get("paths", {}).get("legacy")),
        "risks=" + str(migration.get("bindMountRisks") or migration.get("risks") or []),
        "volumes=" + str(migration.get("namedVolumeRisks") or []),
    )
PY
```

## Deferral Criteria

The following P2 rules caused the deferral:

- Do not migrate Intake OS or company work.
- Do not migrate Uptime Kuma.
- Do not migrate dashboards/admin panels.
- Do not migrate sensitive or restricted workloads.
- Do not migrate workloads with unclear volumes, database state, Docker socket
  access, SSH mounts, or auth/data bind mounts.
- Preserve Docker Compose project names during migration; non-Compose Docker
  workloads need more discovery before they can meet that bar.

## Follow-Up

Move the remaining candidates to P3 discovery/migration planning. A future phase
should first classify data/state, document rollback, and design workload-specific
backup/restore coverage before any cutover.
