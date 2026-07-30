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
