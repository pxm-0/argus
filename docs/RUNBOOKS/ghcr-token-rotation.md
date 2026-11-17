# Runbook: rotate the GHCR pull token

`argus-image-import` pulls `ghcr.io/pxm-0/*@sha256:*` on the host and loads it into a sealed domain. The credential
is a **classic personal access token with only `read:packages`**, lifetime 90 days (a fine-grained token cannot read
GHCR packages). It is stored only in `/etc/argus/registry/.docker/config.json` (root, mode 0600), which
`argus-image-import` selects with `DOCKER_CONFIG` once it exists, so the pull no longer depends on root's `~/.docker`.

<!-- sudoers: root-shell-runbook (rotation happens in a root shell; the token never touches a command line or an edited file) -->

`scripts/argus-doctor --host` has a `ghcr-credential` check: the file is a root-owned regular file, 0600, in a root-owned
non-writable directory; `auths` holds `ghcr.io` only; token age (from `/var/lib/argus/ghcr-token-rotated`) warns at
75 days and fails at 90; `scripts/argus-doctor --host --online` also asks GitHub for the token's scopes and fails unless they
are exactly `read:packages`.

## Rotate

1. Create the new token (operator, in the browser): GitHub, Settings, Developer settings, Tokens (classic), scope
   `read:packages` only, expiry 90 days. Prefer a dedicated machine user that has read access to the packages.
2. In a root shell on the server, log in without echoing the token to the terminal or shell history:

   ```bash
   install -d -m 0700 -o root -g root /etc/argus/registry /etc/argus/registry/.docker
   read -rs GHCR_TOKEN
   printf '%s' "$GHCR_TOKEN" | DOCKER_CONFIG=/etc/argus/registry/.docker docker login ghcr.io -u <github-user> --password-stdin
   unset GHCR_TOKEN
   chmod 0600 /etc/argus/registry/.docker/config.json
   date -u +%Y-%m-%dT%H:%M:%SZ > /var/lib/argus/ghcr-token-rotated
   ```

3. Prove it end to end, then revoke the old token on GitHub:

   ```bash
   /opt/argus/current/scripts/argus-doctor --host --online
   /opt/argus/current/scripts/argus-image-import --domain personal-sandbox --image ghcr.io/pxm-0/<name>@sha256:<known-digest>
   ```

4. First migration only: once step 3 passes, run `docker logout ghcr.io` for root's old `~/.docker` login so a single
   credential remains.

Never paste the token into chat, a ticket, an env file, or a Compose file. Calendar the next rotation for day 75.

## If a pull fails

`unauthorized` or `denied`: the token expired or was revoked; rotate. A `ghcr-credential` mode or `auths` failure:
fix the file; do not loosen the check. To roll back, recreate the previous login in the same directory, or remove
`/etc/argus/registry` (the importer then falls back to the ambient Docker config).
