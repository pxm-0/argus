# Operations Guide

## Open Dashboard

From a Tailscale-connected device:

```text
http://oreochiserver:8088
```

Fallback:

```text
http://<tailscale-ip>:8088
```

## List Workloads

```bash
oreo-workloads
```

## Open a Workload

```bash
oreo-open intake-os
```

Expected output:

```text
Intake OS
Desired: tailnet
Effective: tailnet
URL: http://oreochiserver:8080
```

## Check Health

```bash
oreo-health
```

## Run Inventory

```bash
oreo-inventory
```

## Run Doctor

```bash
oreo-doctor
```

## Run Smoke Test

```bash
oreo-cloud-smoke-test
```

From the repository checkout before `/usr/local/bin` symlinks exist:

```bash
scripts/smoke-test
```

Offline/temp-root validation:

```bash
scripts/smoke-test --offline
```

## Metrics

Run collector once:

```bash
oreo-monitor
```

Install timer after testing:

```bash
sudo cp /srv/oreo-cloud/systemd/oreo-metrics.service /etc/systemd/system/oreo-metrics.service
sudo cp /srv/oreo-cloud/systemd/oreo-metrics.timer /etc/systemd/system/oreo-metrics.timer
sudo systemctl daemon-reload
sudo systemctl enable --now oreo-metrics.timer
```

## Control API

Install service after testing:

```bash
sudo cp /srv/oreo-cloud/systemd/oreo-control-api.service /etc/systemd/system/oreo-control-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now oreo-control-api.service
```

Create token:

```bash
sudo install -d -o root -g oreo -m 0750 /etc/oreo-cloud
openssl rand -base64 32 | sudo tee /etc/oreo-cloud/control-token >/dev/null
sudo chown root:oreo /etc/oreo-cloud/control-token
sudo chmod 0640 /etc/oreo-cloud/control-token
```

Do not paste the token into logs or commits.

## Preview Access Change

```bash
oreo-access-preview intake-os cloudflare-protected
```

## Apply Access Change

```bash
oreo-access-apply intake-os tailnet
```

For P0, Cloudflare-related states should generally update desired state and generate plans only.

## Set Privacy

```bash
oreo-privacy-set intake-os sensitive --reason "Operator classification"
```

## Cloudflare Plan

```bash
oreo-cloudflare-plan
```

This should generate:

```text
/srv/oreo-cloud/cloudflare/planned-ingress.yml
```

and not start any tunnel.

## Git Checkpoint

```bash
oreo-git-checkpoint "Add dashboard monitoring"
```

This should not push.

## Workload Migration Plan

```bash
oreo-migrate-workload-plan intake-os
```

Review before doing any move.

## Caddy Route

Generate the planned private route:

```bash
oreo-caddy-dashboard-plan
```

Dashboard route should look like:

```caddyfile
http://oreochiserver:8088, http://100.x.y.z:8088 {
    bind 100.x.y.z
    root * /srv/oreo-cloud/control-plane/dashboard/public
    handle /api/* {
        reverse_proxy 127.0.0.1:8099
    }
    file_server
}
```

Replace `100.x.y.z` with the actual Tailscale IP.

Install only after review:

```bash
sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.backup.$(date +%Y%m%d-%H%M%S)"
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Reload only after validation passes.
