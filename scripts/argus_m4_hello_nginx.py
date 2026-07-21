"""Read-only M4 preflight checks for the hello-nginx personal-sandbox pilot."""
from __future__ import annotations

import hashlib
from typing import Any


class PreflightError(ValueError):
    """Raised when private M4 pilot evidence is incomplete or unsafe."""


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def evaluate_preflight(*, backup_summary: dict[str, Any], backup_manifest: dict[str, Any],
                       archive_digest: str, expected_archive_digest: str,
                       restore_compose_present: bool, source_health: bool,
                       target_daemon_active: bool, target_socket_present: bool,
                       target_empty: bool, target_has_no_tcp_listeners: bool) -> dict[str, Any]:
    """Validate only pre-cutover facts; this function never approves a migration."""
    if backup_summary.get("workloadId") != "hello-nginx" or backup_manifest.get("id") != "hello-nginx":
        raise PreflightError("backup does not belong to hello-nginx")
    if backup_summary.get("sourceIncluded") is not True:
        raise PreflightError("source-only backup is required")
    if any(backup_summary.get(key) is not False for key in ("envIncluded", "volumesIncluded", "databaseIncluded")):
        raise PreflightError("hello-nginx preflight accepts only a source-only backup")
    if not expected_archive_digest.startswith("sha256:") or archive_digest != expected_archive_digest:
        raise PreflightError("backup archive checksum does not match its manifest")
    checks = {
        "backupVerified": True,
        "restoreVerified": restore_compose_present,
        "sourceHealthVerified": source_health,
        "targetDaemonVerified": target_daemon_active and target_socket_present,
        "targetEmptyVerified": target_empty,
        "targetNoTcpListenersVerified": target_has_no_tcp_listeners,
    }
    if not all(checks.values()):
        failed = ", ".join(key for key, value in checks.items() if not value)
        raise PreflightError(f"M4 hello-nginx preflight failed: {failed}")
    return {
        "schemaVersion": 1,
        "workloadId": "hello-nginx",
        "migrationApproved": False,
        "nextGate": "review-controlled-cutover-plan",
        **checks,
    }
