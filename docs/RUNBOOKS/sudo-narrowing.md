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
  `argus m1 sync|verify`, `argus-release-install --sha *`. Each script validates its own arguments
  (image allowlist and digest, 40-hex sha, trust domain).
- `ARGUS_SYSTEMCTL`: `restart` of named daemons only, `start argus-smoke|argus-estate-refresh|argus-backup-snapshot.service`,
  `--no-pager status <unit>`, `daemon-reload`. No globs.
- `ARGUS_READ`: one `journalctl --no-pager -n 200 -u <unit>` line per daemon.
- `ARGUS_NET`: `tailscale serve status`, `ss -H -ltnp`, and the exact `tailscale serve` lines for 8450 and 8451.
- Defaults: `!env_keep`, `env_reset`, `secure_path`, and `noexec` (everything except `ARGUS_SCRIPTS`, which spawn docker, runuser and git).

Excluded on purpose: the one-time M5 cutover tools, `python3`, `bash`, `cp`, `mv`, `sed`, `tee`,
`install`, `docker`, and any `systemctl enable|stop|edit|link`. The yog-sothoth entries
(`/etc/sudoers.d/oreo-yog-sothoth`) are left untouched by decision and show as a warning in `argus doctor --host`.

The server runs **sudo-rs**, not classic sudo. It accepts only exact argument words or a lone `*`, and it has no
`log_output`; the rendered file stays inside that subset (`--log-output` exists for classic sudo only, and is not
used here). Always validate with the server's own `visudo`.

## Before you start

1. The release path is live: `root-owned-release.md` is applied and `/opt/argus/current` exists.
2. Open **two** root sessions (console, `ssh root@...`, or `su -`) and keep both until the last step.
   If the only way to get root is `sudo`, stop: you would lock yourself out.
3. On the Mac, set `ARGUS_REMOTE_REPO=/opt/argus/current` for `argus release pin|import|promote`
   (they call `sudo -n $ARGUS_REMOTE_REPO/scripts/argus-image-import`).
4. Decide which one-time M5 tools you still need. They will need the break-glass path.

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
```

A snapshot, a restart and an image-import dry path must all succeed before you continue. The negative cases can only
be proven after the broad grant is gone (next step).

## Remove the broad grant (root shell A), last

Only when every test passed and `argus doctor --host` shows no failing `sudoers` or `ExecStart` line:

```bash
rm /etc/sudoers.d/90-codex-nopasswd
visudo -c
```

From the third session, the negatives must now be refused: `sudo -n true`, `sudo -n bash`, `sudo -n /usr/bin/systemctl restart sshd`,
and the allowlisted commands must still work. Keep root shell B until they behave. Optionally drop the root-equivalent
groups, then log `oreo` out and in again (running sessions keep their old groups):

```bash
gpasswd -d oreo docker
gpasswd -d oreo lxd
```

Domain agents and the importer run as their own users or root, so they are unaffected; `oreo` loses direct `docker` use.

## Rollback

From the retained root shell:

```bash
install -m 0440 -o root -g root /root/sudoers-backup/sudoers.d.<stamp>/90-codex-nopasswd /etc/sudoers.d/90-codex-nopasswd
rm -f /etc/sudoers.d/argus-operator
visudo -c
```

Groups: `gpasswd -a oreo docker` and `gpasswd -a oreo lxd`, then log in again.

## Break-glass and lockout recovery

- Retained root shell or console: restore as above.
- No root shell left and `sudo` refuses: from the physical console or hypervisor log in as root, or run `pkexec visudo`
  as `oreo` (polkit) and delete `argus-operator`; as a last resort boot single-user and restore `/etc/sudoers.d`
  from `/root/sudoers-backup`.
- Structural changes after narrowing (install a unit, `systemctl enable`, firewall apply, one-time M5 tools):
  open a root shell, make the change, and write it up. Do not widen the committed allowlist for a one-off.

## Residual risk

`argus-release-install` installs any commit reachable from `origin/main` in the `oreo`-owned `/srv/argus`
checkout, and `oreo` controls that checkout's refs. Narrowing protects against services and stray processes running
as other users and removes arbitrary commands; it does not stop an attacker who is already `oreo` from landing hostile
code through the installer. Follow-up: verify signed commits or a remote ref before install.

Re-render after any change to `systemd/` or the domain list: `scripts/argus-sudoers-render > deploy/sudoers/argus-operator`.
