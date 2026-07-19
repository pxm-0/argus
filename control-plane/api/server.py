#!/usr/bin/env python3
"""Local-only Oreo Cloud control API."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(os.environ.get("OREO_CLOUD_ROOT", Path(__file__).resolve().parents[2])).resolve()
TOKEN_FILE = Path(os.environ.get("OREO_CLOUD_TOKEN_FILE", "/etc/oreo-cloud/control-token"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("OREO_CLOUD_API_PORT", "8099"))
sys.path.insert(0, str(ROOT / "scripts"))

from oreo_actions import actions_catalog, backup_apply, backup_preview, logs_preview, restart_apply, restart_preview  # noqa: E402
from argus_m1 import deny_direct_legacy_mutation, privacy_writer  # noqa: E402
from oreo_common import audit, dashboard_state, load_json, now, policy_decision, recent_events, regenerate_dashboard, save_json  # noqa: E402


def token() -> str:
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def merged_workloads() -> dict[str, Any]:
    state = dashboard_state()
    return {key: state[key] for key in ["workloads", "routes", "exposure", "events"]}


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
        elif path == "/api/dashboard-state":
            self.send_json(200, dashboard_state())
        elif path == "/api/access":
            self.send_json(200, load_json("access.json"))
        elif path == "/api/privacy":
            self.send_json(200, load_json("privacy.json"))
        elif path == "/api/metrics":
            metrics = ROOT / "control-plane" / "dashboard" / "public" / "metrics.json"
            self.send_json(200, json.loads(metrics.read_text()) if metrics.exists() else {"error": "metrics unavailable"})
        elif path == "/api/events":
            self.send_json(200, {"events": recent_events()})
        elif path == "/api/actions":
            self.send_json(200, actions_catalog())
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.require_auth():
            return
        path = urlparse(self.path).path
        if path == "/api/workloads/discover":
            self.handle_workload_discover()
            return
        privacy_match = re.fullmatch(r"/api/workloads/([^/]+)/privacy", path)
        preview_match = re.fullmatch(r"/api/workloads/([^/]+)/access/preview", path)
        apply_match = re.fullmatch(r"/api/workloads/([^/]+)/access/apply", path)
        logs_preview_match = re.fullmatch(r"/api/workloads/([^/]+)/logs/preview", path)
        restart_preview_match = re.fullmatch(r"/api/workloads/([^/]+)/restart/preview", path)
        restart_apply_match = re.fullmatch(r"/api/workloads/([^/]+)/restart/apply", path)
        backup_preview_match = re.fullmatch(r"/api/workloads/([^/]+)/backup/preview", path)
        backup_apply_match = re.fullmatch(r"/api/workloads/([^/]+)/backup/apply", path)
        register_match = re.fullmatch(r"/api/workloads/([^/]+)/register", path)
        try:
            body = self.read_body()
            if register_match:
                self.handle_workload_register(register_match.group(1), body)
            elif privacy_match:
                self.handle_privacy(privacy_match.group(1), body)
            elif preview_match:
                self.handle_access_preview(preview_match.group(1), body)
            elif apply_match:
                self.handle_access_apply(apply_match.group(1), body)
            elif logs_preview_match:
                self.handle_logs_preview(logs_preview_match.group(1), body)
            elif restart_preview_match:
                self.handle_restart_preview(restart_preview_match.group(1))
            elif restart_apply_match:
                self.handle_restart_apply(restart_apply_match.group(1), body)
            elif backup_preview_match:
                self.handle_backup_preview(backup_preview_match.group(1))
            elif backup_apply_match:
                self.handle_backup_apply(backup_apply_match.group(1), body)
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
        old, _ = privacy_writer().set_privacy(workload_id=workload_id, privacy_value=new_privacy, reason=reason, actor="control-api", timestamp=now())
        regenerate_dashboard()
        self.send_json(200, {"ok": True, "from": old, "to": new_privacy})

    def handle_access_preview(self, workload_id: str, body: dict[str, Any]) -> None:
        desired = str(body.get("desired", ""))
        self.send_json(200, {"workloadId": workload_id, "desired": desired, **policy_decision(workload_id, desired)})

    def handle_access_apply(self, workload_id: str, body: dict[str, Any]) -> None:
        deny_direct_legacy_mutation("access")
        desired = str(body.get("desired", ""))
        decision = policy_decision(workload_id, desired)
        if not decision["allowed"]:
            audit("access.apply", workload_id, "blocked", actor="admin-token", desired=desired, reason=decision["reason"])
            self.send_json(403, {"workloadId": workload_id, "desired": desired, **decision})
            return
        phrase = str(decision.get("confirmationPhrase", ""))
        if phrase and str(body.get("confirmation", "")) != phrase:
            audit("access.apply", workload_id, "blocked", actor="admin-token", desired=desired, reason="confirmation required")
            self.send_json(
                403,
                {
                    "ok": False,
                    "workloadId": workload_id,
                    "desired": desired,
                    "allowed": False,
                    "reason": "confirmation required",
                    "confirmationRequired": True,
                    "confirmationPhrase": phrase,
                },
            )
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
        audit(
            "access.apply",
            workload_id,
            "ok",
            actor="admin-token",
            oldDesired=old_desired,
            desired=desired,
            oldEffective=old_effective,
            effective=access["workloads"][workload_id]["effective"],
        )
        regenerate_dashboard()
        self.send_json(200, {"ok": True, "workloadId": workload_id, "desired": desired, "effective": access["workloads"][workload_id]["effective"], "plannedOnly": bool(decision.get("plannedOnly"))})

    def handle_logs_preview(self, workload_id: str, body: dict[str, Any]) -> None:
        payload = logs_preview(workload_id, max_lines=int(body.get("maxLines", 100)))
        self.send_json(int(payload.pop("status", 200 if payload.get("ok") else 403)), payload)

    def handle_restart_preview(self, workload_id: str) -> None:
        payload = restart_preview(workload_id)
        self.send_json(int(payload.pop("status", 200 if payload.get("ok") else 403)), payload)

    def handle_restart_apply(self, workload_id: str, body: dict[str, Any]) -> None:
        payload = restart_apply(workload_id, confirmation=str(body.get("confirmation", "")))
        regenerate_dashboard()
        self.send_json(int(payload.pop("status", 200 if payload.get("ok") else 403)), payload)

    def handle_backup_preview(self, workload_id: str) -> None:
        payload = backup_preview(workload_id)
        self.send_json(int(payload.pop("status", 200 if payload.get("ok") else 403)), payload)

    def handle_backup_apply(self, workload_id: str, body: dict[str, Any]) -> None:
        payload = backup_apply(workload_id, confirmation=str(body.get("confirmation", "")))
        regenerate_dashboard()
        self.send_json(int(payload.pop("status", 200 if payload.get("ok") else 403)), payload)

    def handle_workload_discover(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "oreo-workload-discover"), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            self.send_json(500, {"ok": False, "error": "discovery failed", "output": result.stdout})
            return
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.send_json(500, {"ok": False, "error": "invalid discovery output", "output": result.stdout})
            return
        self.send_json(200, {"ok": True, **report})

    def handle_workload_register(self, workload_id: str, body: dict[str, Any]) -> None:
        deny_direct_legacy_mutation("workload registration")
        if workload_id in {str(item.get("id")) for item in load_json("workloads.json")["workloads"]}:
            raise ValueError("workload already tracked")
        name = str(body.get("name") or workload_id)
        compose_project = str(body.get("composeProject") or workload_id)
        kind = str(body.get("kind") or "web-app")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "oreo-workload-add"),
                workload_id,
                name,
                "--compose-project",
                compose_project,
                "--kind",
                kind,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            self.send_json(500, {"ok": False, "error": "register failed", "output": result.stdout})
            return
        regenerate_dashboard()
        self.send_json(200, {"ok": True, "workloadId": workload_id, "output": result.stdout})


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Oreo Cloud control API listening on {HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
