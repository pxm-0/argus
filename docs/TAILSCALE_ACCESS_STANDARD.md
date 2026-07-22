# Tailscale Access Standard

One pattern for putting an Argus workload on the tailnet. `nodens` is the
reference implementation; every other tailnet workload conforms to this.

## The standard

A workload is "on the tailnet" when, and only when, all four hold:

1. **App binds to `127.0.0.1` only.** No `0.0.0.0` / wildcard host binds. For
   Docker Compose this means published ports are `127.0.0.1:<port>:<port>`, not
   `<port>:<port>`.
2. **Tailscale Serve terminates tailnet-only HTTPS.** Never Funnel. Funnel is
   public and is forbidden in this project.
3. **Canonical URL is the MagicDNS FQDN on a per-workload HTTPS port:**
   `https://oreochiserver.tail0a3a58.ts.net:<port>`.
4. **`effective` access is promoted to `tailnet` only with on-server evidence**
   (see the rollout runbook). The tracked config declares the intent; the
   evidence proves the reality.

### Config representation

- `config/routes.json` → `workloadRoutes.<id>.tailnet`:
  `{ "enabled": true, "mode": "tailscale-serve", "url": "https://oreochiserver.tail0a3a58.ts.net:<port>" }`
- `config/access.json` → `workloads.<id>`:
  `urls.tailnet` = the same FQDN URL; `effective` stays `local` until the
  evidence checklist passes, then flips to `tailnet` with `lastAppliedAt` set
  and `lastError` cleared.

### Port allocation

Distinct HTTPS ports per workload (apps assume they own `/`, so path-prefix
serving is avoided). `8443` is nodens' existing live port.

| workload    | local target      | tailnet HTTPS port | canonical URL                                   |
| ----------- | ----------------- | ------------------ | ----------------------------------------------- |
| nodens      | `127.0.0.1:3000`  | `8443` (live)      | `https://oreochiserver.tail0a3a58.ts.net:8443`  |
| intake-os   | `127.0.0.1:8080`  | `8444`             | `https://oreochiserver.tail0a3a58.ts.net:8444`  |
| hastur      | `127.0.0.1:4173`  | `8445`             | `https://oreochiserver.tail0a3a58.ts.net:8445`  |
| uptime-kuma | `127.0.0.1:54321` | `8446`             | `https://oreochiserver.tail0a3a58.ts.net:8446`  |
| review-ui   | `127.0.0.1:8765`  | `8447`             | `https://oreochiserver.tail0a3a58.ts.net:8447`  |

Prerequisite: MagicDNS + HTTPS certificates must be enabled for the tailnet
(already provisioned — nodens serves HTTPS today).

## Rollout runbook

All steps run on `oreochiserver`. This repo change is **plan-only**: no serve
config is applied and no `effective` state is promoted here. Each promotion
lands as its own PR with the evidence below attached, per
[PR_WORKFLOW.md](PR_WORKFLOW.md).

Workload source (compose files) is **not** committed to this repo. Rebinds are
made in each workload's own source on the server; this runbook only records
what must change.

### Serve command (template — verify on server)

```bash
# Verify exact flag form first; `tailscale serve` syntax varies across versions.
tailscale serve --help
sudo tailscale serve --bg --https=<PORT> 127.0.0.1:<LOCAL_PORT>
```

`--bg` persists the mapping. Confirm afterward with `tailscale serve status`.

### Evidence checklist (gates the `effective` → `tailnet` flip)

Run per workload; attach output to the PR:

1. `ss -tulpen | grep <LOCAL_PORT>` shows `127.0.0.1:<port>` only — no `0.0.0.0`.
2. `tailscale serve status` maps `…:<PORT>` → `127.0.0.1:<LOCAL_PORT>`.
3. `tailscale funnel status` shows Funnel **off** (no funnel config).
4. From another tailnet device:
   `curl -sS -o /dev/null -w '%{http_code}' https://oreochiserver.tail0a3a58.ts.net:<PORT>`
   returns the workload's expected status.
5. `scripts/argus-access-reconcile` clean and `scripts/argus-doctor` ok.
6. Set `access.json` `effective: "tailnet"`, `lastAppliedAt`, clear `lastError`.

### Per-workload plan

| workload    | class      | remaining work                                                                 | approval gate |
| ----------- | ---------- | ------------------------------------------------------------------------------ | ------------- |
| review-ui   | internal   | **Serve-only** — already `127.0.0.1:8765`. Add serve `8447 → 127.0.0.1:8765`.  | none          |
| intake-os   | sensitive  | Rebind `0.0.0.0:3000 → 127.0.0.1`; confirm front-door port (Caddy 8080 vs app 3000); serve `8444 → 127.0.0.1:8080`. | operator sign-off (manifest: no promotion without approval) |
| hastur      | sensitive  | Rebind `0.0.0.0:4173 → 127.0.0.1`; serve `8445 → 127.0.0.1:4173`.              | operator sign-off (SSH/auth data) |
| uptime-kuma | restricted | Rebind `0.0.0.0:54321 → 127.0.0.1`; serve `8446 → 127.0.0.1:54321`.            | operator sign-off (restricted admin dashboard) |

Suggested order: **review-ui first** (no rebind, lowest risk) to prove the
standard end-to-end, then the rebind-first workloads once approved.

### Out of scope

- **locigraph** — tailnet-*eligible* (`accessCompatibility: tailnet`) but desired
  access is `none`. Backend (`0.0.0.0:8000`) and Caddy (`0.0.0.0:8090`) are
  wildcard-bound, and Postgres (`15432`) and Redis (`16379`) are host-exposed.
  It must be bind-remediated and re-classified `none → tailnet` before it enters
  this standard.
- **dozzle** (`local`), **hello-nginx** (`cloudflare-protected`, plan-only) — not
  tailnet workloads.

## References

- Tailscale Serve: https://tailscale.com/docs/features/tailscale-serve
- [CONFIG_MODEL.md](CONFIG_MODEL.md) — config file shapes
- [ACCESS_RECONCILE.md](ACCESS_RECONCILE.md) — desired/effective reconciliation
