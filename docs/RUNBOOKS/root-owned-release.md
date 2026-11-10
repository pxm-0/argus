# Runbook: run Argus from a root-owned release

Today every `argus-*` unit executes code from `/srv/argus`, a git checkout owned by `oreo`. Anyone who can
write there controls root-run services. A release is an immutable, root-owned export of one reviewed commit under
`/opt/argus/releases/<sha>`; `/opt/argus/current` is a symlink to the active one.

<!-- sudoers: root-shell-runbook (the first install happens before the sudo allowlist exists; run from a root shell) -->

## How a release is built

`scripts/argus-release-install --sha <40-hex>` (root shell only, no other arguments; it is not in the sudoers
allowlist because it would turn the allowlist into root):

1. Refuses a sha that is not a commit in `/srv/argus` or is not reachable from `origin/main`. A dirty checkout is
   irrelevant (the release is built from the commit object) and `git status` is never run: it executes
   repo-configured filters and `core.fsmonitor`, which the unprivileged repo owner controls.
2. Writes the commit's blobs (`git ls-tree` plus `git cat-file`, not `git archive`, which runs smudge filters) into a
   private staging directory, recomputes the git tree hash of the written files, and refuses unless it equals the
   commit's tree.
3. Replaces `runtime/` and `control-plane/dashboard/public/` with symlinks to the live checkout (both are gitignored
   state that services write) and writes `ARGUS_RELEASE` with the sha.
4. Runs `chown -R root:root`, strips group and other write everywhere, then renames the directory into place.
5. Atomically repoints `/opt/argus/current` (temporary symlink, then `rename`). Existing releases are never modified;
   installing the same sha twice is refused.

Git runs with `--no-optional-locks`, a per-command `safe.directory`, an empty environment, no system or global config,
and fsmonitor, hooks, pager and ssh command disabled, so root leaves no files in the `oreo` checkout and runs nothing the
checkout configures. Fetch first as `oreo` (`git -C /srv/argus fetch origin`); the commit and `origin/main` must exist
locally. The sha is the trust anchor: copy it from the merged PR on GitHub (`gh pr view <n> --json mergeCommit`), never
from the server. `origin/main` in the checkout is only a sanity check, because `oreo` can forge that ref.

Anything that writes under the release (for example `config/*.json`, `__pycache__`) now fails or is skipped.
`config/` is read-only: change it with a reviewed PR and a new release, not on the server.

## Apply (root shell)

1. Install the release for the merged sha. The very first run has no root-owned copy of the installer yet, so do not
   run it from the `oreo`-owned `/srv/argus`: copy it from the reviewed commit and compare hashes first. On the Mac:

   ```bash
   git -C ~/Code/nodens/argus show <merged-sha>:scripts/argus-release-install > /tmp/argus-release-install
   git -C ~/Code/nodens/argus rev-parse <merged-sha>:scripts/argus-release-install   # blob id
   git hash-object /tmp/argus-release-install                                        # must be identical
   ```

   Put that file in `/root/bootstrap/argus-release-install` (mode 0700) from the root shell, then:

   ```bash
   python3 /root/bootstrap/argus-release-install --sha <merged-sha>
   readlink /opt/argus/current        # /opt/argus/releases/<sha>
   ```

2. Render and install the override drop-ins (they repoint `ExecStart`, `WorkingDirectory` and `ARGUS_ROOT`).
   `--units-dir` derives them from the units actually installed, which includes the generated
   `argus-m5-workload-*.service` units that the repository does not carry. It also writes
   `argus-metrics.service.d/20-argus-docker-group.conf` and `argus-workload-discover.service.d/20-argus-docker-group.conf`
   (`SupplementaryGroups=docker`), which let those two oreo-run units keep docker after `oreo` leaves the docker group:

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

From a root shell, `/opt/argus/current/scripts/argus-release-install --sha <sha>` (the previous root-owned copy; not allowlisted by design), then restart the daemons whose code
changed. Render the overrides again only when `systemd/` changed. A root shell may delete old releases once no unit
points at them.

Other runbooks in this directory use the post-narrowing `/opt/argus/current/scripts` paths; before the cutover
substitute `/srv/argus/scripts`.
