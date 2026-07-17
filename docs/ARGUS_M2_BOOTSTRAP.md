# Argus M2 Disposable Pilot Bootstrap

The root-owned M2 bootstrap is constrained to the argus-pilot disposable
identity in personal-sandbox-pilot. Its fixed contract requires subordinate
IDs, user lingering, separate storage, rootless systemd, a network namespace,
and default-deny firewall policy. It prohibits host networking, host-path
mounts, Docker sockets, published ports, public routes, and cross-domain routes.

Before an apply implementation is accepted, it must back up changed
configuration and produce isolation, restart, reboot, and rollback evidence.
The current command only emits the reviewable contract; it does not mutate the
host.
