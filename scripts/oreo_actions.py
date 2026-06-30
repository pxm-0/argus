from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from oreo_common import audit, by_id, http_status, load_manifest, operation_allowed, runtime_config


MAX_LOG_LINES = 100
MAX_LOG_BYTES = 65536
MAX_LINE_CHARS = 600
SECRET_LINE = re.compile(r"(authorization|bearer|credential|password|private[_ -]?key|secret|token)", re.IGNORECASE)
TOKEN_PAIR = re.compile(r"(?i)([a-z0-9_.-]*(?:token|secret|password|key|credential)[a-z0-9_.-]*)(\\s*[:=]\\s*)([^\\s,;]+)")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _base(operation: str, workload_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "workloadId": workload_id,
        "operation": operation,
        "warnings": [],
        "redacted": True,
    }


def _blocked(operation: str, workload_id: str, reason: str, *, status: int = 403) -> dict[str, Any]:
    return {
        **_base(operation, workload_id),
        "ok": False,
        "allowed": False,
        "status": status,
        "reason": reason,
        "summary": reason,
    }


def _workload(workload_id: str) -> dict[str, Any] | None:
    return by_id().get(workload_id)


def _health(workload: dict[str, Any]) -> dict[str, str]:
    health = workload.get("health", {})
    status, detail = http_status(str(health.get("url", "")), float(health.get("timeoutSeconds", 3)))
    return {
        "url": str(health.get("url", "")),
        "expectedStatus": str(health.get("expectedStatus", "")),
        "status": status,
        "detail": detail,
    }


def _compose_runtime(workload_id: str) -> tuple[dict[str, Any], str | None]:
    runtime = runtime_config(workload_id)
    if runtime.get("type") != "docker-compose":
        return runtime, "operation requires docker-compose runtime"
    if not runtime.get("composePath") or not runtime.get("composeProject"):
        return runtime, "missing composePath or composeProject"
    return runtime, None


def sanitize_log_text(text: str, *, max_lines: int = MAX_LOG_LINES, max_bytes: int = MAX_LOG_BYTES) -> tuple[list[str], bool]:
    redacted = False
    clipped = text.encode(errors="replace")[:max_bytes].decode(errors="replace")
    if len(clipped) < len(text):
        redacted = True
    lines: list[str] = []
    for raw_line in clipped.splitlines()[-max_lines:]:
        line = ANSI.sub("", raw_line)
        if SECRET_LINE.search(line):
            lines.append("[redacted secret-like log line]")
            redacted = True
            continue
        replaced = TOKEN_PAIR.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", line)
        if replaced != line:
            redacted = True
        if len(replaced) > MAX_LINE_CHARS:
            replaced = replaced[:MAX_LINE_CHARS] + "...[truncated]"
            redacted = True
        lines.append(replaced)
    return lines, redacted


def logs_preview(workload_id: str, *, max_lines: int = MAX_LOG_LINES) -> dict[str, Any]:
    if _workload(workload_id) is None:
        return _blocked("logs-preview", workload_id, "unknown workload", status=404)
    if not operation_allowed(workload_id, "logsAllowed"):
        audit("logs.preview", workload_id, "blocked", reason="logs not allowed")
        return _blocked("logs-preview", workload_id, "logs not allowed")
    runtime, reason = _compose_runtime(workload_id)
    if reason:
        audit("logs.preview", workload_id, "blocked", reason=reason)
        return _blocked("logs-preview", workload_id, reason)

    tail = max(1, min(int(max_lines or MAX_LOG_LINES), MAX_LOG_LINES))
    command = [
        "docker",
        "compose",
        "-f",
        str(runtime["composePath"]),
        "-p",
        str(runtime["composeProject"]),
        "logs",
        "--tail",
        str(tail),
    ]
    service = str(runtime.get("service", ""))
    if service:
        command.append(service)
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=8)
    output = result.stdout if result.returncode == 0 else result.stderr
    lines, redacted = sanitize_log_text(output, max_lines=tail)
    audit("logs.preview", workload_id, "ok" if result.returncode == 0 else "failed", exitCode=result.returncode, lines=len(lines))
    return {
        **_base("logs-preview", workload_id),
        "allowed": result.returncode == 0,
        "commandClass": "docker-compose-logs",
        "maxLines": tail,
        "maxBytes": MAX_LOG_BYTES,
        "lines": lines,
        "redacted": True,
        "summary": "Logs preview returned sanitized capped output." if result.returncode == 0 else "Logs preview failed.",
        "warnings": ["output was redacted or truncated"] if redacted else [],
    }


def restart_preview(workload_id: str) -> dict[str, Any]:
    workload = _workload(workload_id)
    if workload is None:
        return _blocked("restart-preview", workload_id, "unknown workload", status=404)
    runtime, reason = _compose_runtime(workload_id)
    allowed = operation_allowed(workload_id, "restartAllowed") and reason is None
    health = _health(workload)
    result = {
        **_base("restart-preview", workload_id),
        "allowed": allowed,
        "requiresConfirmation": True,
        "confirmationPhrase": workload_id,
        "commandClass": "docker-compose-restart",
        "runtime": {
            "type": str(runtime.get("type", "")),
            "composeProject": str(runtime.get("composeProject", "")),
            "service": str(runtime.get("service", "")),
        },
        "health": health,
        "summary": f"Restart is {'allowed' if allowed else 'blocked'} for {workload_id}.",
        "reason": "" if allowed else reason or "restart not allowed",
    }
    audit("restart.preview", workload_id, "ok" if allowed else "blocked", reason=result["reason"])
    return result


