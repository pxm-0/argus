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
- **Phase B (control plane):** reuses the repo's installers in the server
  provisioning order, each with `--preflight` before `--apply` and its
  acknowledge flag: `sysusers` → `secrets` (sim-only `control-token`,
  `operator-proxy-token`, `operators.json` with the fake owner
  `sim-owner@sim.invalid`, and `runtime/argus/m5/agents`) → `dashboard`
  (generate) → `ledger-worker` → `capability-issuer` → `sandbox`
  (`argus-m5-sandbox-bootstrap` for personal-sandbox, work-sandbox and
  personal-managed) → `caddy` (appends the reviewed route to the stock
  Caddyfile, sim only) → `session-boundary` → `control-plane-reconcile` →
  `units` (enables the domain agents, privileged-lifecycle agent and
  migration coordinator) → `collectors` → `workloads`. Two changes from the
  server order, both forced by a fresh machine: the dashboard is generated
  before the ledger worker, and `argus-m5-runtime-permissions` is not its own
  step. That script refuses without the generated dashboard files and the
  `argus-worker` user, and the ledger-worker and capability-issuer installers
  already run it. Phase B stops at the first failure and prints the `--from`
  step to resume with.

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
`argus-doctor --host` is expected to fail its PostgreSQL and GHCR-credential
checks in the sim; never run it with `--online`.

Known gap: on a fresh machine the M5 installers' preflights depend on each
other (the ledger worker wants the work-sandbox issuer key and agent; the
capability issuer wants the ledger and an active worker), because the real
server reached its state incrementally. Phase B will stop at the first such
preflight and say which one; the fix belongs in the installers, not in the
sim.

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
