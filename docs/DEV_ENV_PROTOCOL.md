# Dev Environment Protocol

Every project's development environment runs in containers. The Mac needs only
OrbStack (Docker plus Linux machines); no language runtime, database or package
manager is installed on the host for project work. The production server,
`oreochiserver`, is rehearsed on a local OrbStack machine, `oreochiserver-sim`.

## Rules

1. **Both a devcontainer and a compose dev stack.** The devcontainer holds the
   toolchain (editor terminal, tests, linters). The compose dev stack runs the
   app and its dependencies with the source bind-mounted and hot reload, and
   starts with one command. Both use the same image.
2. **Loopback only.** Every published port binds `127.0.0.1`
   (`"127.0.0.1:3000:3000"`, never `"3000:3000"`). Ports come from the
   [port registry](#port-registry).
3. **No host build artefacts.** `node_modules`, package stores and build caches
   (`.next`, `.astro`, `dist` when it holds native output) live in named
   volumes. They are never shared with macOS, whose copies contain
   darwin-arm64 native binaries.
4. **Fixed compose project names.** Each dev compose file sets top-level
   `name:` so volumes never depend on the directory a command runs from.
5. **No real secrets in dev.** Dev stacks use placeholder values committed as
   such (`dev-only`) or values generated locally. Production secrets are never
   copied to a laptop, a dev stack or the server sim.
6. **CI parity.** CI runs the same install and test commands, in the same
   pinned image, that the devcontainer runs.

## Per-repo checklist

A repo is compliant when all of these hold:

- [ ] `.devcontainer/devcontainer.json` using the dev compose file's
      `workspace` service (start from
      [`templates/dev-env/devcontainer.jsonc`](../templates/dev-env/devcontainer.jsonc)).
- [ ] `compose.dev.yml` with app and dependencies, source bind-mounted, hot
      reload, and a fixed `name:` (start from
      [`templates/dev-env/compose.dev.yml`](../templates/dev-env/compose.dev.yml)).
- [ ] Every `ports:` entry starts with `127.0.0.1:` and matches a row in the
      port registry below. Production-style compose files follow the same rule.
- [ ] `node_modules`, package stores and build caches are named volumes.
- [ ] Images are pinned by digest, the same digest CI and the production
      Dockerfile use.
- [ ] README has a **Develop** section: the one command that starts the stack,
      how to open the devcontainer, how to run the tests, and the ports used.
- [ ] CI runs the same commands in the same image (install, lint, typecheck,
      test, build).
- [ ] No `.env` with real values is required; `.env.example` lists names only.

## Port registry

Host ports on the Mac. Add a row in the same PR that starts using a port, and
check this table for collisions first. Container-internal ports are not listed.

| Project | Service | Host port | Status |
|---|---|---|---|
| kadath | web (Next dev) | 3000 | compliant (`127.0.0.1`) |
| kadath | api | 3001 | compliant |
| kadath | postgres | 55432 | compliant; run with project name `kadath-local` |
| nodens | Astro dev server | 4321 | compliant (`127.0.0.1`), dev stack project `nodens` |
| nodens | production-style image (nginx) | 8082 | compliant; 8081 stays untouched |
| hastur | app | 4173 | **not compliant**: `compose.yml` publishes `${PORT:-4173}:4173` on every interface |
| yog-sothoth | postgres | 55499 | compliant |
| yog-sothoth | Caddy proxy | 443 | **not compliant**: binds every interface; change to `127.0.0.1:443:443` or another loopback port |
| locigraph | postgres | 55433 | set through `POSTGRES_PORT` in the local env; the compose default (5432) has no `127.0.0.1` and must get one |
| locigraph | redis | 56379 | set through `REDIS_PORT`; same fix as postgres |
| locigraph | backend | 8000 | **not compliant**: `8000:8000` binds every interface |
| locigraph | Caddy | 80 (`CADDY_PORT`) | **not compliant**: binds every interface on a default port; move to a loopback `3xxx`/`8xxx` port |
| argus (sim) | dashboard Caddy route | 8088 | inside `oreochiserver-sim`; OrbStack forwards it to Mac loopback |
| argus (sim) | control API | 8099 | inside `oreochiserver-sim`; loopback in the sim |
| template | `templates/dev-env` example postgres | 55400 | example only; pick a free port when copying |

Conventions for new rows: web apps `3xxx`/`4xxx`, Postgres `554xx`, Redis
`563xx`. Never reuse a default port (5432, 6379, 80, 443) on the Mac.

## Server simulation (`oreochiserver-sim`)

`oreochiserver-sim` is an OrbStack Linux machine that copies the server's base:
Ubuntu 26.04 on amd64 (Rosetta), user `oreo` UID 1000, `docker` GID 983,
`argus-control` GID 981, systemd, rootful plus per-trust-domain rootless
Docker, Caddy, and the Argus checkout at `/srv/argus`.
OrbStack's own default user is `simadmin`, so it never takes the name
`oreo`; `sim up` refuses to continue unless `oreo` came out as UID 1000.

What differs on purpose:

- It is created `--isolated`: no `/Users` mount and no macOS integration.
- Code arrives as a git bundle pushed with `orbctl push`. No Git or GitHub
  credentials exist inside it.
- Tailscale is a stub at `/usr/local/bin/tailscale`
  ([`infra/server-sim/tailscale-stub`](../infra/server-sim/tailscale-stub)):
  `status --json` answers, `serve status` and `funnel status` report no
  config (Funnel off), and `serve --bg` is a no-op. It never joins a tailnet.
- No Cloudflare, no DNS, no router changes.
- Every secret is generated inside the sim (`umask 077`, never printed) and
  marked by `/etc/argus/SIM-ONLY`.
- The hostname stays `oreochiserver-sim`. Live acceptance scripts that check
  the host take `ARGUS_EXPECTED_HOST=oreochiserver-sim`.
- OrbStack shares one kernel across machines and pauses them while the Mac
  sleeps, so timers fire late and kernel-level networking (nft inside netns,
  rootless Docker under Rosetta) may differ from the real host.

### Before the first run (you, once)

1. Keep OrbStack ports off your LAN. `sim` refuses to run until both are off:

   ```bash
   orbctl config set machines.expose_ports_to_lan false
   orbctl config set docker.expose_ports_to_lan false
   ```

2. Choose the ref to simulate. The default is the current branch. The alert,
   typed-health and backup-snapshot units (and `argus-release-install`,
   `argus-sudoers-render`) exist only on the wave2 tree, so pass that branch
   with `--ref` when you need them.

### Lifecycle

All commands run on the Mac from the Argus checkout. Each prints a `PLAN`
line before acting; anything that creates or deletes a machine needs `--yes`.
Re-running is safe: an existing machine is reused, an existing checkout is
moved to the new commit only when it is clean, and existing sim secrets are
kept.

```bash
infra/server-sim/sim status                 # machines and the LAN-exposure check
infra/server-sim/sim up --yes [--ref REF]   # create, wait for cloud-init, push, phase A, phase B
infra/server-sim/sim sync [--ref REF]       # push a new bundle and rerun phase A
infra/server-sim/sim phase-b [--from STEP]  # rerun the control-plane phase from a step
infra/server-sim/sim snapshot --yes         # clone to oreochiserver-sim-golden (copy-on-write)
infra/server-sim/sim reset --yes            # delete the sim, clone it back from golden, start it
infra/server-sim/sim down --yes [--golden]  # delete the sim (and golden)
```

Sizing defaults to 4 CPUs, 6G memory and a 64G disk; override with
`SIM_CPUS`, `SIM_MEMORY` and `SIM_DISK`. OrbStack's global memory cap
(`memory_mib`) must be at least as large.

### Provisioning phases

`up` creates the machine from
[`infra/server-sim/cloud-init.yaml`](../infra/server-sim/cloud-init.yaml),
which installs every package (Docker CE with the rootless extras, uidmap,
slirp4netns, fuse-overlayfs, nftables, Caddy, age, sqlite3,
python3, git, curl) and creates the fixed IDs. The Argus scripts themselves
never download anything.

[`infra/server-sim/provision`](../infra/server-sim/provision) runs as root
inside the sim and refuses on any other hostname.

- **Phase A (base):** checks the bundle out at `/srv/argus` (owned by `oreo`),
  installs the tailscale stub, then prints `PASS` or `FAIL` for every
  prerequisite: hostname, x86_64, systemd as PID 1, cgroup v2, the fixed UID
  and GIDs, group memberships, `/etc/ssl/private` mode, subordinate IDs,
  every required command, rootful Docker, Caddy, the stub and a clean
  checkout. It ends with `PREREQUISITES_PASS` or `PREREQUISITES_FAIL`.
- **Phase B (control plane):** reuses the repo's installers, each with
  `--preflight` before `--apply` and its acknowledge flag, in an order that
  satisfies every preflight on a fresh machine: `sysusers` → `secrets`
  (sim-only `control-token`, `operator-proxy-token`, `operators.json` with the
  fake owner `sim-owner@oreochiserver-sim.test`, and `runtime/argus/m5/agents`)
  → `dashboard` (generate) → `sandbox` (`argus-m5-sandbox-bootstrap` for
  personal-sandbox, work-sandbox and personal-managed) → `runtime-seed`
  (sim only) → `control-plane-seed` (sim only) → `ledger-worker` →
  `capability-issuer` → `caddy` (appends the reviewed route to the stock
  Caddyfile, sim only) → `session-boundary` → `control-plane-reconcile` →
  `units` (enables the domain agents, privileged-lifecycle agent and
  migration coordinator) → `collectors` → `workloads`. Phase B stops at the
  first failure and prints the `--from` step to resume with.

Why this differs from the server order. The server reached its control plane
one milestone at a time, and today's M5 installers are upgrade scripts whose
preflights expect that earlier state:

- The dashboard is generated before the ledger worker, because
  `argus-m5-runtime-permissions` (run by both M5 installers) refuses without
  the generated files. It is not its own step: it also refuses until
  `argus-worker` exists.
- `sandbox` runs before both M5 installers, which refuse without the
  `argus-<domain>` users (`docs/ARGUS_M5_SANDBOX_RUNTIMES.md` also applies the
  runtimes before the issuer).
- `runtime-seed` recreates operator state the server has from earlier
  milestones: the M1 writer's `state.sqlite3`, `audit.sqlite3` and an empty
  access journal (built through `argus_m1.access_writer()`, as the operator),
  `runtime/backups` (written by `argus-backup-run`, listed in every
  domain-agent unit's `ReadWritePaths`), and lingering for `oreo` (the
  server's `user@1000.service` runs user services, `docs/DISCOVERY.md`; the
  oreo schedules collector needs `/run/user/1000`).
- `control-plane-seed` breaks a real cycle. `argus-m5-ledger-worker` requires
  the work-sandbox `issuer.pub` and an active `argus-domain-agent@work-sandbox`
  (added in cf847c1, when the server already had both); that agent `Requires=`
  the issuer and worker units, which only the two installers install. The
  seed runs the installers' own commands once (the `argus-worker` and
  `argus-issuer` users, the Ed25519 key generated in place and never printed,
  its public half for each domain, the reviewed units, runtime permissions)
  and starts the work-sandbox agent. Both installers then run in full and
  re-verify every owner, mode, socket, schema and typed agent status.

