# Runbook: run argus-control-api as the unprivileged `argus-api` user

Why: the API ran as `oreo` (NOPASSWD sudo, docker group), so any bug in
`server.py` was root. The unit now runs as `argus-api:argus-control` with an
empty capability bounding set, `ProtectSystem=strict`, `ProtectHome`,
`PrivateTmp`, `NoNewPrivileges`, `MemoryDenyWriteExecute`, `LockPersonality`,
`SystemCallFilter=@system-service` and `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`.

Requires a maintenance window and a pre-change snapshot (backup-snapshot).
Keep a root shell open on the server for the whole procedure.

## Access audit (what the API needs, and what it does not)

| Path | Needed? | How `argus-api` gets it |
|---|---|---|
| `/var/lib/argus/control/operations.sqlite3` (`argus-worker:argus-control 0660`) | yes, read/write | group `argus-control`; directory must be group-writable for SQLite WAL files |
| `/var/lib/argus/control/session.sqlite3` (today `oreo`) | yes | chown below |
| `/etc/argus/{control-token,operators.json,operator-proxy-token}` (root 0600) | yes | `LoadCredential=` (systemd reads as root); no file access needed |
| `/run/argus/domains/*/agent.sock`, `/run/argus/privileged-lifecycle/agent.sock` (group `argus-control`, 0660) | yes, connect | group `argus-control` |
| `/srv/argus/runtime/argus/*` (setgid `argus-control`, group rw) | yes | group `argus-control` |
| `/etc/argus/domain-keys/*.key` (`legacy-rootful.key` is `oreo:oreo 0400`) | **no** | `grep` shows `server.py` never opens domain keys; the API only verifies/forwards through agents, and the issuer public keys in `/etc/argus/domains/*/issuer.pub` are world-readable. The key stays with `oreo` (its legacy agent) and the API must NOT be granted it. |
| docker sockets | no | stay blocked by `InaccessiblePaths=` |

Notes: `StateDirectory=` was removed from the unit because systemd would chown
the shared ledger directory to the API user. Ownership is set explicitly below.
`handle_workload_discover` shells out to `scripts/argus-workload-discover`; with
no docker access that path reports what an unprivileged user can see. Verify it
on the dashboard after migration. `scripts/argus-m5-runtime-permissions` still
names `API_USER="oreo"` for file ownership; group `argus-control` access keeps
that compatible, and re-running it will not break the new user.

## Migrate

```sh
cd /srv/argus && git pull --ff-only        # operator step, after the PR is merged
sudo install -m 0644 systemd/sysusers.d/argus-api.conf /etc/sysusers.d/argus-api.conf
sudo systemd-sysusers /etc/sysusers.d/argus-api.conf
id argus-api                               # expect: groups argus-api,argus-control; no sudo/docker

sudo systemctl stop argus-control-api
sudo chown argus-api:argus-control /var/lib/argus/control/session.sqlite3
sudo chmod 0600 /var/lib/argus/control/session.sqlite3
sudo chown root:argus-control /var/lib/argus/control            # was oreo:argus-control
sudo chmod 2770 /var/lib/argus/control
# leave operations.sqlite3 at argus-worker:argus-control 0660 (do not touch)
# leave /etc/argus/domain-keys/legacy-rootful.key at oreo:oreo 0400

sudo install -m 0644 systemd/argus-control-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart argus-control-api
```

Directory ownership by root with group write keeps the worker (group member)
and the API able to create SQLite sidecar files while neither owns the directory.

## Verify

```sh
systemctl show argus-control-api -p User -p CapabilityBoundingSet   # User=argus-api, empty set
sudo -u argus-api sudo -n true; sudo -u argus-api docker ps          # both must fail
sudo /srv/argus/scripts/argus-doctor --host
sudo journalctl -u argus-control-api -n 50 --no-pager                # no EACCES / PermissionError
/srv/argus/scripts/smoke-test
```

Then log in to the dashboard (session cookie, step-up) and open an operation.
`argus-doctor` WARNs if a NOPASSWD sudoers drop-in names `argus-api`; narrowing
the `oreo` NOPASSWD drop-in is a separate operator task.

## Rollback to `User=oreo` (data is untouched)

```sh
sudo systemctl stop argus-control-api
sudo sed -i 's/^User=argus-api$/User=oreo/' /etc/systemd/system/argus-control-api.service
sudo chown oreo:argus-control /var/lib/argus/control /var/lib/argus/control/session.sqlite3
sudo chmod 2770 /var/lib/argus/control
sudo systemctl daemon-reload && sudo systemctl restart argus-control-api
```

(`StateDirectory=` need not be restored; the directory already exists.)
Alternatively revert the PR and reinstall the old unit.
