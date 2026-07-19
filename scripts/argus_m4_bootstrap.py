"""Fail-closed M4 target-cell contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class BootstrapError(ValueError):
    """Raised when an unsupported M4 cell is requested."""


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def personal_sandbox_contract(*, user: str) -> dict[str, Any]:
    if user != "argus-personal-sandbox":
        raise BootstrapError("personal-sandbox must use its dedicated Argus identity")
    contract = {
        "schemaVersion": 1,
        "domain": "personal-sandbox",
        "user": user,
        "mutations": ["create-dedicated-unix-identity", "allocate-subordinate-ids", "enable-user-lingering", "create-dedicated-storage-root", "install-rootless-systemd-unit", "create-network-namespace", "install-default-deny-firewall-policy"],
        "prohibitions": ["no-host-networking", "no-host-path-mounts", "no-docker-socket-mounts", "no-published-ports", "no-public-route", "no-cross-domain-route"],
        "requiredEvidence": ["config-backup", "namespace-isolation-matrix", "daemon-start-check", "no-listener-check", "rollback-rehearsal"],
    }
    return {**contract, "contractDigest": _digest(contract)}
