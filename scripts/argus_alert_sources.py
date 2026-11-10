"""Tolerant readers for the on-disk evidence the alert evaluator and the read-only CLI leaves share.

Every reader returns None (or an empty list) when the file is missing, unreadable or malformed:
absent evidence is "unknown", never a crash and never a secret leak.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from argus_alerting import parse_timestamp

SNAPSHOT_LAST = Path("/var/lib/argus/snapshot-last.json")
BACKUP_STATUS = Path("/var/lib/argus/backup-status.json")
PULL_DIR = Path("/var/backups/argus-snapshots-pull")
MAX_JSON_BYTES = 262144


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default)))


def snapshot_last_path() -> Path:
    return _env_path("ARGUS_SNAPSHOT_LAST", SNAPSHOT_LAST)


def backup_status_path() -> Path:
    return _env_path("ARGUS_BACKUP_STATUS", BACKUP_STATUS)


def pull_dir() -> Path:
    return _env_path("ARGUS_SNAPSHOT_PULL_DIR", PULL_DIR)


def read_json(path: Path) -> Any:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            return None
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None


def read_dict(path: Path) -> dict | None:
    value = read_json(path)
    return value if isinstance(value, dict) else None


def smoke_dir(repo: Path) -> Path:
    return repo / "runtime" / "smoke"


def smoke_latest(repo: Path) -> dict | None:
    return read_dict(smoke_dir(repo) / "latest.json")


def smoke_history(repo: Path, limit: int | None = None) -> list[dict]:
    """Newest-last list of smoke-history.jsonl rows; malformed lines are skipped."""
    try:
        lines = (smoke_dir(repo) / "smoke-history.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows if limit is None else rows[-limit:]


def scalar_fields(document: dict | None) -> dict:
    """Top-level scalars only, so a status file can never smuggle nested payloads into output."""
    if not document:
        return {}
    return {key: value for key, value in document.items() if isinstance(value, (str, int, float, bool)) or value is None}


def pull_archives(directory: Path) -> list[dict]:
    """Snapshot archives in the pull directory, newest first. Unreadable directory -> []."""
    try:
        entries = [entry for entry in directory.iterdir() if entry.is_file() and ".tar" in entry.name and not entry.name.endswith(".pinned")]
        rows = [{"name": entry.name, "size": entry.stat().st_size, "mtime": entry.stat().st_mtime} for entry in entries]
    except OSError:
        return []
    return sorted(rows, key=lambda row: (row["mtime"], row["name"]), reverse=True)


def age_seconds(value: Any, now: float) -> float | None:
    stamp = parse_timestamp(value)
    return None if stamp is None else max(0.0, now - stamp)
