"""Fail-closed contract generator for the root-owned Argus M2 pilot bootstrap."""
from __future__ import annotations
import hashlib
import json
from typing import Any

class BootstrapError(ValueError):
    pass

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
