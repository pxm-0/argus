# P4 review-ui Migration Deferral

P4-03 evaluated `review-ui` as the only plausible next low-risk migration
candidate. Migration is explicitly deferred for P4 because the safety gates from
P4-01 and P4-02 are not yet satisfied.

- Verified on: 2026-07-01T12:41Z
- Server: `oreochiserver`
- Server branch during review: `main`
- Server commit: `049009b`
- P4 issue: `#99`
- Decision: `defer`

## Candidate State

Runtime:

```text
container: review-ui
image: dupe-engine-worker:v0.10.9
status: running
runtime: docker
compose path: none observed
```

Health:

```text
status=200 url=http://127.0.0.1:8765
```

Network:

```text
127.0.0.1:8765 -> 8765/tcp
```

Bind mounts:

```text
/data/review_ui_jobs -> /data/review_ui_jobs rw
/data/runs -> /data/runs rw
```

Tracked source/runtime check:

```text
git ls-files 'workloads/review-ui/*'
```

No tracked source, env, runtime data, or backup artifacts were present before
this PR. P4-02 adds only a plan-only manifest.

## Deferral Reasons

Migration is deferred because:

- no source/build provenance is documented for `dupe-engine-worker:v0.10.9`
- no Compose or reproducible runtime definition is available in the Argus
  repo
- `/data/runs` ownership and backup requirements are not classified
- `/data/review_ui_jobs` ownership and backup requirements are not classified
- sensitive-looking env key name `GPG_KEY` needs origin/handling review without
  recording its value
- backup execution is intentionally disabled until the state model is known

## Manifest Update

`workloads/review-ui/manifest.json` now marks P4 migration as skipped:

```json
{
  "migration": {
    "status": "skipped"
  },
  "backup": {
    "backupAllowed": false,
    "restoreAllowed": false
  }
}
```

This is a P4 decision, not a permanent rejection. A future phase can reopen
`review-ui` once the missing provenance and state questions are answered.

## Rollback

No migration was applied, so rollback is:

```text
Keep the existing review-ui container and local bind mounts unchanged.
```

No files were copied, no symlink was created, no container was restarted, no
route was changed, and no access state was promoted.

## Server Verification

Server Git status after read-only review:

```text
## main...origin/main
```

Server smoke after read-only review:

```text
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

## Result

P4-03 acceptance is satisfied:

- migration is explicitly deferred
- manifest is updated
- health passes
- source/env/runtime data is not tracked
- smoke passes
