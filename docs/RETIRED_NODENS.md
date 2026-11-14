# Nodens Retirement

`nodens` was retired from Argus on 2026-11-10.

Reason and approval: Superseded by nodens-staging and nodens-production; retired per operator plan.

Argus no longer inventories, routes, classifies, stages, reconciles, or backs
up the workload. It is recorded in `config/argus/retired-workloads.json`, so
the reviewed M1 reconciliation (`scripts/argus-m1-reconcile-retired-workloads`) removes its private state.

Teardown of the server runtime (timer first, then units, sockets, volumes,
networks, images, state directories and the source checkout) is performed by the operator from the numbered runbook in the
retirement pull request. Record the verified backup location and date here
before merging:

- Backup: taken 2026-11-14 on oreochiserver, before any teardown step, at
  `/var/backups/argus-retired/nodens/` (root 0700). It holds `source.tgz` (the
  `/home/oreo/nodens` checkout) and one archive per rootful volume
  (`nodens-live_postgres-data`, `nodens-live_caddy-data`, `nodens-live_caddy-config`),
  taken from each volume's mountpoint while its container had been stopped for
  three months. `checksums.sha256` passed `sha256sum -c` and every archive lists.
- Off-host copy: the directory was encrypted to the snapshot age recipients and
  copied to the operator Mac (`~/Archives/argus-retired/20261114-nodens-retired.tar.age`,
  sha256 `d4b6fcda92d710754760022e63a6217c0519f4585df54ffcda40928197519ed3`). It
  was decrypted there with the operator key and `checksums.sha256` passed.
- Teardown: runbook steps 0-17 ran on 2026-11-14. Kept on the server:
  `/var/lib/argus/migration-cutovers/nodens` (cutover evidence, not yet summarised),
  `/var/backups/argus-m5-workload-staging/nodens` (not yet copied off-host) and the
  pre-change firewall policy, `argus-personal-sandbox.nft.pre`, inside the backup
  directory.

Historical M0-M5 documents and Git commits retain their original references
for audit history; they are not active runtime controls and must not be used to
recreate the workload.
