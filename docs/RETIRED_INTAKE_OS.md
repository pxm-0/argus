# Intake OS Retirement

Intake OS was permanently retired from Argus on 2026-11-09 with operator
approval. It is a work project and was removed from the personal server
`oreochiserver`.

Before removal, the workload was fully backed up and the backup was verified:

- Server archive: `/var/backups/work-archive-20261109T194424Z` (root-only,
  with `SHA256SUMS`), with an operator-held copy off the server.
- The PostgreSQL dumps were restore-tested; the `intake_os` database restored
  cleanly with all 17 tables.

The retirement removes the work-sandbox runtime, Compose project, Tailscale
Serve route on `8446`, ingress socket, reconcile and nightly database-backup
timers, staging artifacts, workload volumes and images, legacy rootful
containers and volumes, and the legacy source checkout on `oreochiserver`.

Argus no longer inventories, routes, classifies, stages, reconciles, or backs
up the workload. Its private M1 entity and compatibility-projection rows are
removed by the reviewed retired-workload reconciliation.

The `work-sandbox` trust domain stays provisioned but holds no workload. Its
user, firewall, network namespace, domain agent, rootless Docker daemon, and
collectors are unchanged.

Historical M0–M5 documents and Git commits retain their original references
for audit history; they are not active runtime controls and must not be used to
recreate the workload.
