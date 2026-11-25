# Dev runs in personal-sandbox: threat model and rollback

Decision: [D029](ARGUS_V1_DECISIONS.md). Protocol:
[`DEV_ENV_PROTOCOL.md`](DEV_ENV_PROTOCOL.md). Like the D027 document, this one
describes controls and failure modes, not live weaknesses.

## What changes at the sandbox boundary

Before D029, images entered personal-sandbox only through `argus-image-import`,
which pulls allowlisted registry digests, and every running container had to
belong to a reviewed Compose project. D029 adds three things:

1. A second way in for images. `argus-dev-sandbox load` accepts an operator-built
   `docker save` archive, but only for one `argus-dev/<project>:<tag>` image, with
   no identity labels.
2. A class of container outside Compose. Dev containers carry `argus.dev=1`, have
   no network interface beyond loopback, and are ignored by firewall discovery
   only while they keep that shape.
3. Two tailnet-only preview routes, `:8460` and `:8461`, each mapped to a unix
   socket in a dev slot directory owned by the sandbox user.

What stays the same: default-drop egress and the host egress guard, the
disabled port driver, the private socket, onboarding and typed deploys for
staging, and the allowlist for every image that staging or production deploys.

## Assets and actors

- **Assets:** the staging workloads that share the cell (nodens-staging,
  kadath-staging) and their server-local secrets, the other trust domains, the
  host, and the tailnet.
- **Untrusted input:** everything inside a dev image. It holds third-party
  packages, and a compromised dependency is the expected attacker.
- **Trusted:** the operator on the Mac, the reviewed helper in the root-owned
  release, and the Docker and RootlessKit runtime.

## Threats and controls

| Threat | Control |
| --- | --- |
| Dev code exfiltrates data or calls out | No interface but loopback: `--network none`, or another container's netns that is itself `none`. Egress policy, host guard and resolver rules are untouched. The firewall carve-out re-checks that shape on every discovery, so a dev container with a real network fails closed like any other unknown container. |
| A dev image impersonates a staging container | Docker copies image labels onto containers. Loads refuse images with `com.docker.compose.*`, `argus.*`, `com.argus.*` or `dev.argus.*` labels. Firewall discovery does not skip a container that carries both `argus.dev` and a Compose label: it fails closed like any other unknown container. Service containers may use only `argus-dev/<project>` images or an imported public Postgres image, never a staging workload's image. |
| The helper is steered at a staging container (`cp`, `logs`, `rm`) | Run IDs are validated. Every container is found by the `argus.dev=1` label plus a run or slot label, then addressed by its full 64-hex ID. Names and ID prefixes are never taken from a request. |
| The archive smuggles extra images or names | Only `manifest.json`, `index.json` and `repositories` are read; nothing is extracted as root. All three must name the single `argus-dev/<project>:<tag>`. After `docker load`, every `Loaded image` line must equal that reference. Otherwise the load is refused, and any `argus-dev` names or untagged IDs it produced are removed. Names outside `argus-dev/` cannot move a staging pin, because pins are image IDs. |
| A request widens the container (privileged, mounts, host namespaces, ports, capabilities) | Requests are strict JSON with a closed field set: command, env, user, tmpfs, services, timeout, port, slot. The helper builds every `docker run` option itself: `--cap-drop ALL`, `no-new-privileges`, pids, memory and CPU limits, no mounts, no ports. Only the preview Caddy keeps `NET_BIND_SERVICE`, `--read-only`, and one bind of its slot directory. |
| Sudo becomes a root shell | Exact-word entries for the helper in the root-owned release. Every parameter is read from stdin and validated. Docker runs as `argus-personal-sandbox` through `runuser`. The helper writes only an unlinked temp spool as root and passes no path from a request to the filesystem. |
| Dev app reconfigures its preview ingress | The Caddy sidecar shares the app's netns, so its admin endpoint is disabled in the config. |
| Preview reaches beyond the tailnet | `tailscale serve` to unix sockets, set once by hand. Funnel stays off and is checked. No Cloudflare route, no listener on the host. |
| Results attack the Mac | The `/out` tar is capped at 1 GiB and extracted with Python's `data` filter (no absolute paths, no links out, no devices) into `~/.cache/argus-dev/`. |
| Disk or memory exhaustion hurts staging | Load size is capped at 8 GiB and refused below 20 GiB free. Each container is limited to 4 GiB of memory, 2 CPUs and 1024 pids. Stopped runs are removed after 24 hours and previews after 12. `gc` runs before every run and never removes the images that run needs. |
| Container escape from a dev run | Rootless Docker maps an escape to `argus-personal-sandbox` and no further: the user is sealed by the host egress guard and owns nothing outside the cell. See the residual risks. |
| Dev image promoted to staging by mistake | Staging pins come from `argus release pin` (GHCR digest through `argus-image-import`), and review of the pin PR shows the registry reference next to the ID. `gc` removes dev images no container uses. |

## Residual risks

Since D030 phase 3, dev runs live in their own sandbox cell (`work-sandbox`),
so the shared-daemon risk below and the carve-out in the staging cell are gone;
the rest of this document still applies, with the sandbox cell in place of
personal-sandbox.

- **Shared daemon with staging.** A container escape from a dev run, not just a
  dev-image bug, would control the staging workloads in personal-sandbox, their
  staging secrets, and their tailnet ingress sockets. It would still have no
  egress and no reach into other domains. Accepted for the first version,
  because personal-sandbox is already the domain for untrusted code and holds
  no production data. The trigger to revisit is any staging workload that holds
  data or credentials worth more than its rebuild cost. The fix then is a
  separate `personal-dev` cell built by the same bootstrap; that also removes
  the firewall carve-out.
  [D030](ARGUS_V1_DECISIONS.md) schedules that fix: dev runs move to the
  reused `work-sandbox` cell (role sandbox) in phase 3 of
  [`TRUST_SPLITS.md`](TRUST_SPLITS.md).
- **Writable container layers** have no disk quota under rootless overlay.
  Memory limits cap tmpfs, but a test that writes to its root filesystem can
  still grow until `gc` removes it.
- **Expiry runs only when the helper runs.** No timer enforces it, so a forgotten
  preview stays up on the tailnet until the next `argus-dev` call or `stop`.
- **The firewall carve-out trusts Docker's inspect data.** It does not enter the
  namespace to list links.
- Until sudo narrowing (#412) is applied, the operator's blanket sudo is broader
  than anything here.

## Rollback

Each step stands alone:

1. `argus-dev purge` removes every dev container and image.
2. `tailscale serve --https=8460 off` and `--https=8461 off`; remove
   `/var/lib/argus/sandbox-ingress/dev-*`.
3. Revert this PR: the helper, the sudoers entries, and the firewall carve-out.
   After it, a leftover dev container makes firewall discovery fail closed, so
   purge first.
