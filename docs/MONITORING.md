# Monitoring and alerts

Argus raises alerts from evidence it already writes. Nothing here sends mail, pages a phone service or calls an
external API. Alerts reach the operator two ways: a banner on the private dashboard (next to the exposure banner,
red while any alert is open) and a macOS notification from a launchd poller on the operator's Mac.

## Pieces

| Piece | Where | What it does |
| --- | --- | --- |
| `scripts/argus-alert` | server, `oreo`, every 2 min (`argus-alert.timer`, `OnBootSec=2min`) | collects read-only evidence, evaluates the checks, writes `runtime/alerts/state.json`, audits each open and resolve |
| `argus-alert-unit@.service` | server | started by `OnFailure=` drop-ins on the smoke, metrics, estate-refresh and backup services so a failure is evaluated at once instead of at the next tick |
| dashboard banner | `/api/dashboard-state` `alerts` key | the existing dashboard-state path reads the state file; no API change |
| `scripts/argus-alert-poller` | Mac, launchd `dev.argus.alert-poller`, every 60 s | reads the state over ssh and runs `osascript` for new or changed alerts |
| `argus smoke status`, `argus backup list\|freshness`, `argus alerts` | server | read-only views of the same evidence |

## Checks

Severity `page` is red-and-act-now, `warn` is act-this-week. Limits are strict: exactly at the limit is still healthy.

| Alert id | Opens when | Severity |
| --- | --- | --- |
| `unit-failed:<unit>` | `systemctl --failed` lists an `argus-*` unit | page |
| `smoke-failed` | `runtime/smoke/latest.json` has `ok == false` | page |
| `smoke-stale` | `latest.json` older than 26 h (smoke runs every 6 h) | warn |
| `snapshot-stale` | `/var/lib/argus/snapshot-last.json` older than 24 h | page |
| `db-backup-stale:<name>` | last successful `argus-workload-db-backup@<name>` finish older than 26 h | page |
| `health:<workload>` | health URL fails twice in a row for an active typed workload | page for `personal-managed`, warn otherwise |
| `container-exited:<name>` | a registered, not yet migrated workload's container exited more than 7 d ago | warn |
| `disk-usage` | root filesystem at 80 % (warn) or 90 % (page) | warn / page |
| `deploy-behind` | `/srv/argus` is behind `origin/main` and the oldest missing commit is older than 24 h | warn |
| `egress-drift:<workload>` | the workload's `argus-m5-workload-*` run reports `egressPolicyDrift` | warn |
| `m1-drift` | `argus doctor`'s M1 drift check reports drift | warn |
| `tailscale-backend` / `tailscale-key-expiry` | `BackendState` is not `Running` / node key expires within 14 d (page once expired) | page / warn |
| `cert-expiry:<host:port>` | the certificate served on a typed workload health endpoint (TLS handshake, no file read) expires within 14 d, when `openssl` exists; unknown (alerts kept) when no endpoint answers | warn (page once expired) |

Every input is optional. A missing or unreadable file, an absent tool or a failed command makes that check
"unknown": it opens nothing and leaves already-open alerts alone. "Healthy" is only ever concluded from evidence.

Alert details are fixed-format text, run through a scrubber (tokens, bearer headers, age identities, long opaque
strings) and capped at 200 characters. Health probes record the failure class (`status 503`, `request failed:
URLError`), never the URL or the response body.

Known limits: `deploy-behind` compares local refs, so it only sees what the last deploy-time `git fetch` saw;
rootless sandbox containers are in daemons this identity cannot read, so `container-exited` covers rootful
registered workloads only, and it needs the `docker` group that the sudo-narrowing change removes (the check then
becomes unknown, not failing); the `argus-m5-workload-*` journal is read through the `adm` group.

## State file

`runtime/alerts/state.json`, mode 0644, written atomically:

```json
{"schemaVersion": 1, "generatedAt": "...Z", "summary": {"open": 1, "page": 1, "warn": 0},
 "probeFailures": {"nodens-production": 1},
 "alerts": [{"id": "unit-failed:argus-smoke.service", "severity": "page", "since": "...Z",
             "detail": "systemd unit is in the failed state", "lastSeen": "...Z", "acked": false}]}
```

`since` is when the alert opened and survives re-evaluation (dedupe); `lastSeen` moves every run. An alert
that stops matching is removed and an `alert.resolved` audit event is written (`alert.opened` on the way in,
`alert.changed` if its severity moves). `acked` is carried through but nothing sets it yet.

## Smoke history

`argus-smoke-scheduled` appends one row per server run to `runtime/smoke/smoke-history.jsonl` and drops rows older
than 30 days. Each row has the result, counts, the runtime-probe verdict and up to ten `FAIL`/`WARN` check names, so a
transient failure stays diagnosable after `latest.log` is rewritten by the next run. `argus smoke status --last 20`
prints it. `argus-smoke.timer` now fires at 00, 06, 12 and 18 UTC with up to 15 minutes of jitter.

## Install (server, operator approval)

Step 0 (Mac or server, before pulling on the server): after the last wave-2 PR is merged, run
`mise exec -- ./scripts/argus-check --boundary-only` on main. Every wave-2 PR rewrites `expectedSbomDigest` in
`config/core-boundary-policy.json`, so the merged tree can fail with a digest mismatch. The failure output is already
JSON and carries the true `sbomDigest` and `endpointDigest`; write them into the policy file, run the full
`./scripts/argus-check` until it passes, and land that as a small PR. Do not pull on the server until main passes.

