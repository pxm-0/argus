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
argus-workloads
```

## Open a Workload

```bash
argus-open intake-os
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
argus-health
```

## Run Inventory

```bash
argus-inventory
```

## Run Doctor

```bash
argus-doctor
```

## Run Smoke Test

```bash
argus-smoke-test
```

From the repository checkout before `/usr/local/bin` symlinks exist:

```bash
scripts/smoke-test
```

Offline/temp-root validation:

```bash
scripts/smoke-test --offline
```

## Scheduled Smoke

P5 adds a server-side timer that records smoke status locally.

Install only on `oreochiserver` after testing:

```bash
sudo cp /srv/argus/systemd/argus-smoke.service /etc/systemd/system/argus-smoke.service
sudo cp /srv/argus/systemd/argus-smoke.timer /etc/systemd/system/argus-smoke.timer
sudo systemctl daemon-reload
sudo systemctl enable --now argus-smoke.timer
```

Run once:

```bash
argus-smoke-scheduled
```

Status is written to:

```text
/srv/argus/runtime/smoke/latest.json
```

## Backup Retention

Preview pruning:

```bash
argus-backup-prune
```

Apply pruning:

```bash
argus-backup-prune --apply --confirm "prune argus backups"
```

Only approved backup destinations under
`/srv/argus/runtime/backups/<workload-id>` are eligible.

## Metrics

Run collector once:

```bash
argus-monitor
```

Install timer after testing:

```bash
sudo cp /srv/argus/systemd/argus-metrics.service /etc/systemd/system/argus-metrics.service
sudo cp /srv/argus/systemd/argus-metrics.timer /etc/systemd/system/argus-metrics.timer
sudo systemctl daemon-reload
sudo systemctl enable --now argus-metrics.timer
```

## Control API

Install service after testing:

```bash
sudo cp /srv/argus/systemd/argus-control-api.service /etc/systemd/system/argus-control-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now argus-control-api.service
```

Create token:

```bash
sudo install -d -o root -g argus -m 0750 /etc/argus
openssl rand -base64 32 | sudo tee /etc/argus/control-token >/dev/null
sudo chown root:argus /etc/argus/control-token
sudo chmod 0640 /etc/argus/control-token
```

Do not paste the token into logs or commits.

If the private dashboard API returns an empty response after config reconciliation,
or Caddy remains failed after a reboot because its Tailscale address was not ready,
run the scoped control-plane reconciliation:

```bash
sudo ./scripts/argus-control-plane-reconcile --preflight
sudo ./scripts/argus-control-plane-reconcile \
  --apply \
  --acknowledge-control-plane-reconcile
```

The apply step backs up the two mutable state files and any prior Caddy drop-in,
restores mode-`0600` access for the API service identity, validates Caddy before
restart, and installs failure retry ordering for `tailscaled.service`. It does not
change the configured Tailscale-only route or any workload.

## Preview Access Change

```bash
argus-access-preview intake-os cloudflare-protected
```

## Apply Access Change

```bash
argus-access-apply intake-os tailnet
```

For P0, Cloudflare-related states should generally update desired state and generate plans only.

## Set Privacy

```bash
argus-privacy-set intake-os sensitive --reason "Operator classification"
```

## Cloudflare Plan

```bash
argus-cloudflare-plan
```

This should generate:

```text
/srv/argus/cloudflare/planned-ingress.yml
```

and not start any tunnel. The generated file is local runtime evidence and is
not tracked by Git.

## Git Checkpoint

```bash
argus-git-checkpoint "Add dashboard monitoring"
```

This should not push.

## Workload Migration Plan

```bash
argus-migrate-workload-plan intake-os
```

Review before doing any move.

## Caddy Route

Generate the planned private route:

```bash
argus-caddy-dashboard-plan
```

The generated `caddy/dashboard.Caddyfile` is local review material and is not
tracked by Git.

Dashboard route should look like:

```caddyfile
http://oreochiserver:8088, http://100.x.y.z:8088 {
    bind 100.x.y.z
    root * /srv/argus/control-plane/dashboard/public
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
