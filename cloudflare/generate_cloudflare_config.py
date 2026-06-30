#!/usr/bin/env python3
"""Generate plan-only Cloudflare ingress from Oreo Cloud config."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("OREO_CLOUD_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / "scripts"))

from oreo_common import audit, policy_decision  # noqa: E402


PLAN_PATH = ROOT / "cloudflare" / "planned-ingress.yml"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "config" / name).read_text())


def service_url(workload: dict[str, Any], access_item: dict[str, Any]) -> str:
    urls = access_item.get("urls", {})
    if urls.get("local"):
        return str(urls["local"])
    if workload.get("network", {}).get("localUrl"):
        return str(workload["network"]["localUrl"])
    port = workload.get("network", {}).get("internalPort")
    if port:
        return f"http://127.0.0.1:{port}"
    return ""


def target_risks(workload: dict[str, Any]) -> list[str]:
    risks = []
    haystack = json.dumps(workload, sort_keys=True).lower()
    if workload.get("kind") == "admin-tool":
        risks.append("admin tool")
    if "docker.sock" in haystack or "docker-socket" in haystack:
        risks.append("docker-socket target")
    if "/.ssh" in haystack or "host-ssh" in haystack:
        risks.append("host-ssh target")
    if "control-api" in haystack:
        risks.append("control-api target")
    return risks


def yaml_quote(value: str) -> str:
    if not value:
        return '""'
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:/"
    if all(char in safe for char in value):
        return value
    return json.dumps(value)


def build_plan() -> dict[str, Any]:
    workloads = {item["id"]: item for item in load_json("workloads.json")["workloads"]}
    access = load_json("access.json")
    routes = load_json("routes.json")
    exposure = load_json("exposure.json")
    requested = []
    blocked = []
    ingress = []

    for workload_id, access_item in access.get("workloads", {}).items():
        desired = access_item.get("desired", "")
        if desired not in {"cloudflare-protected", "cloudflare-public"}:
            continue
        workload = workloads.get(workload_id)
        if workload is None:
            blocked.append({"workloadId": workload_id, "desired": desired, "reason": "unknown workload"})
            continue
        decision = policy_decision(workload_id, desired)
        risks = target_risks(workload)
        route = routes.get("workloadRoutes", {}).get(workload_id, {}).get("cloudflare", {})
        hostname = str(route.get("hostname", ""))
        service = service_url(workload, access_item)
        if not decision["allowed"]:
            blocked.append({"workloadId": workload_id, "desired": desired, "reason": decision["reason"]})
            continue
        if risks:
            blocked.append({"workloadId": workload_id, "desired": desired, "reason": ", ".join(risks)})
            continue
        if not hostname:
            requested.append({"workloadId": workload_id, "desired": desired, "status": "missing hostname", "service": service})
            continue
        if not service:
            blocked.append({"workloadId": workload_id, "desired": desired, "reason": "missing local service URL"})
            continue
        requires_access = desired == "cloudflare-protected" or bool(route.get("requiresAuth", True))
        requested.append(
            {
                "workloadId": workload_id,
                "desired": desired,
                "status": "planned",
                "hostname": hostname,
                "service": service,
                "requiresAccess": requires_access,
            }
        )
        ingress.append({"hostname": hostname, "service": service, "requiresAccess": requires_access})

    return {
        "providerEnabled": bool(exposure["providers"]["cloudflare"]["enabled"]),
        "requested": requested,
        "blocked": blocked,
        "ingress": ingress,
        "generated": str(PLAN_PATH),
    }


def write_plan(plan: dict[str, Any]) -> None:
    lines = ["# Generated plan only. No tunnel is enabled by this file.", "ingress:"]
    for item in plan["ingress"]:
        lines.append(f"  - hostname: {yaml_quote(item['hostname'])}")
        lines.append(f"    service: {yaml_quote(item['service'])}")
        if item["requiresAccess"]:
            lines.append("    # Cloudflare Access policy required before activation.")
    lines.append("  - service: http_status:404")
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text("\n".join(lines) + "\n")


def print_text(plan: dict[str, Any]) -> None:
    print("Cloudflare Exposure Plan")
    print("")
    print(f"Provider enabled: {str(plan['providerEnabled']).lower()}")
    print("")
    print("Requested:")
    if plan["requested"]:
        for item in plan["requested"]:
            detail = item.get("hostname") or item.get("status", "")
            print(f"- {item['workloadId']}: {item['desired']}, {detail}")
    else:
        print("- none")
    print("")
    print("Blocked:")
    if plan["blocked"]:
        for item in plan["blocked"]:
            print(f"- {item['workloadId']}: {item['reason']}")
    else:
        print("- none")
    print("")
    print("Generated:")
    print(plan["generated"])
    print("")
    print("No cloudflared process, tunnel, DNS record, token, or public route was created.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate plan-only Cloudflare ingress.")
    parser.add_argument("--json", action="store_true", help="Print plan details as JSON.")
    args = parser.parse_args()
    plan = build_plan()
    write_plan(plan)
    audit(
        "cloudflare.plan",
        "cloudflare",
        "ok",
        requested=len(plan["requested"]),
        blocked=len(plan["blocked"]),
        ingress=len(plan["ingress"]),
        generated=plan["generated"],
        providerEnabled=bool(plan["providerEnabled"]),
    )
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print_text(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
