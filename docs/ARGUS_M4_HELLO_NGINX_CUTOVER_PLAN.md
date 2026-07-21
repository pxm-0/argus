# Argus M4 hello-nginx Cutover Plan

This command follows the passing M4 preflight. It only renders and inspects the
currently running Compose definition, creates opaque fingerprints, and checks
that the sandbox is still empty. It cannot move, import, start, stop, mount, or
expose a workload.

Run it only on `oreochiserver`:

```bash
cd /srv/oreo-cloud
sudo python3 scripts/argus-m4-hello-nginx-cutover-plan
```

It rejects the pilot before cutover implementation if its Compose file has more
than the `web` service, a target-side build, a wildcard/non-loopback port
mapping, a volume or bind mount, host networking, privileged capabilities,
devices, or a Docker API socket. A source loopback-only health mapping is
accepted solely so the later target generator can remove it. Its private result is written to
`runtime/argus/m4/hello-nginx-cutover-plan.json` and must still say
`cutoverApproved: false`.

The next PR, if this plan passes review, must perform an explicit image import
and a one-way, fenced cutover with an equally explicit rollback. It must retain
no published port or public route in the personal-sandbox target.
