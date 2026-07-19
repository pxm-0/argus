"""Fail-closed inspection for the stateless hello-nginx M4 cutover plan."""
from __future__ import annotations

import hashlib
import json
from typing import Any


class CutoverPlanError(ValueError):
    """Raised when the pilot Compose definition cannot enter the sealed target."""


FORBIDDEN_SERVICE_FIELDS = {
    "ports", "volumes", "network_mode", "privileged", "pid", "devices",
    "cap_add", "cap_drop", "security_opt", "extra_hosts", "use_api_socket",
}


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def inspect_stateless_compose(compose: dict[str, Any]) -> dict[str, Any]:
    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != {"web"}:
        raise CutoverPlanError("pilot must contain exactly the web service")
    web = services["web"]
    if not isinstance(web, dict) or not isinstance(web.get("image"), str) or not web["image"]:
        raise CutoverPlanError("pilot web service must use an explicit image")
    if "build" in web:
        raise CutoverPlanError("target image must be imported; target-side builds are forbidden")
    forbidden = sorted(field for field in FORBIDDEN_SERVICE_FIELDS if field in web and web[field] not in (None, [], {}, False, ""))
    if forbidden:
        raise CutoverPlanError("pilot Compose uses forbidden target fields: " + ", ".join(forbidden))
    return {
        "sourceComposeDigest": digest(compose),
        "sourceImageRefDigest": digest(web["image"]),
        "serviceCount": 1,
    }


def build_plan(*, preflight: dict[str, Any], compose: dict[str, Any], target_empty: bool) -> dict[str, Any]:
    required_preflight = {
        "workloadId": "hello-nginx",
        "backupVerified": True,
        "restoreVerified": True,
        "sourceHealthVerified": True,
        "targetDaemonVerified": True,
        "targetEmptyVerified": True,
        "targetNoTcpListenersVerified": True,
    }
    if any(preflight.get(key) != value for key, value in required_preflight.items()):
        raise CutoverPlanError("complete hello-nginx preflight evidence is required")
    if target_empty is not True:
        raise CutoverPlanError("target must remain empty while the cutover plan is reviewed")
    inspected = inspect_stateless_compose(compose)
    return {
        "schemaVersion": 1,
        "workloadId": "hello-nginx",
        "cutoverApproved": False,
        "nextGate": "review-approved-cutover-implementation",
        "targetContract": "personal-sandbox-no-mounts-no-ports-no-public-route",
        **inspected,
    }
