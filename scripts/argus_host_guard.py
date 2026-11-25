"""Render the host-side egress guard for sealed sandbox identities."""
from __future__ import annotations


class HostGuardError(ValueError):
    pass


HOST_EGRESS: dict[str, tuple[tuple[str, int], ...]] = {
    # The inner prod-cell firewall grants this path only to Hastur's pinned
    # bridge (D030 phase 5). The host guard sees RootlessKit's cell UID instead
    # of the originating bridge, so both gates are required for working egress.
    "personal-sandbox": (),
    "work-sandbox": (),
    "personal-managed": (("tcp", 443),),
}


def render_host_guard(domain: str, uid: int) -> str:
    if domain not in HOST_EGRESS:
        raise HostGuardError(f"unsupported sandbox domain: {domain}")
    if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
        raise HostGuardError("sandbox UID must be a positive integer")

    table = f"argus_{domain.replace('-', '_')}_host_guard"
    allowances = "".join(
        f"    meta skuid {uid} {protocol} dport {port} "
        "ct state new,established accept\n"
        for protocol, port in HOST_EGRESS[domain]
    )
    return (
        f"destroy table inet {table}\n"
        f"table inet {table} {{\n"
        "  chain output {\n"
        "    type filter hook output priority -10; policy accept;\n"
        f"    meta skuid {uid} oifname \"lo\" accept\n"
        f"{allowances}"
        f"    meta skuid {uid} drop\n"
        "  }\n"
        "}\n"
    )
