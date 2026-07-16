# Argus M2 Pilot Preflight

Run this read-only command on oreochiserver before provisioning any rootless
runtime cell:

    scripts/argus-m2-pilot-preflight --user <pilot-user>

It emits only boolean prerequisite results: subordinate-ID allocation, rootless
tooling, user lingering, cgroup v2, a usable storage driver, and namespace
tooling. A nonzero status means the disposable pilot must not proceed. It
creates no user, service, network, firewall rule, runtime socket, or public
route.
