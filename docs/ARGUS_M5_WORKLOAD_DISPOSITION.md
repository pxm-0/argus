# M5 Workload Disposition

The operator approved the following migration destinations:

| Workload | Planned destination | Admission |
| --- | --- | --- |
| Hastur | `personal-sandbox` | denied pending migration gates |
| Kadath | `personal-sandbox` | denied pending migration gates |
| Nodens | `personal-sandbox` | denied pending migration gates |
| Intake OS | `work-sandbox` | denied pending migration gates |

The destination is recorded in each workload manifest as
`migration.targetTrustDomain`. This is a migration plan, not an admission
grant. `config/argus/workload-classification.json` remains unchanged until the
destination runtime, capacity, backup, isolated restore, source staging,
health, rollback, and exact-revision cutover evidence all pass.

LociGraph was permanently retired before the retained-workload cutover; see
[`RETIRED_LOCIGRAPH.md`](RETIRED_LOCIGRAPH.md). The operator also approved
permanent retirement of Uptime Kuma, Dozzle,
Publication Archive, and Review UI. Their containers, approved source/data
paths, workload-specific volumes, and unreferenced images were removed from
`oreochiserver`. Their active Argus inventory, access, privacy, route, legacy
classification, and manifest records are removed by this change. Historical
documentation remains as immutable evidence of their earlier state.

No Compose project name changes are authorized:

- Hastur: `hastur`
- Kadath: `kadath-live`
- Nodens: `nodens`
- Intake OS: `intake-os`

No migration may add a public route, Tailscale Funnel, Cloudflare tunnel, DNS
record, router port, PostgreSQL host exposure, Docker socket exposure, or
cross-domain credential/data mount.
