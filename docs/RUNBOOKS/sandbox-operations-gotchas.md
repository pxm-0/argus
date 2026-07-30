# Sandbox operations gotchas

Traps discovered operating the M5 sandboxed workloads, mostly during the
2026-07-30 personal-sandbox outage and recovery. Kept here instead of a
scratch handoff file because nodens and yog-sothoth will hit the same sandbox
machinery.

- **`sudo ls /path/*/` on a 0700 root dir returns "No such file or
  directory."** The glob is expanded by the *unprivileged shell*, not sudo.
  Looked like missing backups twice. Use `sudo find ... -printf` instead.
- **`docker exec` is not `docker compose exec`.** No `-T` flag (exit 125), and
  stdin is `/dev/null` without `-i`.
- **`--refresh` waits 0.0s for the global lock; `--reconcile` waits 60s.**
  Four timers on 60s cycles make collisions likely. Quiesce timers before
  refreshing.
- **`compose up -d <svc>` follows `depends_on`.** Need `--no-deps` to isolate
  one service.
- **`argus-m5-sandbox-bootstrap --apply` reports `daemonRestarted=false`
  even when it rewrote the unit.** It does not restart an already-active
  daemon. `--dns`-style config changes do not take effect without one.
- **`--reconcile` reuses the frozen accepted compose byte-for-byte.** It
  cannot deliver spec changes — that's what `--refresh` is for.
- **`prepare_ingress_start` requires a root-owned ingress dir and leaves it
  sandbox-owned.** Calling it twice raises `"locked ingress directory
  ownership is unsafe"`.
- **Cron/timer resurrection detection only catches invocations it
  recognizes.** It started as `docker compose` + `up|start|restart` only,
  missing plain `docker exec` against a legacy container (how hastur's
  orphan hid for ~13h). Widened, but treat this as a class of check that
  needs revisiting whenever a new invocation shape shows up, not a solved
  problem.
- **`argus-pilot-rootless-docker.service` is a red herring.** That's the M2
  pilot, `/var/lib/argus/pilot/`. The sandbox daemons are *user* units:
  `~argus-<domain>/.config/systemd/user/argus-<domain>-rootless-docker.service`.
- **A sealed sandbox's default-deny egress has no route to Docker Hub.** A
  smoke test that does `docker run <public-image>` will fail even on a
  perfectly healthy daemon — confirmed live 2026-07-31. Vendor and
  `docker load` any verification image instead of pulling it.
- **Full test suite hangs on macOS.** Run individual files; CI runs the
  suite.
- **After any workload migration, audit user crontabs, `/etc/cron.d`, system
  timers, and every per-user `systemctl --user` timer.** A system-level sweep
  cannot see user-level units; two schedules were missed at M5 cutover this
  way.
- **A personal-sandbox rebuild wipes the shared ingress (caddy) sidecar
  image, and nothing reprovisions it.** Every workload's `ingress_image` in
  `argus-m5-workload-cutover` is a locally-loaded image ID with no script
  behind it. After a wipe, `cutover --preflight` fails on `image inspect` for
  that digest. Fix: `docker pull caddy:2` + `docker save` on the host, `docker
  load` into the sandbox daemon, then update every `ingress_image` in SPECS
  to the new local ID.
- **A restaged legacy source's `docker compose up -d` can silently create a
  brand-new project with empty volumes instead of reattaching the original
  data**, if the compose invocation doesn't pin the same project name the
  original deployment used (`-p <name>`, not derived from the current
  directory). Check `docker volume ls` for the *expected* volume name before
  trusting a fresh `up -d` — an unexpected new volume means it built an empty
  database next to the real one, not on top of it.
- **A workload's own health check (staged before cutover) can point at its
  own post-cutover tailnet route.** After a full sandbox wipe, that route is
  dead (proxying a socket that no longer exists), so the check can never pass
  — a bootstrapping deadlock. Fix: temporarily `tailscale serve --bg
  --https=<port> http://127.0.0.1:<legacy-port>` to point the route straight
  at the legacy container until cutover completes and repoints it itself.
- **`tailscale serve <target>` without `--bg` blocks in the foreground
  watching the config, and killing the wrapping SSH command does not
  reliably kill it server-side** — it can keep running orphaned. Always pass
  `--bg` for a scripted/non-interactive `tailscale serve` add.
