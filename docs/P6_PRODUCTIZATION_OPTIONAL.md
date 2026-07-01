# P6 Productization Optional

P6 makes Oreo Cloud easier to reuse without turning it into a hosted product.
The phase is optional and remains private-first.

## Goals

- Keep reusable templates complete and validated.
- Document how to start another private checkout safely.
- Add a local validator for template hygiene.
- Keep productization separate from server activation.

## Non-Goals

- No public service exposure.
- No Cloudflare tunnel activation.
- No DNS automation.
- No Tailscale Funnel.
- No packaging secrets, runtime files, backups, or workload source.
- No one-command production installer.

## Deliverables

- `templates/README.md`
- `scripts/oreo-template-check`
- `docs/P6_TEMPLATE_ONBOARDING.md`
- P6 smoke coverage for template validation

## Acceptance

- Template files required for a private starter checkout exist.
- JSON template examples parse.
- Template files do not contain obvious secret markers.
- `scripts/oreo-template-check --json` passes.
- `scripts/smoke-test --offline` passes locally.
