# D3 systemd and schedule collectors

Issue: `#323`

D3 adds four D1b sources on `oreochiserver`:

| Source | Identity | Scope |
| --- | --- | --- |
| `oreochiserver.system-schedules` | `oreo:argus-control` | system services/timers, `/etc/crontab`, and `/etc/cron.*` metadata |
| `oreochiserver.user-schedules-oreo` | `oreo:argus-control` | oreo's user services/timers and crontab |
| `oreochiserver.user-schedules-personal-sandbox` | `argus-personal-sandbox:argus-control` | personal user services/timers and crontab |
| `oreochiserver.user-schedules-work-sandbox` | `argus-work-sandbox:argus-control` | work user services/timers and crontab |

The collector uses exact read-only `systemctl` and `crontab -l` argv. It does
not execute a cron or systemd payload. Unit state is limited to the unit name,
load/active/sub-state, enabled flag, timer target, and a boolean legacy-reference
marker. Cron observations contain only a hashed entry identity, location,
schedule class, owner where applicable, and the same marker. Directory records
contain file name, mode, and location; file contents and command lines never
cross the normalized observation boundary.

`legacyReference=true` is evidence that a known migrated naming/path marker was
seen while scanning the bounded source. It is not an admission or disablement
decision. D5 reconciliation remains responsible for mapping evidence to a
canonical workload and presenting any action blocker.

## Verification

Fixture acceptance is deterministic and repeats the current/previous D1b page
contract three times:

```bash
scripts/argus-d3-systemd-schedule-acceptance \
  --root <reviewed-checkout> \
  --source-revision <commit> \
  --captured-at <UTC timestamp> \
  --target local-ci
```

Authoritative acceptance runs the same command on `oreochiserver` from a clean
reviewed checkout while the four collector units use temporary reviewed source
projections and sockets. The acceptance runner writes only sanitized counts and
digests; it does not restart services, change crontabs, alter systemd state, or
touch workloads.

Deployment units are templates only. Installation, source projection, and
enablement remain a separate reviewed server change after this PR and its
dependency chain are merged.
