# Runbook: narrow the operator's sudo to the reviewed allowlist

Today `oreo` has `NOPASSWD: ALL` (`/etc/sudoers.d/90-codex-nopasswd`), plus docker
and lxd group membership. Any process or agent running as `oreo` is root. This
runbook replaces the blanket grant with `deploy/sudoers/argus-operator`, a reviewed
allowlist whose commands live in a root-owned release tree
(`root-owned-release.md`). It is a maintenance-window change: the allowlist covers
day-to-day operation only, so anything structural (installing units, firewall
apply, one-time M5 tools, `systemctl enable`) afterwards needs the break-glass path
below.

Nothing in the repository applies this. The operator runs every step.

<!-- sudoers: root-shell-runbook (every command here runs from the retained root shell or as the tested operator) -->

## What the allowlist grants

Rendered by `scripts/argus-sudoers-render` (`--check` fails when the committed file is stale):

- `ARGUS_SCRIPTS` (tag `EXEC`): `argus-image-import --domain <d> --image *`, `argus-backup-snapshot`
  (no args, `--list`, `--verify *`, `--restore-plan *`), `argus-sandbox-firewall --domain <d> --plan|--verify|--probe`,
  `argus m1 sync|verify`, and `argus-promote-evidence --workload <staging> --image *` (read-only; what
  `argus promote` runs over ssh). Each script validates its own arguments (image allowlist and digest,
  image id, trust domain). `argus-release-install` is **not** here: it publishes the code every other entry runs as
  root, so it stays root-shell only (see Residual risk).
- `ARGUS_SYSTEMCTL`: `restart` of named daemons only, `start argus-smoke|argus-estate-refresh|argus-backup-snapshot.service`,
  `--no-pager status <unit>`, `daemon-reload`. No globs.
- `ARGUS_READ`: one `journalctl --no-pager -n 200 -u <unit>` line per daemon.
- `ARGUS_NET`: `tailscale serve status`, `ss -H -ltnp`, and the exact `tailscale serve` lines for 8450 and 8451.
- Defaults: `!env_keep`, `env_reset`, `secure_path`, and `noexec` (everything except `ARGUS_SCRIPTS`, which spawn docker, runuser and git).

Excluded on purpose: the one-time M5 cutover tools, `python3`, `bash`, `cp`, `mv`, `sed`, `tee`,
`install`, `docker`, and any `systemctl enable|stop|edit|link`. The yog-sothoth entries
(`/etc/sudoers.d/oreo-yog-sothoth`) are left untouched by decision and show as a warning in `scripts/argus-doctor --host`.

The server runs **sudo-rs**, not classic sudo. It accepts only exact argument words or a lone `*`, and it has no
`log_output`; the rendered file stays inside that subset (`--log-output` exists for classic sudo only, and is not
used here). Always validate with the server's own `visudo`.

## Before you start

1. The release path is live: `root-owned-release.md` is applied and `/opt/argus/current` exists.
2. Open **two** root sessions (console, `ssh root@...`, or `su -`) and keep both until the last step.
   If the only way to get root is `sudo`, stop: you would lock yourself out.
3. On the Mac, set `ARGUS_REMOTE_REPO=/opt/argus/current` for `argus release pin|import` and `argus promote`
   (they call `sudo -n $ARGUS_REMOTE_REPO/scripts/argus-image-import` and `.../argus-promote-evidence`).
4. Decide which one-time M5 tools you still need. They will need the break-glass path.
5. Docker consumers: the override drop-ins from `root-owned-release.md` include
   `20-argus-docker-group.conf` (`SupplementaryGroups=docker`) for `argus-metrics.service` and
   `argus-workload-discover.service` and `argus-alert.service`, the oreo-run units that call `docker ps|stats|inspect`. Confirm they are installed
   before the docker-group step below:
   `systemctl show -p SupplementaryGroups argus-metrics.service argus-workload-discover.service argus-alert.service` (all `docker`).

## Apply (root shell A)

```bash
umask 077
install -d -m 0700 /root/sudoers-backup
cp -a /etc/sudoers.d /root/sudoers-backup/sudoers.d.$(date -u +%Y%m%dT%H%M%SZ)
cp -a /etc/sudoers /root/sudoers-backup/sudoers.$(date -u +%Y%m%dT%H%M%SZ)
ls -l /root/sudoers-backup

/opt/argus/current/scripts/argus-sudoers-render > /root/argus-operator.new
cmp /root/argus-operator.new /opt/argus/current/deploy/sudoers/argus-operator
visudo -cf /root/argus-operator.new
install -m 0440 -o root -g root /root/argus-operator.new /etc/sudoers.d/argus-operator
visudo -c
```

Expected: `parsed OK` for the candidate and for every file in the final `visudo -c`.
If either fails, `rm /etc/sudoers.d/argus-operator` immediately and re-run `visudo -c`.

## Test (a third session, as oreo)

```bash
sudo -n -l
```

The listing must show the four aliases; `NOPASSWD: ALL` is still there because the old file is not removed yet.
Run each allowlisted command once, so a typo is found while the old grant still exists:

```bash
sudo -n /opt/argus/current/scripts/argus m1 verify
sudo -n /opt/argus/current/scripts/argus-backup-snapshot
sudo -n /opt/argus/current/scripts/argus-sandbox-firewall --domain personal-sandbox --plan
sudo -n /usr/bin/systemctl restart argus-operation-worker.service
sudo -n /usr/bin/systemctl --no-pager status argus-control-api.service
sudo -n /usr/bin/journalctl --no-pager -n 200 -u argus-control-api.service
sudo -n /usr/bin/ss -H -ltnp
sudo -n /usr/bin/tailscale serve status
sudo -n /opt/argus/current/scripts/argus-image-import --domain personal-sandbox --image ghcr.io/pxm-0/<name>@sha256:<known-digest>
sudo -n /opt/argus/current/scripts/argus-promote-evidence --workload nodens-staging --image sha256:<image-id>
```