Sim boundary settings, all sim only:

- The sandbox users get the server's UIDs (personal-sandbox 1002,
  work-sandbox 1003, personal-managed 1004, from
  `config/argus/observation-sources.json`). The collector installer refuses a
  rootless socket owned by any other UID.
- `/etc/systemd/user.conf.d/argus-sim-rootless.conf` sets
  `DOCKERD_ROOTLESS_ROOTLESSKIT_DETACH_NETNS=false` for every user manager in
  the VM. Only the three sandbox users run rootless dockerd there, so the
  setting changes nothing for oreo's manager. It is not scoped to
  `user@<uid>.service.d`, because the bootstrap owns those drop-in directories
  and rolls them back. Docker 29's `dockerd-rootless.sh` defaults to detach
  mode. That mode is a security gap, not only a flaky check. In detach mode,
  dockerd and the RootlessKit child stay in the child's network namespace, but
  containers run in a separate one at `$ROOTLESSKIT_STATE_DIR/netns`. The
  bootstrap's firewall helper loads the nftables policy with
  `nsenter -t <child>`. When its host-namespace check passes, the policy
  lands in a namespace the containers do not use, and the containers get no
  egress filtering. The sim's classic mode makes the sim's egress policy hold.
  It proves nothing about the server, whose Docker 29.5.3 mode is unknown.

