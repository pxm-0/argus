from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from argus_admission import evaluate_current
from argus_common import audit, by_id, http_status, load_manifest, root, runtime_config


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


def _verify_backup_artifact(latest: Path, workload_id: str) -> bool:
    required = ("manifest.json", "files.tar.gz", "checksums.sha256", "restore-plan.md", "backup-summary.json")
    if any(not (latest / name).is_file() for name in required):
        return False
    try:
        summary = json.loads((latest / "backup-summary.json").read_text())
        rows = (latest / "checksums.sha256").read_text().splitlines()
        artifact_root = latest.resolve()
        if summary.get("workloadId") != workload_id or not rows:
            return False
        verified_names: set[str] = set()
        for row in rows:
            expected, separator, name = row.partition("  ")
            target = (latest / name).resolve()
            if (
                not separator
                or name in verified_names
                or artifact_root not in target.parents
                or not target.is_file()
            ):
                return False
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                return False
            verified_names.add(name)
        if not (set(required) - {"checksums.sha256"}).issubset(verified_names):
            return False
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return True


def _backup_artifact_evidence(workload_id: str, backup: dict[str, Any]) -> tuple[bool, str]:
    destination = Path(str(backup.get("destination", "")))
    if destination != Path(f"/srv/argus/runtime/backups/{workload_id}") or not destination.is_dir():
        return False, ""
    runs = sorted(path for path in destination.iterdir() if path.is_dir())
    if not runs:
        return False, ""
    latest = runs[-1]
    if not _verify_backup_artifact(latest, workload_id):
        return False, ""
    return True, latest.name


def _health_evidence(health: dict[str, Any]) -> bool:
    url = str(health.get("url", ""))
    expected = health.get("expectedStatus")
    if not url or not isinstance(expected, int):
        return False
    status, _detail = http_status(url, float(health.get("timeoutSeconds", 3)))
    return status == str(expected)


