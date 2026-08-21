from __future__ import annotations

from pathlib import Path
from typing import Any

from argus_admission import (
    canonical_records as _canonical_records,
    canonical_revision,
    policy_version,
)


def canonical_records(root: Path, workload_id: str) -> dict[str, Any]:
    """Compatibility export for callers migrating to argus_admission."""
    return _canonical_records(root, workload_id)


def canonical_policy_version(root: Path, workload_id: str = "") -> str:
    """Return the reviewed policy version; workload_id is retained for API parity."""
    del workload_id
    return policy_version(root)