From the Mac, `argus promote nodens-staging nodens-production --dry-run` must still find its evidence
(it uses the last command over ssh, and fails with `promote-evidence-unavailable` otherwise).

A snapshot, a restart and an image-import dry path must all succeed before you continue. The negative cases can only
be proven after the broad grant is gone (next step).

## Remove the broad grant (root shell A), last

Only when every test passed and `sudo /opt/argus/current/scripts/argus-doctor --host` shows no failing `sudoers` or `ExecStart` line:

```bash
rm /etc/sudoers.d/90-codex-nopasswd
visudo -c
```

From the third session, the negatives must now be refused: `sudo -n true`, `sudo -n bash`,
`sudo -n /usr/bin/systemctl stop sshd` and `sudo -n /usr/bin/systemctl edit sshd`, and the allowlisted commands must
still work. (Do not use `restart sshd` as the negative: the retained `oreo-yog-sothoth` file allows
`systemctl restart *`, so that command succeeds and restarts sshd.) Keep root shell B until they behave.

## Remove docker and lxd (root shell A), mandatory

Docker or lxd membership is root (`docker.sock` is `root:docker 0660`), so narrowing sudo means nothing while `oreo`
keeps either group. The operator decision is FULL, so this step is not optional. Only after the unit drop-ins from
Before you start, item 5 are active:

```bash
gpasswd -d oreo docker
gpasswd -d oreo lxd
systemctl start argus-metrics.service argus-workload-discover.service argus-alert.service
systemctl --no-pager status argus-metrics.service argus-workload-discover.service argus-alert.service
```

Both units must finish `active (exited)` / `inactive (dead)` with status 0, and the dashboard metrics must still show
the docker section. Then log `oreo` out and in again (running sessions keep their old groups; `id` must not list
docker or lxd). Domain agents and the importer run as their own users or root, so they are unaffected; `oreo` loses
direct `docker` use: deploys of non-Argus workloads (docker compose as `oreo`) now need a root shell or an
Argus operation. Nothing else may rely on `oreo`'s docker group: `systemctl show -p User,SupplementaryGroups 'argus-*'`
must list no other oreo-run unit that calls the docker CLI (`tests/test_argus_sudoers.py` enforces this for the units
in the repository).

## Rollback

From the retained root shell:

```bash
install -m 0440 -o root -g root /root/sudoers-backup/sudoers.d.<stamp>/90-codex-nopasswd /etc/sudoers.d/90-codex-nopasswd
rm -f /etc/sudoers.d/argus-operator
visudo -c
```

Groups: `gpasswd -a oreo docker` and `gpasswd -a oreo lxd`, then log in again. The unit drop-ins are harmless to keep.

## Break-glass and lockout recovery

- Retained root shell or console: restore as above.
- No root shell left and `sudo` refuses: from the physical console or hypervisor log in as root, or run `pkexec visudo`
  as `oreo` (polkit) and delete `argus-operator`; as a last resort boot single-user and restore `/etc/sudoers.d`
  from `/root/sudoers-backup`.
- Structural changes after narrowing (install a unit, `systemctl enable`, firewall apply, one-time M5 tools):
  open a root shell, make the change, and write it up. Do not widen the committed allowlist for a one-off.

## What this does not remove (read before calling it done)

`oreo` still has root paths after the final step. Narrowing is not complete until these are closed.

1. `/etc/sudoers.d/oreo-yog-sothoth` is kept by operator decision and is root-equivalent:
   `systemctl enable *`, `start *`, `restart *` (for example `sudo systemctl enable --now /home/oreo/x.service` runs
   an `oreo`-written unit as root; `noexec` does not help), `psql -U postgres *` and `psql *` as postgres, `systemd-creds`,
   and `install -m 0644 /home/oreo/yog-sothoth/.../yog-sothoth.service /etc/systemd/system/` (an `oreo`-owned file
   becomes a root unit). `scripts/argus-doctor --host` reports it as `ROOT-EQUIVALENT`. A refused `sudo -n bash` is not
   proof of containment while this file exists. Follow-up: replace the wildcards with exact
   `yog-sothoth.service` lines (and drop `psql`/`systemd-creds` or pin their arguments).
2. `oreo` is in the `sudo` group and has a password set; `/etc/sudoers` has `%sudo ALL=(ALL:ALL) ALL`. Anything that
   learns that password has root. Lock it (`passwd -l oreo`) or remove `oreo` from `sudo` once you have a root
   session that does not depend on it (key-based SSH as another admin, or the console).
3. `argus-release-install` is root-shell only. It cannot be allowlisted: it runs as root against the `oreo`-owned
   `/srv/argus` checkout, whose `.git/config`, refs and objects `oreo` controls (a `core.fsmonitor` or filter setting
   there is code execution as root in any git command that honours it, a forged `origin/main` ref is a forged
   release). The installer neutralises the config vectors, never runs `git status`, and avoids `git archive`
   (smudge filters), but the only trust anchor is the sha the root operator types, taken from the merged PR on
   GitHub, not from the server. A future automated path would need a root-owned mirror fetched with a
   read-only deploy key, or signed commits.
4. The release tree is root-owned, but the scripts run by `ARGUS_SCRIPTS` still spawn `docker`, `runuser` and `git`
   under `EXEC`; their own argument validation is the control.

Re-render after any change to `systemd/` or the domain list: `scripts/argus-sudoers-render > deploy/sudoers/argus-operator`.
