# Dev Environment Protocol

Decided 2026-11-21 ([D029](ARGUS_V1_DECISIONS.md)); moved to its own cell by
[D030](ARGUS_V1_DECISIONS.md). Code is edited on the Mac; apps and tests run on
`oreochiserver`, inside the sealed sandbox cell (`work-sandbox`, role `sandbox`
in `config/argus/domains.json`), a rootless Docker cell that holds no workloads ([`ARGUS_M5_SANDBOX_RUNTIMES.md`](ARGUS_M5_SANDBOX_RUNTIMES.md)).
This replaces the earlier local devcontainer and compose dev stack model. The
OrbStack machine that rehearses Argus's own installers is documented separately
in [`SERVER_SIM.md`](SERVER_SIM.md). Threat model and rollback:
[`DEV_SANDBOX_THREAT_MODEL.md`](DEV_SANDBOX_THREAT_MODEL.md).

```text
Mac                                   oreochiserver (tailnet ssh)
---                                   ---------------------------
edit, git, lint, typecheck
docker build --platform linux/amd64   sudo -n argus-dev-sandbox load    (one argus-dev/<project>:<tag> image)
  (deps baked in; Mac has egress)  ─▶ sudo -n argus-dev-sandbox test    (sealed containers, exit code back)
docker save | ssh                     sudo -n argus-dev-sandbox results (tar of /out back to the Mac)
                                      sudo -n argus-dev-sandbox preview (Caddy on a unix socket,
                                                                          tailscale serve :8460/:8461)
```

## Rules

1. **Nothing runs on the Mac but editing and host-side checks.** Git, lint,
   format and type checks run locally. Dev servers and test suites run only
   through `scripts/argus-dev`.
2. **The sandbox stays sealed.** Dev containers have no network interface
   beyond loopback (`--network none`, or the netns of the run's first
   container), no published ports, no capabilities, no host mounts, and
   the sandbox cell's default-drop egress is unchanged. Anything a run needs
   from the network (dependencies, browsers, fonts) is baked into the image at
   build time on the Mac.
3. **One entry point on the server.** The Mac reaches the cell only through
   `scripts/argus-dev-sandbox`, a root helper with exact-word sudo entries whose
   parameters arrive on stdin. Nobody gets the sandbox Docker socket, `docker`
   or `runuser`.
4. **Previews are tailnet-only.** Two fixed slots map tailnet HTTPS ports 8460
   and 8461 to unix sockets. Never Funnel, Cloudflare or a published port.
5. **No real secrets.** Requests carry dev-only placeholder values. Production
   and staging credentials never go into a dev image, `argus-dev.json` or a
   request.
6. **Only the sandbox cell.** Dev runs never touch the staging cell
   (personal-sandbox), the prod cell (personal-managed), the rootful daemon or a staging or production workload.
   Dev image IDs are never pinned in a reviewed `compose.yml`: staging takes
   images only from `argus release pin` (GHCR digests through
   `argus-image-import`).

## Per-repo setup

Copy [`templates/dev-env/argus-dev.json`](../templates/dev-env/argus-dev.json)
and [`templates/dev-env/Dockerfile.dev`](../templates/dev-env/Dockerfile.dev) to
the project root, and add `argus-dev.json` to Git.

| Field | Meaning |
| --- | --- |
| `project` | `[a-z][a-z0-9-]{0,30}`; images are `argus-dev/<project>:<tag>` |
| `build.context`, `build.dockerfile`, `build.target` | what `docker build --platform linux/amd64` builds on the Mac |
| `test.command`, `test.env`, `test.user`, `test.tmpfs`, `test.timeoutSeconds` | the test container (timeout at most 7200 s, default 1800) |
| `preview.command`, `preview.env`, `preview.port` | the dev server; it must listen on `127.0.0.1:<port>` or `0.0.0.0:<port>` |
| `services[]` | up to four helper containers (`name`, `image`, `command`, `env`, `user`, `tmpfs`) |

A service `image` is either another `argus-dev/<project>:<tag>` or the
`sha256:` ID of a public Postgres image already imported into the sandbox cell
(the ID `argus-image-import` printed, for example for kadath-staging). Other
image IDs, including staging workload images, are refused. The first service owns the
run's network namespace and every other container joins it, so they talk over
`127.0.0.1`. Containers start in order, but nothing waits for readiness. The
test command must wait for its database itself, for example with a short retry
loop in the test setup.

Tests write reports to `/out` in the test container (the template creates it).
`argus-dev test` copies `/out` back to `~/.cache/argus-dev/<project>/<run>/`.

## Commands

