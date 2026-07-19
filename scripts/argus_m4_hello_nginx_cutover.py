"""Strict target-Compose generation for the M4 hello-nginx cutover."""
from __future__ import annotations

from typing import Any


class CutoverError(ValueError):
    pass


def target_compose(source: dict[str, Any]) -> dict[str, Any]:
    services = source.get("services")
    if not isinstance(services, dict) or set(services) != {"web"}:
        raise CutoverError("source must contain exactly the web service")
    web = services["web"]
    if not isinstance(web, dict) or not isinstance(web.get("image"), str) or not web["image"]:
        raise CutoverError("source web image is required")
    allowed = {"image", "ports", "networks"}
    unsupported = sorted(key for key, value in web.items() if key not in allowed and value not in (None, [], {}, False, ""))
    if unsupported:
        raise CutoverError("source service has unsupported cutover fields: " + ", ".join(unsupported))
    ports = web.get("ports", [])
    if not isinstance(ports, list) or any(not isinstance(port, dict) or str(port.get("host_ip", "")) not in {"127.0.0.1", "::1"} for port in ports):
        raise CutoverError("source ports must be loopback-only")
    return {"name": "hello-nginx", "services": {"web": {"image": web["image"]}}}
