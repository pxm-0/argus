"""Reviewed access baseline plus the server-applied effective overlay (D028).

Git keeps config/access.json (desired, urls and a non-Cloudflare baseline). The server writes only
effective, lastAppliedAt and lastError, into the ignored config/access.effective.json. Every reader
sees the merge. A malformed overlay raises; a missing one gives the baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRACKED_NAME = "access.json"
OVERLAY_NAME = "access.effective.json"
OVERLAY_VERSION = 1
EFFECTIVE_FIELDS = ("effective", "lastAppliedAt", "lastError")


class AccessStateError(ValueError):
    """The access baseline or its effective overlay cannot be trusted."""


def empty_overlay() -> dict[str, Any]:
    return {"version": OVERLAY_VERSION, "workloads": {}}


def validate_overlay(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"version", "workloads"}:
        raise AccessStateError("access overlay must hold exactly version and workloads")
    if value["version"] != OVERLAY_VERSION or isinstance(value["version"], bool):
        raise AccessStateError("access overlay has an unsupported version")
    workloads = value["workloads"]
    if not isinstance(workloads, dict):
        raise AccessStateError("access overlay workloads must be an object")
    for workload_id, entry in workloads.items():
        if not isinstance(entry, dict) or set(entry) != set(EFFECTIVE_FIELDS):
            raise AccessStateError(f"access overlay entry {workload_id} must hold exactly {', '.join(EFFECTIVE_FIELDS)}")
        if not all(isinstance(entry[field], str) for field in EFFECTIVE_FIELDS):
            raise AccessStateError(f"access overlay entry {workload_id} must hold only strings")
    return value


def read_overlay(config_dir: Path) -> dict[str, Any]:
    path = config_dir / OVERLAY_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_overlay()
    except (OSError, UnicodeDecodeError) as exc:
        raise AccessStateError(f"access overlay is unreadable: {exc.__class__.__name__}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AccessStateError(f"access overlay is not valid JSON: {exc}") from exc
    return validate_overlay(value)


def merge_access(tracked: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return tracked with the overlay's three fields applied per known workload; inputs are not mutated."""
    if not isinstance(tracked, dict):
        raise AccessStateError("tracked access registry must be an object")
    states = tracked.get("states", [])
    workloads = tracked.get("workloads")
    if not isinstance(workloads, dict) or not isinstance(states, list):
        raise AccessStateError("tracked access registry needs a workloads object and a states list")
    merged = json.loads(json.dumps(tracked))
    for workload_id, entry in overlay["workloads"].items():
        if workload_id not in workloads:
            continue  # orphans are ignored here; doctor warns about them
        if not isinstance(workloads[workload_id], dict) or entry["effective"] not in states:
            raise AccessStateError(f"access overlay state for {workload_id} is not a tracked access state of a tracked entry")
        merged["workloads"][workload_id] = {**merged["workloads"][workload_id], **{field: entry[field] for field in EFFECTIVE_FIELDS}}
    return merged


def read_tracked(config_dir: Path) -> dict[str, Any]:
    path = config_dir / TRACKED_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccessStateError(f"tracked access registry is unavailable or malformed: {exc.__class__.__name__}") from exc
    if not isinstance(value, dict):
        raise AccessStateError("tracked access registry must be an object")
    return value


def load_access(config_dir: Path) -> dict[str, Any]:
    return merge_access(read_tracked(config_dir), read_overlay(config_dir))


def orphans(tracked: dict[str, Any], overlay: dict[str, Any]) -> list[str]:
    return sorted(set(overlay["workloads"]) - set(tracked.get("workloads", {})))
