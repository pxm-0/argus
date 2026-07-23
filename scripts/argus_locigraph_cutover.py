"""Validation helpers for the production-safe LociGraph Compose override."""
from __future__ import annotations

from typing import Any


SERVICES = ("backend", "caddy", "frontend", "postgres", "redis", "worker")


class CutoverError(ValueError):
    """Raised when an effective Compose model violates the cutover contract."""


def override_text() -> str:
    lines = ["services:"]
    for service in SERVICES:
        lines.extend([f"  {service}:", "    restart: unless-stopped"])
        if service == "caddy":
            lines.extend(["    ports: !override", '      - "127.0.0.1:8090:80"'])
        elif service in {"backend", "postgres", "redis"}:
            lines.append("    ports: !reset []")
    return "\n".join(lines) + "\n"


def validate_effective(compose: dict[str, Any]) -> dict[str, Any]:
    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != set(SERVICES):
        raise CutoverError("effective Compose services differ from the approved LociGraph set")
    publications = []
    for name in SERVICES:
        service = services[name]
        if service.get("restart") != "unless-stopped":
            raise CutoverError(f"service {name} is not boot-persistent")
        for port in service.get("ports") or []:
            if not isinstance(port, dict):
                raise CutoverError(f"service {name} has an unsupported port declaration")
            publications.append(
                {
                    "service": name,
                    "hostIp": str(port.get("host_ip", "")),
                    "published": int(port["published"]),
                    "target": int(port["target"]),
                    "protocol": str(port.get("protocol", "tcp")),
                }
            )
    expected = [{"service": "caddy", "hostIp": "127.0.0.1", "published": 8090, "target": 80, "protocol": "tcp"}]
    if publications != expected:
        raise CutoverError("effective Compose publication is not exactly loopback Caddy on port 8090")
    return {
        "schemaVersion": 1,
        "composeProject": str(compose.get("name", "locigraph")),
        "services": list(SERVICES),
        "publications": publications,
        "databaseHostPublished": False,
        "cacheHostPublished": False,
        "backendHostPublished": False,
        "bootPersistent": True,
        "verified": True,
        "redacted": True,
    }
