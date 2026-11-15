# nodens public route: threat model and rollback

Decision: [D027](ARGUS_V1_DECISIONS.md). This document is public, so it describes
controls and failure modes in general terms only: no addresses, ports, paths,
credentials or live weaknesses.

## What becomes public

- `https://nodens.dev`: the `nodens-production` static website (prebuilt HTML,
  CSS and assets served by a web server in a sealed container).
- `https://www.nodens.dev`: a redirect to the apex, configured at Cloudflare.

Nothing else. `nodens-staging`, the Argus dashboard, the control API, other
workloads and the host stay reachable only on the tailnet.

## Path of a request

```text
visitor -> Cloudflare edge (TLS, optional Access) -> named tunnel (outbound from the host)
        -> cloudflared on the host -> the workload's existing private ingress -> static site
```

No inbound port is opened on the host or the router. The tunnel connector runs as
a dedicated unprivileged service account that can reach only the production
ingress for this workload.

## Threats and controls

| Threat | Control |
| --- | --- |
| Over-exposure: another host or workload becomes reachable through the tunnel | The tunnel ingress names exactly the allowlisted hostnames and ends in an `http_status:404` catch-all. It is validated before every reload. doctor and smoke fail if the ingress names a hostname outside the allowlist or if the connector runs while the provider is disabled. |
| Gate weakening spreads to other workloads | Policy, doctor, reconcile and smoke allow `cloudflare-public` only for allowlist entries (workload and hostname), with tests for both the allowed and the denied branch. Onboarding defaults stay deny-by-default. |
| Tunnel credential theft lets someone else serve as the tunnel | Credentials are kept on the server only, root- or connector-owned with mode 0600, never in Git or chat. If exposure is suspected: delete the tunnel at Cloudflare, create a new one and update the DNS route. |
| Connector compromise reaches other services | The connector has no shell login, no docker or sudo access, and filesystem traverse rights only to the single production ingress. It cannot reach other workloads' ingresses or the control plane. |
| Origin attacked directly, bypassing Cloudflare | There is no inbound listener, so the origin is reachable only through the tunnel or the tailnet. |
| Abuse or volumetric load | The site is static and served through Cloudflare's cache and DDoS protection. The workload has no write endpoints or accounts. |
| Wrong build published | The production image is digest-pinned in Git. Promotion requires a succeeded staging deploy of the same image, and the activation records which digest is live. |
| Silent outage after an ingress rebuild | A public health probe of `https://nodens.dev/healthz` runs next to the tailnet probe and feeds the existing alerting. |
| Staged rollout skipped | Activation requires the protected stage (401/403 without an Access session, 200 with one) to be recorded before `cloudflare-public` can be applied. |

Residual risks:
- The public site is only as safe as its static content. A future change that adds server-side behaviour needs a new review under D027 or a successor decision.
- Cloudflare is a trusted third party for TLS and request handling.

## Rollout stages

1. **Prepared:** the gates know the allowlist, the provider is still off and no tunnel exists. All checks are green.
2. **Protected:** the tunnel is live and `nodens.dev` sits behind Cloudflare Access limited to the operator. The probes and checks are recorded as activation evidence.
3. **Public:** the Access application is removed, and the probe answers 200 without authentication. The effective state becomes `cloudflare-public`.

## Rollback

From any stage, in order. Each step alone stops public traffic:

1. Remove the `nodens.dev` and `www.nodens.dev` ingress rules (leaving only the catch-all), validate, and reload the connector. Or stop the connector service entirely.
2. Set the workload's effective access back to `tailnet` and record an audit event.
3. Optionally remove the proxied DNS records and delete the tunnel at Cloudflare.
4. Disable the provider in the exposure config, and revert the allowlist and route changes through a pull request.

The tailnet route on the production workload is not touched at any stage, so the
operator keeps access throughout.
