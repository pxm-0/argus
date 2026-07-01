# P5 Scheduled Smoke

P5 adds a systemd timer for scheduled smoke checks. The timer is server-side
only and should be installed on `oreochiserver` after the PR lands.

## Files

- `scripts/oreo-smoke-scheduled`
- `systemd/oreo-smoke.service`
- `systemd/oreo-smoke.timer`

## Behavior

`oreo-smoke-scheduled` runs `scripts/smoke-test`, captures output, writes local
status evidence, and records an audit event.

Outputs:

```text
/srv/oreo-cloud/runtime/smoke/latest.log
/srv/oreo-cloud/runtime/smoke/latest.json
```

The status JSON contains the command, timestamp, exit code, failure count,
warning count, and log path. It does not send network alerts or call external
services.

## Install

On `oreochiserver` only:

```bash
cd /srv/oreo-cloud
sudo cp systemd/oreo-smoke.service /etc/systemd/system/oreo-smoke.service
sudo cp systemd/oreo-smoke.timer /etc/systemd/system/oreo-smoke.timer
sudo systemctl daemon-reload
sudo systemctl enable --now oreo-smoke.timer
```

## Verify

```bash
sudo systemctl start oreo-smoke.service
systemctl status oreo-smoke.service --no-pager
python3 -m json.tool runtime/smoke/latest.json >/dev/null
```

The service should pass with `0 failure(s), 0 warning(s)` on the server. Offline
Mac validation may have warnings and is not server evidence.
