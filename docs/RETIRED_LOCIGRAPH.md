# LociGraph Retirement

LociGraph was permanently retired from Argus before the retained-workload
cutover. The active personal-sandbox runtime, legacy Compose project, Tailscale
Serve route, source checkout, credentials, named volumes, staging artifacts,
database dumps, and cutover backups were destroyed on `oreochiserver`.

Argus no longer inventories, routes, classifies, stages, reconciles, or backs
up the workload. Its private M1 entity and compatibility-projection rows are
removed by the reviewed retired-workload reconciliation. Historical M0–M5
documents and Git commits retain their original references for audit history;
they are not active runtime controls.
