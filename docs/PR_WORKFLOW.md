# P0 PR Workflow

Every Oreo Cloud P0 plan, phase, and task lands through a pull request.

## Branches

- Keep `main` as the reviewed source of truth.
- Create one branch per P0 task or tightly coupled phase.
- Use branch names like `p0/01-discovery`, `p0/02-base-layout`, or `p0/07-dashboard-generator`.
- Do not commit phase work directly to `main`.

## Argus integration line

- `argus` is the protected integration branch for Argus M0 through M4.
- Create each Argus milestone branch from `argus` and target its PR back to
  `argus`; never merge partial Argus milestones into `main`.
- Tag each accepted checkpoint `argus-m<N>-complete` after its PR merges.
- Sync `main` into `argus` only through a reviewed sync PR.
- After M4, promote the complete integration line through one reviewed
  `argus` → `main` merge PR that preserves checkpoint history.

## Issues

- Track P0 work in the `P0` milestone.
- Each PR should close exactly one task issue when practical.
- If a PR must cover more than one issue, explain why in the PR body.
- If a task must run on `oreochiserver`, do not substitute Mac discovery or local laptop state.

## Commits

- Keep commits bisectable and phase-scoped.
- Use the commit message from `docs/CODEX_TASKS.md` when a task specifies one.
- Do not commit secrets, `.env` files, runtime data, workload source, backups, or token material.
- Do not squash unrelated phases together.

## Required PR Checks

Every PR body must state:

- linked P0 issue
- phase or task number
- whether the work was run on `oreochiserver`
- commands used for verification
- safety confirmation that no public exposure was enabled
- secrets confirmation that no sensitive material was printed or committed

For server-required tasks, verification must come from `oreochiserver` unless the PR is only changing documentation or templates.

## Safety Gates

P0 PRs must not:

- enable Tailscale Funnel
- start or enable Cloudflare tunnels
- create DNS records
- open router ports
- expose the dashboard, control API, Docker socket, PostgreSQL, or workload internals publicly
- restart services unless the task explicitly allows it and the PR documents the command

Cloudflare work in P0 is plan-only. Caddy changes must be backed up and validated before reload.

## Merge Rule

Merge only after:

1. the PR template is complete
2. JSON validates where JSON changed
3. scripts run without printing secrets
4. server-required evidence is attached for server tasks
5. the diff matches the task scope

If a task cannot be verified safely, leave the PR open and document the blocker.
