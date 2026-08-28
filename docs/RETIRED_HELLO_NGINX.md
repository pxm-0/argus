# Hello Nginx Retirement

Hello Nginx was permanently retired from Argus on 2026-08-28 at the
operator's direction. At retirement there was no running source or target
service, no live Tailscale route, and no public exposure.

Argus no longer inventories, routes, classifies, materializes, stages,
reconciles, backs up, or operates the workload. The stopped legacy container,
generated source, compatibility link, target Compose metadata, and
workload-specific migration and backup artifacts are removed from the
production host as part of the retirement deployment. Its private M1 entity
and compatibility-projection rows are removed by the reviewed retired-workload
reconciliation. No named volumes were attached to the stopped container.

The former P1--P4 documents and Git history remain historical evidence; they
are not active runtime controls and must not be used to recreate the workload.