def wait_for_health(workload: dict[str, Any], timeout: float) -> dict[str, Any]:
    health = workload.get("health", {})
    expected = str(health.get("expectedStatus", ""))
    url = str(health.get("url", ""))
    deadline = time.time() + max(timeout, 1)
    last_status = "fail"
    last_detail = "timeout"
    while time.time() <= deadline:
        status, detail = http_status(url, timeout=min(3.0, max(timeout, 1)))
        last_status, last_detail = status, detail
        if status == expected:
            return {"ok": True, "url": url, "expectedStatus": expected, "status": status, "detail": detail}
        time.sleep(1)
    return {"ok": False, "url": url, "expectedStatus": expected, "status": last_status, "detail": last_detail}


def restart_apply(workload_id: str, *, confirmation: str, health_timeout: float = 20.0) -> dict[str, Any]:
    workload = _workload(workload_id)
    if workload is None:
        return _blocked("restart-apply", workload_id, "unknown workload", status=404)
    if confirmation != workload_id:
        audit("restart.apply", workload_id, "blocked", reason="confirmation required")
        return _blocked("restart-apply", workload_id, "exact workload id confirmation required")
    preview = restart_preview(workload_id)
    if not preview.get("allowed"):
        audit("restart.apply", workload_id, "blocked", reason=preview.get("reason", "restart not allowed"))
        return _blocked("restart-apply", workload_id, str(preview.get("reason", "restart not allowed")))

    runtime, _ = _compose_runtime(workload_id)
    command = ["docker", "compose", "-f", str(runtime["composePath"]), "-p", str(runtime["composeProject"]), "restart"]
    service = str(runtime.get("service", ""))
    if service:
        command.append(service)
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=max(health_timeout, 5))
    if result.returncode != 0:
        audit("restart.apply", workload_id, "failed", exitCode=result.returncode)
        return _blocked("restart-apply", workload_id, "restart command failed", status=500)
    health = wait_for_health(workload, health_timeout)
    audit("restart.apply", workload_id, "ok" if health["ok"] else "failed", status=health["status"], detail=health["detail"])
    return {
        **_base("restart-apply", workload_id),
        "allowed": True,
        "commandClass": "docker-compose-restart",
        "health": health,
        "summary": "Restart applied and health verified." if health["ok"] else "Restart applied but health verification failed.",
    }


def backup_preview(workload_id: str) -> dict[str, Any]:
    if _workload(workload_id) is None:
        return _blocked("backup-preview", workload_id, "unknown workload", status=404)
    manifest = load_manifest(workload_id)
    backup = manifest.get("backup", {}) if manifest else {}
    allowed = operation_allowed(workload_id, "backupAllowed") or bool(backup.get("backupAllowed", False))
    destination = str(backup.get("destination", ""))
    approved_root = f"/srv/oreo-cloud/runtime/backups/{workload_id}"
    destination_ok = bool(destination) and destination.startswith(approved_root)
    warnings = []
    if not allowed:
        warnings.append("backup is disabled by manifest")
    if not destination_ok:
        warnings.append(f"backup destination must be under {approved_root}")
    result = {
        **_base("backup-preview", workload_id),
        "allowed": allowed and destination_ok,
        "requiresConfirmation": True,
        "confirmationPhrase": workload_id,
        "commandClass": "oreo-backup-run",
        "destination": destination,
        "include": {
            "source": bool(backup.get("source", False)),
            "env": bool(backup.get("env", False)),
            "volumes": bool(backup.get("namedVolumes", []) or backup.get("bindMounts", [])),
            "database": str(backup.get("database", {}).get("type", "none")) != "none",
        },
        "warnings": warnings,
        "summary": "Backup is allowed by manifest." if allowed and destination_ok else "Backup is blocked by manifest or destination policy.",
    }
    audit("backup.preview", workload_id, "ok" if result["allowed"] else "blocked", destination=destination)
    return result


def backup_apply(workload_id: str, *, confirmation: str) -> dict[str, Any]:
    if confirmation != workload_id:
        audit("backup.apply", workload_id, "blocked", reason="confirmation required")
        return _blocked("backup-apply", workload_id, "exact workload id confirmation required")
    preview = backup_preview(workload_id)
    if not preview.get("allowed"):
        audit("backup.apply", workload_id, "blocked", reason="backup preview denied")
        return _blocked("backup-apply", workload_id, "backup is not allowed by manifest or destination policy")
    script = Path(__file__).resolve().parent / "oreo-backup-run"
    result = subprocess.run([str(script), workload_id, "--confirm", workload_id], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if result.returncode != 0:
        audit("backup.apply", workload_id, "failed", exitCode=result.returncode)
        return _blocked("backup-apply", workload_id, "backup command failed", status=500)
    artifact = result.stdout.strip().removeprefix("backup written to ").strip()
    audit("backup.apply", workload_id, "ok", artifact=artifact)
    return {
        **_base("backup-apply", workload_id),
        "allowed": True,
        "commandClass": "oreo-backup-run",
        "artifactPath": artifact,
        "summary": "Backup artifact created.",
    }


def actions_catalog() -> dict[str, Any]:
    return {
        "actions": [
            {"id": "logs-preview", "method": "POST", "requiresAuth": True, "mutates": False},
            {"id": "restart-preview", "method": "POST", "requiresAuth": True, "mutates": False},
            {"id": "restart-apply", "method": "POST", "requiresAuth": True, "mutates": True, "requiresConfirmation": True},
            {"id": "backup-preview", "method": "POST", "requiresAuth": True, "mutates": False},
            {"id": "backup-apply", "method": "POST", "requiresAuth": True, "mutates": True, "requiresConfirmation": True},
        ]
    }