All run on the Mac from the project directory. They use `ssh $ARGUS_SSH_HOST`
(default `oreochiserver`) and `$ARGUS_REMOTE_REPO/scripts/argus-dev-sandbox`
(default `/srv/argus`; set `/opt/argus/current` once the root-owned release and
sudo narrowing from #412 are live, because the sudoers entries point there).

```bash
argus-dev test                         # build, ship, run test.command, stream output, fetch /out, exit with its code
argus-dev test -- pnpm vitest run a.ts # override the command for one run
argus-dev test --reuse 20261121t100000z  # rerun an image already loaded (no build, no upload)
argus-dev preview --slot 1             # build, ship, serve on tailnet port 8460 (slot 2: 8461) for 12 hours
argus-dev logs <run>                   # last 500 lines of a run's main container
argus-dev results <run>                # fetch /out again
argus-dev stop --slot 1 | --run <run>
argus-dev status | gc | purge
```

`scripts/argus-dev` lives in the Argus checkout; put that `scripts/`
directory on your `PATH` or call it by path.

Each load ships the whole image over ssh, so the edit loop is
"edit → `argus-dev test`" with a rebuild each time. Keep `Dockerfile.dev`
ordered so that dependency layers cache on the Mac. There is no hot reload in
the sandbox. A preview shows the build it was started from, and running
`argus-dev preview` again replaces it.

Exit codes follow Argus: 0 success, 1 failure, 2 invalid request, 3 refused
(not root, slot not prepared, image missing), 4 unavailable. `test` exits with
the test container's own code, or 124 on timeout.

## One-time server setup (operator, root shell)

Run these yourself on `oreochiserver`, after this PR is merged and pulled. They
mirror the nodens-staging ingress setup in
[`ARGUS_M5_WORKLOAD_CUTOVER.md`](ARGUS_M5_WORKLOAD_CUTOVER.md).

```bash
install -d -m 0700 -o argus-work-sandbox -g argus-work-sandbox /var/lib/argus/sandbox-ingress/dev-1
install -d -m 0700 -o argus-work-sandbox -g argus-work-sandbox /var/lib/argus/sandbox-ingress/dev-2
tailscale serve --bg --https=8460 unix:/var/lib/argus/sandbox-ingress/dev-1/upstream.sock
tailscale serve --bg --https=8461 unix:/var/lib/argus/sandbox-ingress/dev-2/upstream.sock
tailscale serve status    # 8460 and 8461 added, tailnet only
tailscale funnel status   # must be empty
```

The preview ingress uses the Caddy image ID pinned for nodens-staging (in
`scripts/argus-dev-sandbox`); import that same image once into the sandbox cell
the way it was imported for staging. Database services need their image
imported once with `argus-image-import --domain work-sandbox`.

Moving from D029's personal-sandbox setup (D030 phase 3): run `argus-dev purge`
first, then `chown argus-work-sandbox:argus-work-sandbox` the two slot
directories. The `tailscale serve` routes keep their paths and need no change.
Then re-render and install the sudoers drop-in as in
[`RUNBOOKS/sudo-narrowing.md`](RUNBOOKS/sudo-narrowing.md). Until that runbook
is applied, the operator's existing blanket grant covers the helper. A smoke
test from the Mac with any project:

```bash
argus-dev status                       # {"ok": true, "containers": []}
argus-dev test -- sh -c 'echo ok > /out/ok.txt'
```

## Interaction with the cell's other tooling

- **Firewall.** Discovery in `argus_sandbox_firewall.py` skips a running
  container only when it carries `argus.dev=1`, has no Compose label, is
  unprivileged with no host namespaces and no added capability beyond
  `NET_BIND_SERVICE`, and has network mode `none` or the netns of one running
  dev container that is itself `none`. Every other unlabelled container still
  fails closed, so plan, verify, cutover and drift checks keep working while dev
  runs exist. The policy digest does not change.
- **Maintenance.** `argus-m5-rootless-gid-repair` and a sandbox bootstrap
  rollback count every container in the cell. Run `argus-dev purge` before
  either.
- **Disk.** Loads refuse when the cell's disk would keep less than 20 GiB free.
  `gc` runs before every `test` and `preview`. It removes stopped runs after 24
  hours, previews after 12 hours, and dev images no container uses.

## What this does not do

- No network egress for dev runs, ever. A test that needs the internet must
  fake it.
- No dev runs in any other trust domain, and no use of staging data.
- No layer-level transfer. A whole image is uploaded per load (see the shortcut
  note in `scripts/argus-dev`).
- No interactive shell or `exec` in a dev container.
