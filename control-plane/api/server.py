#!/usr/bin/env python3
"""Local-only Oreo Cloud control API."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(os.environ.get("OREO_CLOUD_ROOT", Path(__file__).resolve().parents[2])).resolve()
TOKEN_FILE = Path(os.environ.get("OREO_CLOUD_TOKEN_FILE", "/etc/oreo-cloud/control-token"))
AUDIT = ROOT / "runtime" / "audit.log"
HOST = "127.0.0.1"
PORT = int(os.environ.get("OREO_CLOUD_API_PORT", "8099"))


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "config" / name).read_text())


def load_manifest(workload_id: str) -> dict[str, Any]:
    path = ROOT / "workloads" / workload_id / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def recent_events() -> list[dict[str, Any]]:
    events = []
    if AUDIT.exists():
        for line in AUDIT.read_text().splitlines()[-50:]:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(
                {
                    "timestamp": event.get("timestamp", ""),
                    "action": event.get("action", ""),
                    "workloadId": event.get("workloadId", ""),
                    "result": event.get("result", ""),
                }
            )
    return events


def save_json(name: str, data: dict[str, Any]) -> None:
    path = ROOT / "config" / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    temp.replace(path)


def audit(action: str, workload_id: str, result: str, **extra: Any) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": now(), "actor": "admin-token", "action": action, "workloadId": workload_id, "result": result, **extra}
    with AUDIT.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def token() -> str:
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def merged_workloads() -> dict[str, Any]:
    workloads = load_json("workloads.json")
    privacy = load_json("privacy.json")
    access = load_json("access.json")
    routes = load_json("routes.json")
    exposure = load_json("exposure.json")
    merged = []
    events = recent_events()
    for workload in workloads["workloads"]:
        wid = workload["id"]
        manifest = load_manifest(wid)
        last_event = next((event for event in reversed(events) if event.get("workloadId") == wid), {})
        merged.append(
            {
                **workload,
                "privacy": privacy["workloads"].get(wid, {}),
                "access": access["workloads"].get(wid, {}),
                "routes": routes["workloadRoutes"].get(wid, {}),
                "manifest": manifest,
                "operations": manifest.get("operations", {}),
                "backup": manifest.get("backup", {}),
                "lastAuditEvent": last_event,
            }
        )
    return {"workloads": merged, "routes": routes, "exposure": exposure, "events": events[-20:]}


def regenerate_dashboard() -> None:
    import importlib.util

    generator = ROOT / "control-plane" / "dashboard" / "generate_dashboard.py"
    spec = importlib.util.spec_from_file_location("generate_dashboard", generator)
    if spec is None or spec.loader is None:
        raise RuntimeError("dashboard generator unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def policy_decision(workload_id: str, desired: str) -> dict[str, Any]:
    workloads = {item["id"]: item for item in load_json("workloads.json")["workloads"]}
    privacy = load_json("privacy.json")
    policy = load_json("policy.json")
    access = load_json("access.json")
    if workload_id not in workloads:
        return {"allowed": False, "reason": "unknown workload", "effective": None}
    if desired not in access["states"]:
        return {"allowed": False, "reason": "invalid access state", "effective": None}
    privacy_state = privacy["workloads"].get(workload_id, {}).get("privacy", privacy["defaultPrivacy"])
    rules = policy["rules"]
    if desired == "tailnet" and rules.get("allowTailnetForAll", False):
        return {"allowed": True, "reason": "tailnet allowed", "effective": "tailnet"}
    if desired in {"none", "local"}:
        return {"allowed": True, "reason": "safe local state", "effective": desired}
    if desired == "cloudflare-public":
        if privacy_state == "restricted" and not rules.get("allowRestrictedToCloudflarePublic", False):
            return {"allowed": False, "reason": "restricted workloads cannot be public", "effective": None}
        if privacy_state == "sensitive" and not rules.get("allowSensitiveToCloudflarePublic", False):
            return {"allowed": False, "reason": "sensitive workloads cannot be public", "effective": None}
        return {"allowed": True, "reason": "public exposure planned only in P0", "effective": access["workloads"][workload_id]["effective"], "plannedOnly": True}
    if desired == "cloudflare-protected":
        if privacy_state == "restricted" and not rules.get("allowRestrictedToCloudflareProtected", False):
            return {"allowed": False, "reason": "restricted protected exposure blocked", "effective": None}
        if privacy_state == "sensitive" and not rules.get("allowSensitiveToCloudflareProtected", False):
            return {"allowed": False, "reason": "sensitive protected exposure blocked", "effective": None}
        return {"allowed": True, "reason": "Cloudflare exposure planned only in P0", "effective": access["workloads"][workload_id]["effective"], "plannedOnly": True}
    return {"allowed": False, "reason": "policy denied", "effective": None}


class Handler(BaseHTTPRequestHandler):
    server_version = "OreoCloudControl/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Avoid logging headers or request bodies; never risk token leakage.
        print(f"{self.address_string()} {self.command} {self.path} {fmt % args}")

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self) -> bool:
        expected = token()
        supplied = self.headers.get("Authorization", "")
        if not expected or supplied != f"Bearer {expected}":
            self.send_json(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/workloads":
            self.send_json(200, merged_workloads())
        elif path == "/api/access":
            self.send_json(200, load_json("access.json"))
        elif path == "/api/privacy":
            self.send_json(200, load_json("privacy.json"))
        elif path == "/api/metrics":
            metrics = ROOT / "control-plane" / "dashboard" / "public" / "metrics.json"
            self.send_json(200, json.loads(metrics.read_text()) if metrics.exists() else {"error": "metrics unavailable"})
        elif path == "/api/events":
            self.send_json(200, {"events": recent_events()})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.require_auth():
            return
        path = urlparse(self.path).path
        privacy_match = re.fullmatch(r"/api/workloads/([^/]+)/privacy", path)
        preview_match = re.fullmatch(r"/api/workloads/([^/]+)/access/preview", path)
        apply_match = re.fullmatch(r"/api/workloads/([^/]+)/access/apply", path)
        try:
            body = self.read_body()
            if privacy_match:
                self.handle_privacy(privacy_match.group(1), body)
            elif preview_match:
                self.handle_access_preview(preview_match.group(1), body)
            elif apply_match:
                self.handle_access_apply(apply_match.group(1), body)
            else:
                self.send_json(404, {"error": "not found"})
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid json"})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - API should return JSON errors.
            self.send_json(500, {"error": exc.__class__.__name__})

    def handle_privacy(self, workload_id: str, body: dict[str, Any]) -> None:
        privacy = load_json("privacy.json")
        workloads = {item["id"] for item in load_json("workloads.json")["workloads"]}
        new_privacy = str(body.get("privacy", ""))
        reason = str(body.get("reason", "Operator change"))
        if workload_id not in workloads:
            raise ValueError("unknown workload")
        if new_privacy not in privacy["states"]:
            raise ValueError("invalid privacy state")
        old = privacy["workloads"].get(workload_id, {}).get("privacy", privacy["defaultPrivacy"])
        privacy["workloads"][workload_id] = {"privacy": new_privacy, "reason": reason, "updatedAt": now(), "updatedBy": "control-api"}
        save_json("privacy.json", privacy)
        audit("privacy.set", workload_id, "ok", **{"from": old, "to": new_privacy})
        regenerate_dashboard()
        self.send_json(200, {"ok": True, "from": old, "to": new_privacy})

    def handle_access_preview(self, workload_id: str, body: dict[str, Any]) -> None:
        desired = str(body.get("desired", ""))
        self.send_json(200, {"workloadId": workload_id, "desired": desired, **policy_decision(workload_id, desired)})

    def handle_access_apply(self, workload_id: str, body: dict[str, Any]) -> None:
        desired = str(body.get("desired", ""))
        decision = policy_decision(workload_id, desired)
        if not decision["allowed"]:
            audit("access.apply", workload_id, "blocked", desired=desired, reason=decision["reason"])
            self.send_json(403, {"workloadId": workload_id, "desired": desired, **decision})
            return
        access = load_json("access.json")
        if workload_id not in access["workloads"]:
            raise ValueError("unknown workload")
        old_desired = access["workloads"][workload_id]["desired"]
        old_effective = access["workloads"][workload_id]["effective"]
        access["workloads"][workload_id]["desired"] = desired
        if decision.get("plannedOnly"):
            access["workloads"][workload_id]["lastError"] = decision["reason"]
        else:
            access["workloads"][workload_id]["effective"] = decision["effective"]
            access["workloads"][workload_id]["lastError"] = ""
        access["workloads"][workload_id]["lastAppliedAt"] = now()
        save_json("access.json", access)
        audit("access.apply", workload_id, "ok", oldDesired=old_desired, desired=desired, oldEffective=old_effective, effective=access["workloads"][workload_id]["effective"])
        regenerate_dashboard()
        self.send_json(200, {"ok": True, "workloadId": workload_id, "desired": desired, "effective": access["workloads"][workload_id]["effective"], "plannedOnly": bool(decision.get("plannedOnly"))})


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Oreo Cloud control API listening on {HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