Step 1: record the rollback point first (`git -C /srv/argus rev-parse HEAD`), then `git pull --ff-only` and
`python3 scripts/argus-check --boundary-only`. Rollback of the pull is `git reset --hard <recorded sha>` (`runtime/` is
untracked, so it is untouched).

Then run the whole block below from `/srv/argus` as the operator (do not hand-pick lines: the first lines back up the
current units, which the rollback needs). The evaluator itself runs as `User=oreo`; run any manual evaluation as oreo
(`sudo -u oreo python3 scripts/argus-alert`), never as root, or `runtime/alerts/` ends up root-owned.

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -m 0700 "/var/lib/argus/config-backups/alerting-$stamp"
sudo cp --preserve=all -r /etc/systemd/system/argus-smoke.timer /etc/systemd/system/argus-smoke.service \
  /etc/systemd/system/argus-metrics.service /etc/systemd/system/argus-estate-refresh.service \
  "/var/lib/argus/config-backups/alerting-$stamp/"
sudo install -m 0644 systemd/argus-alert.service systemd/argus-alert.timer 'systemd/argus-alert-unit@.service' /etc/systemd/system/
sudo install -m 0644 systemd/argus-smoke.timer /etc/systemd/system/argus-smoke.timer
for unit in argus-smoke.service argus-metrics.service argus-estate-refresh.service \
            'argus-workload-db-backup@.service' argus-backup-snapshot.service; do
  sudo install -d -m 0755 "/etc/systemd/system/$unit.d"
  sudo install -m 0644 "systemd/$unit.d/onfailure.conf" "/etc/systemd/system/$unit.d/onfailure.conf"
done
sudo systemd-analyze verify /etc/systemd/system/argus-alert.service 'argus-alert-unit@x.service'
sudo systemctl daemon-reload
sudo systemctl enable --now argus-alert.timer
sudo systemctl restart argus-smoke.timer
```

Notes: `argus-backup-snapshot.service` does not exist until the backups PR lands, so its drop-in directory dangles
until then (harmless). `argus-smoke.timer` moves from daily to every 6 hours, so the root `rootless-gid-repair --probe`
pre-steps run four times as often. The `argus-alert.service` sandbox (`ProtectSystem=strict`, `NoNewPrivileges`, only
`/srv/argus/runtime` writable) is first exercised under real systemd by the verify steps below, as is the `OnFailure=`
trigger for the `argus-workload-db-backup@kadath.service` instance.

Verify:

```bash
systemctl list-timers 'argus-alert*' 'argus-smoke*' --no-pager
python3 -m json.tool runtime/alerts/state.json
argus alerts --json
```

Prove the loop with a temporary failing unit, then remove it:

```bash
printf '[Service]\nType=oneshot\nExecStart=/bin/false\n' | sudo tee /etc/systemd/system/argus-alerttest.service >/dev/null
sudo systemctl daemon-reload && sudo systemctl start argus-alerttest.service || true
sudo systemctl start argus-alert.service && argus alerts       # unit-failed:argus-alerttest.service is open
sudo systemctl reset-failed argus-alerttest.service
sudo rm /etc/systemd/system/argus-alerttest.service && sudo systemctl daemon-reload
sudo systemctl start argus-alert.service && argus alerts       # resolved
grep alert. runtime/audit.log | tail -2
```

The next scheduled smoke run must add a row to `runtime/smoke/smoke-history.jsonl`.

## Install (Mac, operator)

```bash
cp ops/launchd/dev.argus.alert-poller.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.argus.alert-poller.plist
launchctl print gui/$(id -u)/dev.argus.alert-poller | head
tail ~/Library/Logs/argus-alert-poller.log
```

The plist assumes the repo at `~/Code/nodens/argus` and ssh host `oreochiserver` with key auth (`BatchMode`, so no
prompts). Override with `ARGUS_SSH_HOST`, `ARGUS_ARCHIVE_DIR` or `ARGUS_POLLER_STATE` in the plist's
`EnvironmentVariables`. The poller also warns when the newest `*.tar*` in `~/Archives/argus-snapshots` is older than
7 days (skipped while that directory does not exist), and raises `poller-unreachable` after five failed polls.
Notifications fire once per new or changed alert; a recurrence after resolution notifies again.

## Rollback

```bash
sudo systemctl disable --now argus-alert.timer
sudo rm /etc/systemd/system/argus-alert.service /etc/systemd/system/argus-alert.timer \
  '/etc/systemd/system/argus-alert-unit@.service'
sudo rm -r /etc/systemd/system/{argus-smoke,argus-metrics,argus-estate-refresh,argus-backup-snapshot}.service.d \
  '/etc/systemd/system/argus-workload-db-backup@.service.d'
# restore the pre-install smoke timer (stamp: `sudo ls /var/lib/argus/config-backups`)
sudo cp --preserve=all /var/lib/argus/config-backups/alerting-<stamp>/argus-smoke.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart argus-smoke.timer
launchctl bootout gui/$(id -u)/dev.argus.alert-poller
```

The old `argus-smoke.timer` comes back from the config backup taken by the install block. No other
state is touched; `runtime/alerts/` is disposable.
