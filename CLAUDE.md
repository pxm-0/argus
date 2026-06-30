# Oreo Cloud Agent Notes

This repository is the P0 handoff and source of truth for Oreo Cloud work.

## Hard Rules

- Land every P0 plan, phase, and task through a pull request.
- Do not commit phase work directly to `main`.
- Do not expose services publicly by default.
- Do not enable Tailscale Funnel.
- Do not start Cloudflare tunnels in P0.
- Do not create DNS records in P0.
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
- Keep Cloudflare work plan-only during P0.
- Treat the PR template as a required safety gate, not a formality.
