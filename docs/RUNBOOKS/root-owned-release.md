# Runbook: run Argus from a root-owned release

Today every `argus-*` unit executes code from `/srv/argus`, a git checkout owned by `oreo`. Anyone who can
write there controls root-run services. A release is an immutable, root-owned export of one reviewed commit under
`/opt/argus/releases/<sha>`; `/opt/argus/current` is a symlink to the active one.

<!-- sudoers: root-shell-runbook (the first install happens before the sudo allowlist exists; run from a root shell) -->

## How a release is built

`scripts/argus-release-install --sha <40-hex>` (root only, no other arguments):

1. Refuses a sha that is not a commit in `/srv/argus`, is not reachable from `origin/main`, or when the checkout is dirty.
2. Runs `git archive <sha>` into a private staging directory, recomputes the git tree hash of the extracted files,
   and refuses unless it equals the commit's tree.
3. Replaces `runtime/` and `control-plane/dashboard/public/` with symlinks to the live checkout (both are gitignored
   state that services write) and writes `ARGUS_RELEASE` with the sha.
4. Runs `chown -R root:root`, strips group and other write everywhere, then renames the directory into place.
5. Atomically repoints `/opt/argus/current` (temporary symlink, then `rename`). Existing releases are never modified;
   installing the same sha twice is refused.

Git runs with `--no-optional-locks` and a per-command `safe.directory`, so root leaves no files in the `oreo` checkout.
Fetch first as `oreo` (`git -C /srv/argus fetch origin`); the commit and `origin/main` must exist locally.

Anything that writes under the release (for example `config/*.json`, `__pycache__`) now fails or is skipped.
`config/` is read-only: change it with a reviewed PR and a new release, not on the server.

## Apply (root shell)

1. Install the release for the merged sha:

   ```bash
   /srv/argus/scripts/argus-release-install --sha <merged-sha>
   readlink /opt/argus/current        # /opt/argus/releases/<sha>
   ```

2. Render and install the override drop-ins (they repoint `ExecStart`, `WorkingDirectory` and `ARGUS_ROOT`).
   `--units-dir` derives them from the units actually installed, which includes the generated
   `argus-m5-workload-*.service` units that the repository does not carry:

   ```bash
   /opt/argus/current/scripts/argus-sudoers-render --units-dir /etc/systemd/system --overrides-dir /root/argus-overrides
   cp -a --no-preserve=ownership /root/argus-overrides/. /etc/systemd/system/
   systemctl daemon-reload
   ```

3. Restart daemons one at a time and run the doctor between each. Order: `argus-capability-issuer`,
   `argus-operation-worker`, `argus-control-api`, `argus-migration-coordinator`, `argus-privileged-lifecycle-agent`,
   then each `argus-domain-agent@<domain>` and `argus-domain-agent-legacy-rootful`:

   ```bash
   systemctl restart argus-capability-issuer.service
   /opt/argus/current/scripts/argus-doctor --host
   ```

   The doctor line `<unit> ExecStart is under root-owned, non-group-writable paths` turns `ok` per unit; lines for
   units not yet restarted keep failing until their drop-in is active. Timer and oneshot units pick up the drop-in
   on their next run.

4. Switch the operator link: `ln -sfn /opt/argus/current/scripts/argus /usr/local/bin/argus`.

## Roll back

```bash
ln -sfn /opt/argus/releases/<previous-sha> /opt/argus/current
systemctl restart <units>
```

Or return to `/srv/argus` entirely: remove `/etc/systemd/system/*.service.d/10-argus-release.conf`, run
`systemctl daemon-reload`, and restart the units. `/srv/argus` is untouched by all of this.

## Upgrades afterwards

`sudo /opt/argus/current/scripts/argus-release-install --sha <sha>` (allowlisted), then restart the daemons whose code
changed. Render the overrides again only when `systemd/` changed. A root shell may delete old releases once no unit
points at them.

Other runbooks in this directory use the post-narrowing `/opt/argus/current/scripts` paths; before the cutover
substitute `/srv/argus/scripts`.
