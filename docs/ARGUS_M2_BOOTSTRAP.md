# Argus M2 Disposable Pilot Bootstrap

The root-owned M2 bootstrap is constrained to the argus-pilot disposable
identity in personal-sandbox-pilot. Its fixed contract requires subordinate
IDs, user lingering, separate storage, rootless systemd, a network namespace,
and default-deny firewall policy. It prohibits host networking, host-path
mounts, Docker sockets, published ports, public routes, and cross-domain routes.

The bootstrap command defaults to a non-mutating plan:

    sudo ./scripts/argus-m2-bootstrap --plan

After reviewing that plan, the host administrator can apply only the fixed,
disposable cell:

    sudo ./scripts/argus-m2-bootstrap --apply --acknowledge-disposable-pilot

It backs up subordinate-ID configuration, gives the pilot its own storage,
installs a root-owned network namespace with loopback-only default-deny
nftables rules, and runs its rootless Docker daemon as `argus-pilot` within
that namespace. The unit disables Docker iptables programming and rootless port
forwarding; the bootstrap starts no workload and accepts no workload options.

The host administrator captures the isolation/restart/reboot evidence before
using the pilot, then removes the test cell only with the explicit destruction
acknowledgement:

    sudo ./scripts/argus-m2-pilot-teardown --apply --confirm-destroy-disposable-pilot

The teardown removes only the fixed pilot identity, its individual subordinate
ID ranges, units, namespace policy, and disposable storage. It never restores
the full `/etc/subuid` or `/etc/subgid` backup, because other valid host changes
may have happened after bootstrap.
