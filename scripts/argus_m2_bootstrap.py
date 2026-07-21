"""Fail-closed contract and deterministic subordinate-ID allocator for Argus M2."""
from __future__ import annotations
import hashlib
import json
from typing import Any

class BootstrapError(ValueError):
    pass


def _ranges(contents: str) -> list[tuple[int, int]]:
    parsed: list[tuple[int, int]] = []
    for line in contents.splitlines():
        parts = line.split(":")
        if len(parts) != 3:
            continue
        try:
            start, length = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if start >= 0 and length > 0:
            parsed.append((start, start + length - 1))
    return parsed


def first_free_subid_range(*, subuid: str, subgid: str, size: int = 65536, floor: int = 100000) -> tuple[int, int]:
    """Return the first shared, non-overlapping subordinate-ID range.

    The allocator considers both files together, so the identity receives the
    same safe range for UIDs and GIDs without overwriting another local user.
    """
    if size <= 0 or floor < 0:
        raise BootstrapError("invalid subordinate-ID range request")
    occupied = sorted(_ranges(subuid) + _ranges(subgid))
    candidate = floor
    for start, end in occupied:
        if end < candidate:
            continue
        if candidate + size - 1 < start:
            return candidate, candidate + size - 1
        candidate = max(candidate, end + 1)
    return candidate, candidate + size - 1

def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def pilot_contract(*, domain: str, user: str) -> dict[str, Any]:
    if domain != "personal-sandbox-pilot" or user != "argus-pilot":
        raise BootstrapError("only the disposable personal-sandbox pilot is permitted")
    contract = {
        "schemaVersion": 1, "domain": domain, "user": user,
        "mutations": ["create-dedicated-unix-identity", "allocate-subordinate-ids", "enable-user-lingering", "create-dedicated-storage-root", "install-rootless-systemd-unit", "create-network-namespace", "install-default-deny-firewall-policy"],
        "prohibitions": ["no-host-networking", "no-host-path-mounts", "no-docker-socket-mounts", "no-published-ports", "no-public-route", "no-cross-domain-route"],
        "requiredEvidence": ["config-backup", "preflight-pass", "namespace-isolation-matrix", "daemon-restart-check", "host-reboot-check", "rollback-rehearsal"],
        "rollback": ["stop-and-disable-pilot-unit", "remove-firewall-policy", "remove-network-namespace", "remove-dedicated-storage-root", "remove-pilot-identity-only-after-data-destruction-confirmation"],
    }
    return {**contract, "contractDigest": _digest(contract)}
