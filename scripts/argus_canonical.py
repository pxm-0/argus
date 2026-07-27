from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from argus_operations import canonical_json


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.is_file() else {}


def _list_record(items: Any, workload_id: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("id") == workload_id:
            return item
    return None


def _map_record(items: Any, workload_id: str) -> Any:
    return items.get(workload_id) if isinstance(items, dict) else None


def canonical_records(root: Path, workload_id: str) -> dict[str, Any]:
    config = root / "config"
    workloads = _load(config / "workloads.json")
    privacy = _load(config / "privacy.json")
    access = _load(config / "access.json")
    classification = _load(config / "argus" / "workload-classification.json")
    routes = _load(config / "routes.json")
    manifest = _load(root / "workloads" / workload_id / "manifest.json")
    policy = _load(config / "policy.json")
    return {
        "workload": _list_record(workloads.get("workloads"), workload_id),
        "privacy": _map_record(privacy.get("workloads"), workload_id),
        "access": _map_record(access.get("workloads"), workload_id),
        "classification": _map_record(
            classification.get("workloads"),
            workload_id,
        ),
        "manifest": manifest or None,
        "policy": policy,
        "route": _map_record(routes.get("workloadRoutes"), workload_id),
    }


def canonical_revision(root: Path, workload_id: str) -> str:
    encoded = canonical_json(canonical_records(root, workload_id)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_policy_version(root: Path, workload_id: str) -> str:
    policy = _load(root / "config" / "policy.json")
    manifest = _load(root / "workloads" / workload_id / "manifest.json")
    payload = {
        "policy": policy,
        "operations": manifest.get("operations"),
        "security": manifest.get("security"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
