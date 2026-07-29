"""Fail-closed M4 target-cell contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class BootstrapError(ValueError):
    """Raised when an unsupported M4 cell is requested."""


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sandbox_contract(*, domain: str, user: str) -> dict[str, Any]:
    if domain not in {"personal-sandbox", "work-sandbox"}:
        raise BootstrapError("unsupported sandbox domain")
    if user != f"argus-{domain}":
        raise BootstrapError(f"{domain} must use its dedicated Argus identity")
    contract = {
        "schemaVersion": 1,
        "domain": domain,
        "user": user,
        "mutations": ["create-dedicated-unix-identity", "allocate-subordinate-ids", "enable-user-lingering", "create-dedicated-storage-root", "install-rootless-systemd-unit", "create-network-namespace", "install-host-uid-egress-guard", "install-default-deny-firewall-policy"],
        "prohibitions": ["no-host-networking", "no-host-path-mounts", "no-docker-socket-mounts", "no-published-ports", "no-public-route", "no-cross-domain-route"],
        "requiredEvidence": ["config-backup", "namespace-isolation-matrix", "daemon-start-check", "no-listener-check", "rollback-rehearsal"],
        "rollback": ["restore-backed-up-config", "restore-subordinate-id-files", "restore-service-state", "remove-new-empty-cell-only"],
    }
    return {**contract, "contractDigest": _digest(contract)}


def personal_sandbox_contract(*, user: str) -> dict[str, Any]:
    return sandbox_contract(domain="personal-sandbox", user=user)
