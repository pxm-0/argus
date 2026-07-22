# P5 Scheduled Smoke

P5 adds a systemd timer for scheduled smoke checks. The timer is server-side
only and should be installed on `oreochiserver` after the PR lands.

## Files

- `scripts/argus-smoke-scheduled`
- `systemd/argus-smoke.service`
- `systemd/argus-smoke.timer`

## Behavior

`argus-smoke-scheduled` runs `scripts/smoke-test`, captures output, writes local
status evidence, and records an audit event.

Outputs:

```text
/srv/argus/runtime/smoke/latest.log
/srv/argus/runtime/smoke/latest.json
```

The status JSON contains the command, timestamp, exit code, failure count,
warning count, and log path. It does not send network alerts or call external
services.

## Install

On `oreochiserver` only:

```bash
cd /srv/argus
sudo cp systemd/argus-smoke.service /etc/systemd/system/argus-smoke.service
sudo cp systemd/argus-smoke.timer /etc/systemd/system/argus-smoke.timer
sudo systemctl daemon-reload
sudo systemctl enable --now argus-smoke.timer
```

## Verify

```bash
sudo systemctl start argus-smoke.service
systemctl status argus-smoke.service --no-pager
python3 -m json.tool runtime/smoke/latest.json >/dev/null
```

The service should pass with `0 failure(s), 0 warning(s)` on the server. Offline
Mac validation may have warnings and is not server evidence.
