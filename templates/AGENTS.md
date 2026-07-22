# Codex Instructions for Argus

This project manages private self-hosted infrastructure.

## Hard Rules

- Land every P0 plan, phase, and task through a pull request.
- Do not commit phase work directly to `main`.
- Do not expose services publicly by default.
- Do not enable Tailscale Funnel.
- Do not start Cloudflare tunnels in P0.
- Do not create DNS records in P0.
- Do not open router ports.
- Do not expose PostgreSQL.
- Do not expose Docker socket.
- Do not expose the control API publicly.
- Do not commit secrets, tokens, `.env`, runtime files, workload source, or backups.
- Prefer read-only discovery before changes.
- Back up config files before editing.
- Validate Caddy before reload.
- Keep scripts idempotent.
- Preserve Docker Compose project names during migration.

## PR Workflow

- Follow `docs/PR_WORKFLOW.md`.
- Link each PR to the matching P0 issue.
- Keep server-required work on `oreochiserver`; do not use Mac discovery as server evidence.
- Complete the PR template safety checklist before merge.

## Project Model

Workloads are agnostic by default.

- `workloads.json` describes app/runtime identity.
- `privacy.json` stores classification.
- `access.json` stores desired/effective access.
- `policy.json` stores guardrails.
- `exposure.json` stores provider capability/planning.

## Coding Style

- Use Python standard library where practical.
- Do not require `jq`.
- Do not print secrets.
- Shell scripts should use safe defaults.
- JSON files must validate with `python3 -m json.tool`.
