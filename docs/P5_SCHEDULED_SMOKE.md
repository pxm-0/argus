# P5 Scheduled Smoke

P5 adds a systemd timer for scheduled smoke checks. The timer is server-side
only and should be installed on `oreochiserver` after the PR lands.

## Files

- `scripts/argus-smoke-scheduled`
- `systemd/argus-smoke.service`
- `systemd/argus-smoke.timer`

The service runs a root-only, no-network container-creation preflight through
each sandbox's private Docker socket before dropping to the `oreo` identity for
the normal smoke suite. Only sanitized mode-`0644` results are handed across
that boundary. Missing, failed, or stale runtime-probe evidence fails the run,
as does any ordinary smoke warning; scheduled acceptance is therefore exactly
zero failures and zero warnings.

## Behavior

`argus-smoke-scheduled` runs `scripts/smoke-test`, captures output, writes local
status evidence, and records an audit event.

Outputs:

```text
/srv/argus/runtime/smoke/latest.log
/srv/argus/runtime/smoke/latest.json
```

The status JSON contains the command, timestamp, exit code, failure count,
warning count, sanitized per-domain runtime-probe state, and log path. It does
not send network alerts or call external services.

## Install

On `oreochiserver` only:

```bash
cd /srv/argus
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -o root -g root -m 0700 "/var/lib/argus/config-backups/scheduled-smoke-$stamp"
sudo cp --preserve=all /etc/systemd/system/argus-smoke.service \
  "/var/lib/argus/config-backups/scheduled-smoke-$stamp/argus-smoke.service"
sudo install -d -o root -g root -m 0755 \
  /usr/local/lib/argus /usr/local/lib/argus/fixtures
sudo install -o root -g root -m 0755 scripts/argus-m5-rootless-gid-repair \
  /usr/local/lib/argus/argus-m5-rootless-gid-repair
sudo install -o root -g root -m 0644 scripts/fixtures/argus-hello-world-amd64.tar \
  /usr/local/lib/argus/fixtures/argus-hello-world-amd64.tar
sudo install -o root -g root -m 0644 systemd/argus-smoke.service \
  /etc/systemd/system/argus-smoke.service
sudo install -o root -g root -m 0644 systemd/argus-smoke.timer \
  /etc/systemd/system/argus-smoke.timer
sudo systemd-analyze verify /etc/systemd/system/argus-smoke.service
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
