#!/usr/bin/env python3
"""Shared helpers for Oreo Cloud CLI scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import deque
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

from argus_m5_topology import build_topology


APPROVED_OPERATOR_LINKS = {
    "argus-legacy-inventory": "argus-legacy-inventory",
    "argus-m0-remediation-plan": "argus-m0-remediation-plan",
    "argus-m0-evidence": "argus-m0-evidence",
    "argus-m0-isolation-check": "argus-m0-isolation-check",
    "oreo-logs": "oreo-logs",
    "oreo-backup-plan": "oreo-backup-plan",
    "oreo-backup-prune": "oreo-backup-prune",
    "oreo-backup-run": "oreo-backup-run",
    "oreo-restore-plan": "oreo-restore-plan",
    "oreo-events": "oreo-events",
    "oreo-cloud-smoke-test": "smoke-test",
    "oreo-access-preview": "oreo-access-preview",
    "oreo-access-apply": "oreo-access-apply",
    "oreo-access-reconcile": "oreo-access-reconcile",
    "oreo-cloudflare-plan": "oreo-cloudflare-plan",
    "oreo-cloudflare-activate-preview": "oreo-cloudflare-activate-preview",
    "oreo-cloudflare-activate": "oreo-cloudflare-activate",
    "oreo-cloudflare-rollback": "oreo-cloudflare-rollback",
    "oreo-smoke-scheduled": "oreo-smoke-scheduled",
    "oreo-template-check": "oreo-template-check",
}
OPERATION_SCRIPTS = [
    "argus-legacy-inventory",
    "argus-m0-remediation-plan",
    "argus-m0-evidence",
    "argus-m0-isolation-check",
    "oreo-logs",
    "oreo-backup-plan",
    "oreo-backup-prune",
    "oreo-backup-run",
    "oreo-restore-plan",
    "oreo-events",
    "oreo-action-preview",
    "oreo-action-apply",
    "oreo-access-reconcile",
    "oreo-cloudflare-activate-preview",
    "oreo-cloudflare-activate",
    "oreo-cloudflare-rollback",
    "oreo-smoke-scheduled",
    "oreo-template-check",
    "smoke-test",
]
SECRET_KEY_PARTS = (
    "authorization",
    "bearer",
    "credential",
    "key",
    "password",
    "private",
    "secret",
    "token",
)
REDACTED = "[redacted]"


def root() -> Path:
    override = os.environ.get("OREO_CLOUD_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def load_json(name: str) -> dict[str, Any]:
    path = root() / "config" / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"missing {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from None


def save_json(name: str, data: dict[str, Any]) -> None:
    path = root() / "config" / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    temp.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SECRET_KEY_PARTS)


def sanitize_audit_value(value: Any, *, key: str = "") -> Any:
    if _secret_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(item_key): sanitize_audit_value(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sanitize_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    return {str(key): sanitize_audit_value(value, key=str(key)) for key, value in event.items()}


def audit(action: str, workload_id: str, result: str, *, actor: str = "local-cli", **extra: Any) -> None:
    path = root() / "runtime" / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    event = sanitize_audit_event({
        "timestamp": now(),
        "actor": actor,
        "action": action,
        "workloadId": workload_id,
        "result": result,
        **extra,
    })
    with path.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def regenerate_dashboard(*, quiet: bool = False) -> None:
    import importlib.util

    generator = root() / "control-plane" / "dashboard" / "generate_dashboard.py"
    spec = importlib.util.spec_from_file_location("generate_dashboard", generator)
    if spec is None or spec.loader is None:
        fail(f"dashboard generator unavailable: {generator}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if quiet:
        with redirect_stdout(StringIO()):
            module.main()
    else:
        module.main()


def workloads() -> list[dict[str, Any]]:
    data = load_json("workloads.json")
    items = data.get("workloads", [])
    if not isinstance(items, list):
        raise SystemExit("config/workloads.json must contain a workloads list")
    return items


def by_id() -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in workloads()}


def load_manifest(workload_id: str) -> dict[str, Any]:
    workload = by_id().get(workload_id)
    if workload is None:
        fail(f"unknown workload: {workload_id}")
    manifest_path = root() / "workloads" / workload_id / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {manifest_path}: {exc}")


def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    path = root() / "runtime" / "audit.log"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in deque(path.open(), maxlen=max(limit, 1)):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        safe = sanitize_audit_event(event)
        events.append(
            {
                "timestamp": safe.get("timestamp", ""),
                "actor": safe.get("actor", ""),
                "action": safe.get("action", ""),
                "workloadId": safe.get("workloadId", ""),
                "result": safe.get("result", ""),
            }
        )
    return events


def dashboard_state() -> dict[str, Any]:
    privacy = load_json("privacy.json")
    access = load_json("access.json")
    routes = load_json("routes.json")
    exposure = load_json("exposure.json")
    monitoring = load_json("monitoring.json")
    events = recent_events()
    legacy_classification = load_json("argus/legacy-classification.json")
    workload_classification = load_json("argus/workload-classification.json")

    merged = []
    for workload in workloads():
        workload_id = str(workload["id"])
        manifest = load_manifest(workload_id)
        last_event = next((event for event in reversed(events) if event.get("workloadId") == workload_id), {})
        merged.append(
            {
                **workload,
                "privacy": privacy["workloads"].get(workload_id, {}),
                "access": access["workloads"].get(workload_id, {}),
                "routes": routes["workloadRoutes"].get(workload_id, {}),
                "manifest": manifest,
                "operations": manifest.get("operations", {}),
                "backup": manifest.get("backup", {}),
                "lastAuditEvent": last_event,
            }
        )

    return {
        "workloads": merged,
        "privacyStates": privacy["states"],
        "accessStates": access["states"],
        "routes": routes,
        "exposure": exposure,
        "monitoring": monitoring,
        "events": events[-20:],
        "topology": build_topology(
            workloads=merged,
            legacy=legacy_classification,
            classified=workload_classification,
        ),
    }


def operation_allowed(workload_id: str, operation: str) -> bool:
    manifest = load_manifest(workload_id)
    operations = manifest.get("operations", {}) if manifest else {}
    return bool(operations.get(operation, False))


def runtime_config(workload_id: str) -> dict[str, Any]:
    workload = by_id().get(workload_id)
    if workload is None:
        fail(f"unknown workload: {workload_id}")
    manifest = load_manifest(workload_id)
    runtime = dict(workload.get("runtime", {}))
    runtime.update(manifest.get("runtime", {}) if manifest else {})
    return runtime


def policy_decision(workload_id: str, desired: str) -> dict[str, Any]:
    workload_map = by_id()
    privacy = load_json("privacy.json")
    policy = load_json("policy.json")
    access = load_json("access.json")
    routes = load_json("routes.json")
    changes = {
        "files": ["config/access.json", "runtime/audit.log", "control-plane/dashboard/public/*"],
        "routes": routes.get("workloadRoutes", {}).get(workload_id, {}),
    }
    if workload_id not in workload_map:
        return {
            "allowed": False,
            "reason": "unknown workload",
            "effective": None,
            "plannedOnly": False,
            "confirmationRequired": False,
            "confirmationPhrase": "",
            "changes": changes,
        }
    if desired not in access.get("states", []):
        return {
            "allowed": False,
            "reason": "invalid access state",
            "effective": None,
            "plannedOnly": False,
            "confirmationRequired": False,
            "confirmationPhrase": "",
            "changes": changes,
        }

    rules = policy.get("rules", {})
    privacy_state = privacy.get("workloads", {}).get(workload_id, {}).get("privacy", privacy.get("defaultPrivacy", "unclassified"))
    current_effective = access["workloads"][workload_id]["effective"]
    phrases = policy.get("confirmationPhrases", {})

    def allowed(reason: str, effective: str | None, *, planned_only: bool = False, phrase: str = "") -> dict[str, Any]:
        return {
            "allowed": True,
            "reason": reason,
            "effective": effective,
            "plannedOnly": planned_only,
            "confirmationRequired": bool(phrase),
            "confirmationPhrase": phrase,
            "changes": changes,
        }

    if desired == "tailnet" and rules.get("allowTailnetForAll", False):
        return allowed("tailnet allowed", "tailnet")
    if desired in {"none", "local"}:
        return allowed("safe local state", desired)
    if desired == "cloudflare-public":
        if privacy_state == "restricted" and not rules.get("allowRestrictedToCloudflarePublic", False):
            return {
                "allowed": False,
                "reason": "restricted workloads cannot be public",
                "effective": None,
                "plannedOnly": False,
                "confirmationRequired": False,
                "confirmationPhrase": "",
                "changes": changes,
            }
        if privacy_state == "sensitive" and not rules.get("allowSensitiveToCloudflarePublic", False):
            return {
                "allowed": False,
                "reason": "sensitive workloads cannot be public",
                "effective": None,
                "plannedOnly": False,
                "confirmationRequired": False,
                "confirmationPhrase": "",
                "changes": changes,
            }
        phrase = phrases.get("cloudflare-public", "") if rules.get("requireConfirmationForCloudflarePublic", False) else ""
        if privacy_state == "restricted" and rules.get("requireSecondConfirmationForRestrictedPublic", False):
            phrase = phrases.get("restricted-cloudflare-public", phrase)
        return allowed("public exposure planned only in P0", current_effective, planned_only=True, phrase=phrase)
    if desired == "cloudflare-protected":
        if privacy_state == "restricted" and not rules.get("allowRestrictedToCloudflareProtected", False):
            return {
                "allowed": False,
                "reason": "restricted protected exposure blocked",
                "effective": None,
                "plannedOnly": False,
                "confirmationRequired": False,
                "confirmationPhrase": "",
                "changes": changes,
            }
        if privacy_state == "sensitive" and not rules.get("allowSensitiveToCloudflareProtected", False):
            return {
                "allowed": False,
                "reason": "sensitive protected exposure blocked",
                "effective": None,
                "plannedOnly": False,
                "confirmationRequired": False,
                "confirmationPhrase": "",
                "changes": changes,
            }
        phrase = "plan protected cloudflare" if rules.get("requireConfirmationForCloudflareProtected", False) else ""
        return allowed("Cloudflare exposure planned only in P0", current_effective, planned_only=True, phrase=phrase)
    return {
        "allowed": False,
        "reason": "policy denied",
        "effective": None,
        "plannedOnly": False,
        "confirmationRequired": False,
        "confirmationPhrase": "",
        "changes": changes,
    }


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    fmt = "  ".join("{:<" + str(width) + "}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * width for width in widths]))
    for row in rows:
        print(fmt.format(*row))


def yaml_quote(value: str) -> str:
    if not value:
        return '""'
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:/"
    if all(char in safe for char in value):
        return value
    return json.dumps(value)


def http_status(url: str, timeout: float = 3.0) -> tuple[str, str]:
    if not url:
        return "skip", "no-url"
    request = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(NoRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            return str(response.status), "ok"
    except urllib.error.HTTPError as exc:
        return str(exc.code), "http-error"
    except Exception as exc:  # noqa: BLE001 - CLI should report concise failure.
        return "fail", exc.__class__.__name__


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None
