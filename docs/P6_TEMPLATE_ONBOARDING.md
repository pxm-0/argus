# P6 Template Onboarding

Use this flow when adapting Oreo Cloud templates for another private server.
This is a planning and bootstrap guide, not an installer.

## 1. Create A Private Checkout

```bash
mkdir -p /srv/oreo-cloud
cd /srv/oreo-cloud
git init
```

Copy selected files from `templates/` into the new checkout and replace
placeholders before committing.

## 2. Start With Discovery

Run read-only discovery first. Do not move workloads, restart services, expose
routes, or print env files.

```bash
templates/scripts/discovery.sh.example
```

## 3. Fill Registries

Populate config files from the examples:

```text
config/workloads.json
config/privacy.json
config/access.json
config/policy.json
config/routes.json
config/exposure.json
config/monitoring.json
```

Validate each file:

```bash
for f in config/*.json; do python3 -m json.tool "$f" >/dev/null; done
```

## 4. Keep Runtime Out Of Git

Do not commit:

- `.env` files
- tokens
- Cloudflare credentials
- runtime logs
- metrics history
- backup artifacts
- workload source
- workload runtime data

## 5. Activate Manually

Install systemd units and Caddy routes only after reviewing generated files on
the server. Back up config files and validate Caddy before reload.

## 6. Validate Templates

From this repo:

```bash
scripts/oreo-template-check
```
