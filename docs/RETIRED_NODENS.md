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

- Backup: TODO before merge.

Historical M0-M5 documents and Git commits retain their original references
for audit history; they are not active runtime controls and must not be used to
recreate the workload.
