"""M1 control-plane guardrails while the single mutation writer is introduced."""

from __future__ import annotations

from argus_state import StateError


def deny_direct_legacy_mutation(operation: str) -> None:
    """Fail closed until the operation has a dual-schema writer transform."""
    if not operation:
        raise StateError("M1 mutation operation is required")
    raise StateError(
        f"Argus M1 writer cutover: direct {operation} mutation is disabled until its dual-schema transform is available"
    )