Read-only check for the server (run it there yourself; the sim tooling never
connects to it). It prints `detach` for any sandbox RootlessKit started in
detach mode:

```sh
for p in $(pgrep -x rootlesskit); do
  printf '%s ' "$(stat -c %U /proc/$p)"
  tr '\0' ' ' </proc/$p/cmdline | grep -q -- --detach-netns && echo detach || echo classic
done
```

If the server prints `detach`, fix it in the bootstrap. Either pin
`DOCKERD_ROOTLESS_ROOTLESSKIT_DETACH_NETNS=false` in the daemon unit it writes,
or make the firewall helper refuse a child started with `--detach-netns`. The
sim prints `classic` for all six processes.

The `workloads` step stops with `GHCR_LOGIN_REQUIRED` until root's Docker is
logged in to `ghcr.io`. Doing that is yours alone:

1. On GitHub, create a classic token with only `read:packages`, for the sim.
2. `orbctl run -m oreochiserver-sim -u root bash`
3. `docker login ghcr.io -u <your-github-user> --password-stdin`, pasting the
   token on stdin. Never pass it as an argument, and never store it in a repo.
4. `infra/server-sim/sim phase-b --from workloads`

After that, import pinned images with `scripts/argus-image-import` and deploy
through the API. Smoke, alerting, typed health and backups follow
`docs/P5_SCHEDULED_SMOKE.md`, `docs/MONITORING.md`, `docs/OPERATIONS.md` and
`docs/BACKUP_AND_RESTORE.md`, with a throwaway age key for snapshots.
`ARGUS_EXPECTED_HOST=oreochiserver-sim argus-doctor --host --json` is
expected to fail in the sim with: no PostgreSQL 18; no tracked-file inventory
(root's git refuses the oreo-owned checkout); OrbStack's own
`/etc/sudoers.d/orbstack` (`ALL`); and every Argus unit whose `ExecStart`
lives in the oreo-owned `/srv/argus` checkout instead of a root-owned release
(`docs/RUNBOOKS/root-owned-release.md`). The GHCR credential shows as a
warning until you log in. Never run it with `--online`.

### Known limits

Two installer bugs on `integration/wave2` stop phase B before `workloads`.
They are real (the server would hit them on a re-run) and are left for a
wave2 fix, not worked around in the sim:

- `session-boundary`: `argus-m5-session-boundary` still demands session
  schema 3, but `scripts/argus_sessions.py` moved to `SCHEMA_VERSION = 4` in
  ffd83e3 (TOTP). The apply rolls back with "session database schema version
  is not 3". The check (and its `SESSION_SCHEMA_OK version=3` line and test)
  needs version 4.
- `control-plane-reconcile`: it sets `config/access.json` and
  `config/privacy.json` to `oreo` mode 0600, but the API runs as `argus-api`
  (group access) since c5b5069, and `argus-m5-runtime-permissions` wants
  `access.json` at 0664. Its own readiness curl then gets a 500
  (PermissionError on `privacy.json`), and it has no rollback, so restore both
  files from `/var/lib/argus/control-plane-backups/<ts>/config/` and rerun
  `argus-m5-runtime-permissions`.

To rehearse the rest until then: run the session-boundary apply from a copy
of the script with the version check set to 4, kept outside `/srv/argus`,
then `infra/server-sim/sim phase-b --from units`. With that, `units` and
`collectors` pass and phase B stops at `workloads` as intended.

Other known limits:

- `personal-managed` takes over work-sandbox's helpers. Wave2's
  `argus-m4-personal-sandbox-bootstrap` sets one `HELPER_PREFIX`
  (`argus-work-sandbox`) for every domain except personal-sandbox. After
  phase B, `/usr/local/lib/argus/argus-work-sandbox-{netns,firewall}`
  hard-code personal-managed: its user, its netns, its nft files and its
  host-guard table. The namespace and firewall units of both domains run
  those same files. Restarting `argus-work-sandbox-namespace.service` runs
  `remove` against personal-managed, which deletes its netns and host-guard
  table. Restarting `argus-work-sandbox-firewall.service` firewalls
  personal-managed's dockerd and exits 0. Work-sandbox's own policy is never
  re-applied or checked, but the unit still reports success. This fails open
  and does not show up as a failed unit. **In the sim, do not restart either
  work-sandbox sandbox unit, and do not reboot the VM.** The fix belongs in
  integration/wave2's bootstrap, not in the sim: give each domain its own
  `HELPER_PREFIX`, for example `argus-${CELL_DOMAIN}`.
- Root's `git -C /srv/argus` prints "dubious ownership" (the checkout is
  oreo's), so the installers' `commit=` fields are empty. Cosmetic.
- Rosetta makes phase B slow: each sandbox takes about 100 s and the
  collector deploy about 5 minutes (a failed one rolls back for 15).

### Safety rules

- **`ARGUS_SSH_HOST=oreochiserver-sim` must be set** for every Mac-side tool
  run against the sim (`argus release pin`, `argus promote`, the alert poller,
  `argus-backup-pull` via `ARGUS_PULL_SOURCE=oreochiserver-sim:/var/backups/argus-snapshots-pull/`).
  Their default is the real `oreochiserver`. Set it per command or per shell,
  never in a global profile. The alias needs an ssh config entry: copy the
  `Host orb` block from `~/.orbstack/ssh/config`, rename it
  `oreochiserver-sim`, set `User oreo@oreochiserver-sim`, and check that
  `ssh oreochiserver-sim hostname` prints `oreochiserver-sim`.
- **Never reuse production secrets.** Nothing from `oreochiserver:/etc/argus`
  or GitHub Actions secrets goes into the sim, and nothing from the sim goes
  to the server.
- **The GHCR token is user-created and read-only** (`read:packages`), entered
  by you on stdin inside the sim, and revoked when the sim is deleted.
- **OrbStack LAN exposure stays off** (`machines.expose_ports_to_lan` and
  `docker.expose_ports_to_lan` both `false`); `sim` checks this every time.
- Live acceptance in the sim runs with `ARGUS_EXPECTED_HOST=oreochiserver-sim`;
  without it the scripts still demand `oreochiserver`.
- Never enable Funnel, Cloudflare tunnels or DNS for the sim.
