# Stateful Restore Gates

Before enabling backup or restore execution for a stateful workload, complete
these gates in a PR and record server evidence.

## Required Gates

- Classify every source path, bind mount, named volume, database, and generated
  artifact.
- Document explicit backup inclusions and exclusions.
- Document secret-handling boundaries without printing secret values.
- Define quiesce or hot-backup safety requirements.
- Define restore target paths that cannot overwrite live state by default.
- Run an isolated restore drill.
- Verify checksums.
- Verify health against the isolated restore target.
- Record rollback steps.
- Keep `restoreAllowed=false` until the restore drill evidence is reviewed.

## Workload Notes

`uptime-kuma`:

- Treat monitor URLs, notification targets, tokens, and operational history as
  restricted.
- Restore into an isolated test volume before enabling restore.

`intake-os`:

- Require PostgreSQL dump and restore commands before backup execution.
- Do not expose PostgreSQL.
- Keep env and database credentials excluded from logs and tracked files.

`hastur`:

- Keep SSH keys and auth state excluded unless separately approved.
- Restore into isolated paths only.

`review-ui`:

- Classify `/data/runs` and `/data/review_ui_jobs` before backup execution.
- Confirm source/build provenance before migration or restore automation.

`dozzle`:

- No backup execution is needed for Docker socket admin state.
- Never expose publicly or through Cloudflare.
