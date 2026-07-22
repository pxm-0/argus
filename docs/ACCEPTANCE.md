# Acceptance Criteria and Smoke Tests

## P0 Definition of Done

```text
[ ] /srv/argus exists
[ ] /srv/argus is a Git repo
[ ] .gitignore blocks secrets/runtime/workload source
[ ] .gitattributes exists
[ ] README.md exists
[ ] AGENTS.md exists
[ ] docs exist
[ ] workloads.json exists and validates
[ ] access.json exists and validates
[ ] privacy.json exists and validates
[ ] policy.json exists and validates
[ ] routes.json exists and validates
[ ] exposure.json exists and validates
[ ] monitoring.json exists and validates
[ ] workloads are neutral by default
[ ] privacy state lives outside workloads.json
[ ] access state lives outside workloads.json
[ ] desired and effective access are separate
[ ] dashboard is generated
[ ] dashboard opens from phone over Tailscale
[ ] dashboard shows workload cards
[ ] dashboard shows privacy controls
[ ] dashboard shows desired/effective access
[ ] unauthenticated dashboard is view-only
[ ] admin mode can update privacy
[ ] admin mode can preview access changes
[ ] admin mode can apply allowed access changes
[ ] monitor toggle exists
[ ] monitor toggle shows btop-style stats
[ ] metrics collector writes valid metrics.json
[ ] control API binds only to 127.0.0.1:8099
[ ] Caddy exposes API only through Tailscale-bound dashboard
[ ] Cloudflare plan exists
[ ] Cloudflare is disabled by default
[ ] no cloudflared tunnel started by P0
[ ] no Tailscale Funnel enabled
[ ] no public router ports required
[ ] no PostgreSQL exposure
[ ] no Docker socket exposure
[ ] no control token tracked by Git
[ ] no .env files tracked by Git
[ ] no workload source tracked by Argus Git
[ ] argus-workloads works
[ ] argus-health works
[ ] argus-open works
[ ] argus-monitor works
[ ] argus-cloudflare-plan works
[ ] argus-doctor works
[ ] argus-smoke-test works
```

## Manual Smoke Tests

### JSON Validation

```bash
for f in /srv/argus/config/*.json; do
  python3 -m json.tool "$f" >/dev/null || exit 1
done
```

### Git Secret Check

```bash
cd /srv/argus
git ls-files | grep -E '(^|/)\.env($|\.)|token|credential|secret|\.key$|\.pem$' && exit 1 || true
```

### Dashboard Generated

```bash
test -f /srv/argus/control-plane/dashboard/public/index.html
test -f /srv/argus/control-plane/dashboard/public/style.css
test -f /srv/argus/control-plane/dashboard/public/app.js
```

### Metrics Valid

```bash
python3 /srv/argus/control-plane/monitoring/collect_metrics.py
python3 -m json.tool /srv/argus/control-plane/dashboard/public/metrics.json >/dev/null
```

### Control API Local Only

```bash
ss -tulpen | grep ':8099' | grep '127.0.0.1'
```

Fail if bound to `0.0.0.0`.

### Caddy Validation

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

### Tailscale Dashboard Reachability

```bash
TS_IP="$(tailscale ip -4 | head -n 1)"
curl -I "http://$TS_IP:8088"
```

### Funnel Not Enabled

```bash
tailscale funnel status || true
```

Review output. P0 should not show Argus dashboard or workloads exposed publicly.

### Cloudflare Not Active Unexpectedly

```bash
systemctl is-active cloudflared || true
```

P0 expects inactive unless a future phase explicitly changes this.

### Cloudflare Plan Only

```bash
argus-cloudflare-plan
cat /srv/argus/cloudflare/planned-ingress.yml
```

This must not start tunnels.

### CLI Checks

```bash
argus-workloads
argus-health
argus-open intake-os || true
argus-doctor
argus-smoke-test
```

## Policy Tests

### Restricted Public Block

```bash
argus-privacy-set uptime-kuma restricted --reason "admin dashboard"
argus-access-preview uptime-kuma cloudflare-public
```

Expected: blocked.

### Tailnet Allowed

```bash
argus-access-preview uptime-kuma tailnet
```

Expected: allowed.

### Cloudflare Protected Planned

```bash
argus-access-preview intake-os cloudflare-protected
```

Expected: allowed or confirmation-required by policy, but P0 should not make it effective unless Cloudflare activation is implemented.

## Dashboard Tests

From phone on Tailscale:

1. Open dashboard.
2. Verify workloads appear.
3. Toggle monitor on.
4. Verify metrics load.
5. Toggle monitor off.
6. Enter admin mode.
7. Change a workload privacy state.
8. Verify audit event.
9. Preview an access change.
10. Verify unsafe public change is blocked.
