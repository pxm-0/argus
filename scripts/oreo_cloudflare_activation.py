#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from oreo_common import audit, by_id, load_json, now, print_json, root, save_json


ACCESS_CONFIRMATION = "cloudflare access protects this hostname"
SAFE_PRIVACY = {"unclassified", "personal", "internal"}
BLOCKED_KINDS = {"admin-tool", "database"}
BLOCKED_MARKERS = ("postgres", "docker.sock", "docker-socket", "/.ssh", "host-ssh", "control-api")
EVIDENCE_DIR = root() / "runtime" / "cloudflare-activation"


def _privacy(workload_id: str) -> str:
    data = load_json("privacy.json")
    return str(data.get("workloads", {}).get(workload_id, {}).get("privacy", data.get("defaultPrivacy", "")))


def _route(workload_id: str) -> dict[str, Any]:
    routes = load_json("routes.json")
    return dict(routes.get("workloadRoutes", {}).get(workload_id, {}).get("cloudflare", {}))


def _access_item(workload_id: str) -> dict[str, Any]:
    access = load_json("access.json")
    return dict(access.get("workloads", {}).get(workload_id, {}))


def _provider() -> dict[str, Any]:
    exposure = load_json("exposure.json")
    return dict(exposure.get("providers", {}).get("cloudflare", {}))


def _service_url(workload: dict[str, Any], access_item: dict[str, Any], route: dict[str, Any]) -> str:
    if route.get("service"):
        return str(route["service"])
    urls = access_item.get("urls", {})
    if urls.get("local"):
        return str(urls["local"])
    if workload.get("network", {}).get("localUrl"):
        return str(workload["network"]["localUrl"])
    port = workload.get("network", {}).get("internalPort")
    if port:
        return f"http://127.0.0.1:{port}"
    return ""


def yaml_quote(value: str) -> str:
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:/"
    if value and all(char in safe for char in value):
        return value
    return json.dumps(value)


def ingress_text(hostname: str, service: str) -> str:
    return "\n".join(
        [
            "ingress:",
            f"  - hostname: {yaml_quote(hostname)}",
            f"    service: {yaml_quote(service)}",
            "  - service: http_status:404",
            "",
        ]
    )


def _external_config_path(provider: dict[str, Any]) -> Path:
    configured = str(provider.get("activationConfigPath") or "/etc/cloudflared/oreo-cloud.yml")
    return Path(configured)


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(root())
    except ValueError:
        return False
    return True


