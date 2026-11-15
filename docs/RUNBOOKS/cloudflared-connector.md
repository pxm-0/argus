# cloudflared connector (D027)

<!-- sudoers: root-shell-runbook (one-time connector install and the rare activation/rollback steps; once operator sudo is narrowed, run them from a root shell) -->

Installs the named-tunnel connector for the only allowlisted Cloudflare route
([D027](../ARGUS_V1_DECISIONS.md), threat model in
[NODENS_PUBLIC_ROUTE.md](../NODENS_PUBLIC_ROUTE.md)). Activation itself is in
[CLOUDFLARE.md](../CLOUDFLARE.md).

The connector must not run while `providers.cloudflare.enabled` is `false`:
smoke fails on an active `cloudflared` with the provider off. Steps 1-4 leave it
stopped.

## 1. Packages, identity and ingress access (server, sudo)

Install `cloudflared` from Cloudflare's signed package repository and `acl` from
Ubuntu. Then:

```bash
sudo install -m 0644 systemd/sysusers.d/argus-cloudflared.conf /etc/sysusers.d/
sudo systemd-sysusers /etc/sysusers.d/argus-cloudflared.conf
sudo setfacl -m u:cloudflared:x <production ingress directory of nodens-production>
sudo install -m 0644 systemd/cloudflared.service /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload   # do not enable or start yet
```

`cloudflared` has no login shell, no sudo and no docker group. Its only filesystem
grant is traverse (`--x`) on that one ingress directory; the unit also hides the
rest of the Argus state, `/srv`, `/etc/argus` and the Docker socket.

## 2. Tunnel (operator only)

Run these yourself, as your own user on the server. They open a Cloudflare
authorization link and write credentials; never paste their output anywhere.

```bash
cloudflared tunnel login          # authorize the nodens.dev zone
cloudflared tunnel create argus-nodens
```

Then move the tunnel credentials to the connector and remove your copy:

```bash
sudo install -d -m 0750 -o root -g cloudflared /etc/cloudflared
sudo install -m 0640 -o root -g cloudflared ~/.cloudflared/<tunnel-id>.json /etc/cloudflared/
shred -u ~/.cloudflared/<tunnel-id>.json
```

## 3. Catch-all-only config

`/etc/cloudflared/argus.yml`, mode `0644` (smoke reads it, it holds no secret):

```yaml
tunnel: <tunnel-id>
credentials-file: /etc/cloudflared/<tunnel-id>.json
ingress:
  - service: http_status:404
```

Check it with `cloudflared tunnel --config /etc/cloudflared/argus.yml ingress validate`.

## 4. DNS (operator)

```bash
cloudflared tunnel route dns argus-nodens nodens.dev
cloudflared tunnel route dns argus-nodens www.nodens.dev
rm ~/.cloudflared/cert.pem        # the account certificate is not needed to run
```

Until activation adds their rules, both names answer 404 from the catch-all.

## 5. Provider on, connector on

Merge the pull request that sets the provider `enabled`, `provisioned` and
`allowNamedTunnels` to `true`, deploy it, then:

```bash
sudo systemctl enable --now cloudflared
scripts/smoke-test   # "no unexpected cloudflared active" must pass
```

Create the Cloudflare Access application for both hostnames, limited to the
operator, before running the protected activation.

## Stop or remove

`sudo systemctl stop cloudflared` cuts all Cloudflare traffic at once. To remove
the connector: disable the unit, delete the tunnel at Cloudflare, remove
`/etc/cloudflared`, the unit, the sysusers file, the ACL
(`setfacl -x u:cloudflared <dir>`) and the user.
