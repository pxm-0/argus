"""Serialized, fail-closed D1–D5 configured-estate refresh coordination."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from argus_collectors import CollectorCallable, CollectorError, CollectorScheduler, collect_from_socket
from argus_observations import ObservationError, ObservationRepository, load_registry
from argus_reconciliation import reconcile


RUN_ID = re.compile(r"^refresh-[0-9a-f-]{36}$")
STATUS_VERSION = 1
MAX_PENDING_REQUESTS = 8
RUNNER_UID = 1000


class EstateRefreshError(ValueError):
    pass


def require_runner_identity() -> None:
    """Prevent privileged ad-hoc refreshes from breaking collector peer auth."""
    if os.geteuid() != RUNNER_UID:
        raise EstateRefreshError("estate refresh runner must execute as uid 1000")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def paths(root: Path) -> dict[str, Path]:
    runtime = root / "runtime" / "argus" / "estate-refresh"
    return {
        "database": root / "runtime" / "argus" / "observations.sqlite3",
        "runtime": runtime,
        "requests": runtime / "requests",
        "status": runtime / "status",
        "latest": runtime / "latest.json",
        "lock": runtime / "refresh.lock",
        "registry": root / "config" / "argus" / "observation-sources.json",
    }


def _ensure_runtime(root: Path) -> dict[str, Path]:
    result = paths(root)
    for key in ("runtime", "requests", "status"):
        directory = result[key]
        if directory.exists() or directory.is_symlink():
            if directory.is_symlink() or not directory.is_dir():
                raise EstateRefreshError("estate refresh runtime path must be a directory")
        else:
            directory.mkdir(mode=0o770, parents=True, exist_ok=False)
        if directory.is_symlink():
            raise EstateRefreshError("estate refresh runtime path must not be a symlink")
    return result


def _atomic_json(path: Path, value: dict[str, Any], *, mode: int = 0o640) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_run_id(value: str) -> str:
    if not RUN_ID.fullmatch(value):
        raise EstateRefreshError("estate refresh ID is invalid")
    return value


def create_request(root: Path, *, requested_by: str) -> dict[str, Any]:
    if not requested_by or len(requested_by) > 128:
        raise EstateRefreshError("estate refresh requester is invalid")
    directories = _ensure_runtime(root)
    run_id = f"refresh-{uuid.uuid4()}"
    request = {
        "schemaVersion": STATUS_VERSION,
        "runId": run_id,
        "requestedAt": utc_now(),
        "requestedBy": requested_by,
        "state": "queued",
    }
    _atomic_json(directories["requests"] / f"{run_id}.json", request)
    return {
        "schemaVersion": STATUS_VERSION,
        "runId": run_id,
        "state": "queued",
        "statusUrl": f"/api/estate/refresh/{run_id}",
    }


def read_status(root: Path, run_id: str | None = None) -> dict[str, Any] | None:
    directories = paths(root)
    if run_id is None:
        path = directories["latest"]
    else:
        path = directories["status"] / f"{_safe_run_id(run_id)}.json"
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return None
        content = path.read_text(encoding="utf-8")
        value = json.loads(content)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schemaVersion") != STATUS_VERSION:
        return None
    return value


def read_request(root: Path, run_id: str) -> dict[str, Any] | None:
    """Return a queued inert request without exposing its caller identity."""
    directories = paths(root)
    path = directories["requests"] / f"{_safe_run_id(run_id)}.json"
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != STATUS_VERSION
        or value.get("runId") != run_id
        or value.get("state") != "queued"
        or not isinstance(value.get("requestedAt"), str)
    ):
        return None
    return {
        "schemaVersion": STATUS_VERSION,
        "runId": run_id,
        "state": "queued",
        "requestedAt": value["requestedAt"],
        "safeToMoveWorkloads": False,
    }


def _write_status(root: Path, result: dict[str, Any]) -> None:
    directories = _ensure_runtime(root)
    run_id = _safe_run_id(str(result.get("runId", "")))
    _atomic_json(directories["status"] / f"{run_id}.json", result)
    _atomic_json(directories["latest"], result)


def _database_mode(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.is_file() and not candidate.is_symlink():
            os.chmod(candidate, 0o660)


def run_refresh(
    root: Path,
    run_id: str,
    *,
    explicit_clock: str | None = None,
    collector: CollectorCallable | None = None,
) -> dict[str, Any]:
    """Refresh every configured source while holding the sole scheduler lock."""
    run_id = _safe_run_id(run_id)
    root = root.resolve()
    directories = _ensure_runtime(root)
    now = explicit_clock or utc_now()
    lock = directories["lock"].open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EstateRefreshError("estate refresh is already running") from exc
        registry = load_registry(directories["registry"], root)
        with ObservationRepository(directories["database"]) as repository:
            recovered = repository.recover_interrupted(terminal_at=now)
            scheduler = CollectorScheduler(
                repository,
                registry,
                collector=collector or collect_from_socket,
            )
            outcome = scheduler.refresh(refresh_id=run_id, explicit_clock=now)
            reconciliation = reconcile(root, repository, registry, explicit_clock=now)
            pruned_runs = repository.prune()
        _database_mode(directories["database"])
        result = {
            "schemaVersion": STATUS_VERSION,
            "runId": run_id,
            "state": "completed" if outcome["status"] == "completed" else "partial",
            "requestedAt": now,
            "finishedAt": utc_now(),
            "recoveredInterruptedRuns": recovered,
            "collection": outcome,
            "coverage": reconciliation["coverage"],
            "reconciliationStatus": reconciliation["status"],
            "safeToMoveWorkloads": reconciliation["safeToMoveWorkloads"],
            "evidenceDigest": reconciliation["evidenceDigest"],
            "prunedRuns": pruned_runs,
        }
    except (CollectorError, ObservationError, EstateRefreshError, OSError, ValueError) as exc:
        result = {
            "schemaVersion": STATUS_VERSION,
            "runId": run_id,
            "state": "failed",
            "requestedAt": now,
            "finishedAt": utc_now(),
            "error": exc.__class__.__name__,
            "safeToMoveWorkloads": False,
        }
    finally:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        finally:
            lock.close()
    _write_status(root, result)
    return result


def run_pending(
    root: Path,
    *,
    timer: bool = False,
    collector: CollectorCallable | None = None,
) -> list[dict[str, Any]]:
    directories = _ensure_runtime(root)
    requests: list[tuple[str, Path | None]] = []
    for path in sorted(directories["requests"].glob("refresh-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            run_id = _safe_run_id(str(value.get("runId", "")))
        except (OSError, json.JSONDecodeError, EstateRefreshError):
            continue
        requests.append((run_id, path))
    if timer and not requests:
        requests.append((f"refresh-{uuid.uuid4()}", None))
    outcomes: list[dict[str, Any]] = []
    for run_id, request_path in requests[:MAX_PENDING_REQUESTS]:
        result = run_refresh(root, run_id, collector=collector)
        outcomes.append(result)
        if request_path is not None:
            request_path.unlink(missing_ok=True)
    return outcomes


def status_summary(root: Path) -> dict[str, Any]:
    result = read_status(root)
    if result is None:
        return {"schemaVersion": STATUS_VERSION, "state": "never-run", "safeToMoveWorkloads": False}
    return result