def migration_preflight(
    workload_id: str,
    *,
    record_audit: bool = True,
    actor: str = "local-cli",
) -> dict[str, Any]:
    """Return a redacted, read-only migration readiness assessment."""
    admission = evaluate_current(root(), workload_id, "migration.preflight")
    if not admission.allowed:
        return _blocked(
            "migration-preflight",
            workload_id,
            admission.decision_code,
            status=404 if admission.decision_code == "unknown-workload" else 403,
        )
    workload = _workload(workload_id)
    if workload is None:
        return _blocked("migration-preflight", workload_id, "unknown-workload", status=404)
    manifest = load_manifest(workload_id)
    migration = manifest.get("migration", {})
    status = str(migration.get("status", workload.get("migration", {}).get("status", "")))
    if status not in {"planned", "rolled-back"}:
        return _blocked(
            "migration-preflight",
            workload_id,
            f"migration status {status or 'unknown'} is not a migration candidate",
        )

    runtime = runtime_config(workload_id)
    backup = manifest.get("backup", {})
    source_path = str(
        migration.get("originalPath")
        or workload.get("migration", {}).get("originalPath")
        or workload.get("paths", {}).get("legacy")
        or ""
    )
    target_path = str(manifest.get("sourcePath") or workload.get("paths", {}).get("source") or "")
    compose_path = str(runtime.get("composePath", ""))
    blockers: list[str] = []
    if not source_path:
        blockers.append("Source path is not recorded.")
    elif not Path(source_path).is_dir():
        blockers.append("Recorded source path is unavailable.")
    if target_path != f"/srv/argus/workloads/{workload_id}/source":
        blockers.append("Target source path is outside the canonical workload root.")
    elif not Path(target_path).is_dir():
        blockers.append("Target source path is unavailable.")
    if runtime.get("type") != "docker-compose":
        blockers.append("Runtime is not Docker Compose.")
    if not compose_path:
        blockers.append("Target Compose path is not recorded.")
    elif not Path(compose_path).is_file():
        blockers.append("Target Compose file is unavailable.")
    if not runtime.get("composeProject"):
        blockers.append("Compose project name is not recorded.")
    if not backup.get("backupAllowed"):
        blockers.append("Backup execution is not approved.")
    if not backup.get("restoreAllowed"):
        blockers.append("Restore execution is not approved.")
    if not backup.get("restoreTested"):
        blockers.append("An isolated restore test is not recorded.")
    artifact_verified, artifact_id = _backup_artifact_evidence(workload_id, backup)
    if not artifact_verified:
        blockers.append("A checksum-verified backup artifact is unavailable.")
    if not str(migration.get("rollback", "")).strip():
        blockers.append("Rollback contract is not recorded.")
    health = manifest.get("health", {})
    health_verified = False
    if not health.get("url"):
        blockers.append("Target health URL is not recorded.")
    else:
        health_verified = _health_evidence(health)
        if not health_verified:
            blockers.append("Target health check did not return the expected status.")

    result = {
        **_base("migration-preflight", workload_id),
        "allowed": True,
        "migrationStatus": status,
        "readyForCutover": not blockers,
        "blockers": blockers,
        "sourcePathRecorded": bool(source_path),
        "targetPath": target_path,
        "composeProject": str(runtime.get("composeProject", "")),
        "backupApproved": bool(backup.get("backupAllowed")),
        "restoreApproved": bool(backup.get("restoreAllowed")),
        "restoreTested": bool(backup.get("restoreTested")),
        "backupArtifactVerified": artifact_verified,
        "backupArtifactId": artifact_id,
        "healthVerified": health_verified,
        "rollbackRecorded": bool(str(migration.get("rollback", "")).strip()),
        "summary": (
            "Migration preflight passed; cutover still requires a separately approved operation."
            if not blockers
            else f"Migration preflight found {len(blockers)} blocking condition(s)."
        ),
    }
    if record_audit:
        audit(
            "migration.preflight",
            workload_id,
            "ok" if not blockers else "blocked",
            actor=actor,
            blockerCount=len(blockers),
        )
    return result


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
    admission = evaluate_current(root(), workload_id, "logs.preview")
    if not admission.allowed:
        audit("logs.preview", workload_id, "blocked", reason=admission.decision_code)
        return _blocked(
            "logs-preview",
            workload_id,
            admission.decision_code,
            status=404 if admission.decision_code == "unknown-workload" else 403,
        )
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
    admission = evaluate_current(root(), workload_id, "workload.restart")
    if not admission.allowed:
        return _blocked(
            "restart-preview",
            workload_id,
            admission.decision_code,
            status=404 if admission.decision_code == "unknown-workload" else 403,
        )
    workload = _workload(workload_id)
    if workload is None:
        return _blocked("restart-preview", workload_id, "unknown-workload", status=404)
    runtime, reason = _compose_runtime(workload_id)
    allowed = admission.allowed and reason is None
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
        "reason": "" if allowed else reason or admission.decision_code,
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
    admission = evaluate_current(root(), workload_id, "backup.create")
    if not admission.allowed:
        return _blocked(
            "backup-preview",
            workload_id,
            admission.decision_code,
            status=404 if admission.decision_code == "unknown-workload" else 403,
        )
    manifest = load_manifest(workload_id)
    backup = manifest.get("backup", {}) if manifest else {}
    allowed = True
    destination = str(backup.get("destination", ""))
    approved_root = f"/srv/argus/runtime/backups/{workload_id}"
    destination_ok = bool(destination) and destination.startswith(approved_root)
    warnings = []
    if not destination_ok:
        warnings.append(f"backup destination must be under {approved_root}")
    result = {
        **_base("backup-preview", workload_id),
        "allowed": allowed and destination_ok,
        "requiresConfirmation": True,
        "confirmationPhrase": workload_id,
        "commandClass": "argus-backup-run",
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
    script = Path(__file__).resolve().parent / "argus-backup-run"
    result = subprocess.run([str(script), workload_id, "--confirm", workload_id], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if result.returncode != 0:
        audit("backup.apply", workload_id, "failed", exitCode=result.returncode)
        return _blocked("backup-apply", workload_id, "backup command failed", status=500)
    artifact = result.stdout.strip().removeprefix("backup written to ").strip()
    audit("backup.apply", workload_id, "ok", artifact=artifact)
    return {
        **_base("backup-apply", workload_id),
        "allowed": True,
        "commandClass": "argus-backup-run",
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