def activation_plan(workload_id: str = "hello-nginx") -> dict[str, Any]:
    workloads = by_id()
    workload = workloads.get(workload_id)
    provider = _provider()
    route = _route(workload_id)
    access_item = _access_item(workload_id)
    privacy = _privacy(workload_id)
    hostname = str(route.get("hostname") or access_item.get("urls", {}).get("cloudflare", "").removeprefix("https://"))
    service = _service_url(workload or {}, access_item, route)
    config_path = _external_config_path(provider)
    blockers: list[str] = []
    warnings: list[str] = []

    if workload is None:
        blockers.append("unknown workload")
    else:
        haystack = json.dumps(workload, sort_keys=True).lower()
        if workload.get("kind") in BLOCKED_KINDS:
            blockers.append(f"blocked workload kind: {workload.get('kind')}")
        if privacy not in SAFE_PRIVACY:
            blockers.append(f"privacy classification is not allowed for P2 Cloudflare activation: {privacy}")
        marker = next((item for item in BLOCKED_MARKERS if item in haystack), "")
        if marker:
            blockers.append(f"blocked target marker detected: {marker}")
    if workload_id != "hello-nginx":
        blockers.append("P2 activation is limited to hello-nginx")
    if access_item.get("desired") != "cloudflare-protected":
        blockers.append("desired access is not cloudflare-protected")
    if access_item.get("effective") == "cloudflare-public":
        blockers.append("cloudflare-public effective state is forbidden")
    if not hostname:
        blockers.append("missing Cloudflare hostname")
    if hostname.endswith(".invalid"):
        blockers.append("real hostname required; .invalid is only a planning placeholder")
    if route.get("mode") not in {"protected", "planned"}:
        blockers.append(f"route mode is not protected/planned: {route.get('mode')}")
    if route.get("requiresAuth") is not True:
        blockers.append("Cloudflare Access auth must be required")
    if not service:
        blockers.append("missing local service URL")
    if not bool(provider.get("enabled")):
        blockers.append("Cloudflare provider is disabled")
    if not bool(provider.get("provisioned")):
        blockers.append("Cloudflare provider is not provisioned")
    if not bool(provider.get("allowNamedTunnels")):
        blockers.append("named tunnels are not allowed by exposure policy")
    if bool(provider.get("allowQuickTunnels")):
        blockers.append("quick tunnels must remain disabled")
    if _inside_repo(config_path):
        blockers.append("activation config path must be outside the Git repository")
    if not shutil.which("cloudflared"):
        warnings.append("cloudflared is not installed; ingress validation/start cannot run yet")

    return {
        "ok": not blockers,
        "workloadId": workload_id,
        "hostname": hostname,
        "service": service,
        "privacy": privacy,
        "providerEnabled": bool(provider.get("enabled")),
        "providerProvisioned": bool(provider.get("provisioned")),
        "allowNamedTunnels": bool(provider.get("allowNamedTunnels")),
        "allowQuickTunnels": bool(provider.get("allowQuickTunnels")),
        "configPath": str(config_path),
        "ingress": ingress_text(hostname, service) if hostname and service else "",
        "blockers": blockers,
        "warnings": warnings,
        "manualChecks": [
            "Cloudflare named tunnel exists and credentials are stored outside Git.",
            "Cloudflare Access application exists for the hostname.",
            "Access policy denies unauthenticated requests.",
            "DNS points at the named tunnel only after Access policy verification.",
        ],
    }


def validate_ingress(config_path: Path) -> dict[str, Any]:
    if not shutil.which("cloudflared"):
        return {"ok": False, "reason": "cloudflared unavailable"}
    result = subprocess.run(
        ["cloudflared", "tunnel", "ingress", "validate", str(config_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def write_evidence(payload: dict[str, Any]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{now().replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def set_effective_cloudflare_protected(workload_id: str) -> None:
    access = load_json("access.json")
    item = access["workloads"][workload_id]
    item["effective"] = "cloudflare-protected"
    item["lastAppliedAt"] = now()
    item["lastError"] = ""
    save_json("access.json", access)


def lower_effective(workload_id: str, effective: str = "local", reason: str = "Cloudflare activation rolled back") -> None:
    access = load_json("access.json")
    item = access["workloads"][workload_id]
    item["effective"] = effective
    item["lastAppliedAt"] = now()
    item["lastError"] = reason
    save_json("access.json", access)


def print_preview(plan: dict[str, Any]) -> None:
    state = "ready" if plan["ok"] else "blocked"
    print(f"{plan['workloadId']} Cloudflare protected activation: {state}")
    print(f"Hostname: {plan['hostname'] or '-'}")
    print(f"Service: {plan['service'] or '-'}")
    print(f"Config path: {plan['configPath']}")
    if plan["blockers"]:
        print("Blockers:")
        for blocker in plan["blockers"]:
            print(f"- {blocker}")
    if plan["warnings"]:
        print("Warnings:")
        for warning in plan["warnings"]:
            print(f"- {warning}")
    print("Manual checks:")
    for check in plan["manualChecks"]:
        print(f"- {check}")


def json_or_text(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print_json(payload)
    else:
        print_preview(payload)


def audit_preview(plan: dict[str, Any]) -> None:
    audit(
        "cloudflare.activate.preview",
        str(plan["workloadId"]),
        "ok" if plan["ok"] else "blocked",
        hostname=plan.get("hostname", ""),
        blockers=plan.get("blockers", []),
    )
