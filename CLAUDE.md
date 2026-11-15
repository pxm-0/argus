# Argus Agent Notes

This repository is the P0 handoff and source of truth for Argus work.

## Hard Rules

- Land every P0 plan, phase, and task through a pull request.
- Do not commit phase work directly to `main`.
- Do not expose services publicly by default. The only exception is the single route authorized by D027 (`nodens-production` at `nodens.dev` and `www.nodens.dev` through a named tunnel; see `docs/NODENS_PUBLIC_ROUTE.md`).
- Do not enable Tailscale Funnel.
- Do not start Cloudflare tunnels or create DNS records, except for the D027 route.
- Never use Cloudflare Quick Tunnels.
- Do not open router ports.
- Do not commit secrets, tokens, `.env`, runtime files, workload source, or backups.
- Use `oreochiserver` evidence for server-required tasks.

## Skill Routing

When the user's request matches an available gstack skill, invoke it.

- Product and scope shaping -> `/office-hours` or `/spec`
- Plan review -> `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, or `/autoplan`
- Implementation debugging -> `/investigate`
- QA and smoke testing -> `/qa` or `/qa-only`
- Code review and diff checks -> `/review`
- PR creation and phase shipping -> `/ship`
- Post-ship docs -> `/document-release`
- Save or restore context -> `/context-save` or `/context-restore`

## P0 Workflow

- Follow `docs/PR_WORKFLOW.md`.
- Work one GitHub issue at a time when possible.
- Keep all other Cloudflare work plan-only; widening D027 needs a new decision, threat model and PR.
- Treat the PR template as a required safety gate, not a formality.

## Identity (learned from session audit)
- GitHub: pushes as **pxm-0** (pinned via ~/.gitconfig — don't switch accounts manually).
