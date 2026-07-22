"""Secret-safe, read-only LociGraph Compose migration evidence."""
from __future__ import annotations

from typing import Any


class PreflightError(ValueError):
    """Raised when the legacy Compose model cannot be evaluated safely."""


def _scope(host_ip: Any) -> str:
    value = str(host_ip or "")
    if value in {"127.0.0.1", "::1"}:
        return "loopback"
    if value in {"", "0.0.0.0", "::"}:
        return "wildcard"
    return "specific-address"


def _service_report(name: str, service: dict[str, Any]) -> dict[str, Any]:
    ports = []
    for port in service.get("ports") or []:
        if not isinstance(port, dict):
            raise PreflightError(f"service {name} has an unsupported short port declaration")
        ports.append(
            {
                "target": int(port["target"]),
                "published": int(port["published"]),
                "protocol": str(port.get("protocol", "tcp")),
                "addressScope": _scope(port.get("host_ip")),
            }
        )
    mounts = []
    for mount in service.get("volumes") or []:
        if not isinstance(mount, dict):
            raise PreflightError(f"service {name} has an unsupported short volume declaration")
        mounts.append(
            {
                "type": str(mount.get("type", "")),
                "target": str(mount.get("target", "")),
                "readOnly": bool(mount.get("read_only", False)),
            }
        )
    environment = service.get("environment") or {}
    if isinstance(environment, list):
        environment_keys = sorted(str(item).split("=", 1)[0] for item in environment)
    elif isinstance(environment, dict):
        environment_keys = sorted(str(key) for key in environment)
    else:
        raise PreflightError(f"service {name} has an unsupported environment declaration")
    return {
        "name": name,
        "restartPolicy": str(service.get("restart", "no")),
        "publishedPorts": sorted(ports, key=lambda item: (item["published"], item["target"])),
        "mounts": sorted(mounts, key=lambda item: (item["target"], item["type"])),
        "environmentKeys": environment_keys,
        "healthcheckConfigured": bool(service.get("healthcheck")),
    }


def build_report(*, compose: dict[str, Any], containers: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    services = compose.get("services")
    if not isinstance(services, dict) or not services:
        raise PreflightError("Compose model contains no services")
    reports = [_service_report(str(name), service) for name, service in sorted(services.items())]
    wildcard = [f'{item["name"]}:{port["published"]}' for item in reports for port in item["publishedPorts"] if port["addressScope"] == "wildcard"]
    database_or_cache = [
        f'{item["name"]}:{port["published"]}'
        for item in reports
        if item["name"] in {"postgres", "redis"}
        for port in item["publishedPorts"]
    ]
    no_restart = [item["name"] for item in reports if item["restartPolicy"] in {"", "no"}]
    running = sorted(str(item.get("service", "")) for item in containers if item.get("running"))
    operations = manifest.get("operations") or {}
    backup = manifest.get("backup") or {}
    findings = []
    if wildcard:
        findings.append("wildcard-published-ports")
    if database_or_cache:
        findings.append("database-or-cache-host-published")
    if no_restart:
        findings.append("boot-persistence-absent")
    if not bool(backup.get("backupAllowed", False)) or not bool(backup.get("restoreTested", False)):
        findings.append("backup-restore-gate-incomplete")
    if running:
        findings.append("source-not-stopped")
    return {
        "schemaVersion": 1,
        "workloadId": "locigraph",
        "composeProject": str(compose.get("name", "locigraph")),
        "readOnly": True,
        "redacted": True,
        "environmentValuesIncluded": False,
        "sourceStopped": not running,
        "runningServices": running,
        "services": reports,
        "gates": {
            "restartApproved": bool(operations.get("restartAllowed", False)),
            "backupApproved": bool(backup.get("backupAllowed", False)),
            "restoreTested": bool(backup.get("restoreTested", False)),
            "wildcardPublishedPortsAbsent": not wildcard,
            "databaseAndCacheHostPortsAbsent": not database_or_cache,
            "bootPersistenceConfigured": not no_restart,
        },
        "findings": findings,
        "safeForMigrationApply": not findings,
    }
