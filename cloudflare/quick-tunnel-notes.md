# Quick Tunnel Notes

Quick Tunnel is disabled for P0.

Reasons:

- quick tunnels create public ingress without the named-tunnel review path
- URLs are ephemeral and easy to lose track of
- Cloudflare Access policy enforcement is not part of this P0 phase

Future use requires an explicit phase that:

- records the reason for temporary exposure
- requires an operator confirmation phrase
- refuses dashboard, control API, database, and Docker-socket targets
- writes an audit event
- tears the tunnel down after the planned window
