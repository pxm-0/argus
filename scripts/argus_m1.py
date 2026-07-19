"""M1 control-plane guardrails while the single mutation writer is introduced."""

from __future__ import annotations

from argus_state import AccessMutationWriter, PrivacyMutationWriter, StateError
from oreo_common import root


def deny_direct_legacy_mutation(operation: str) -> None:
    """Fail closed until the operation has a dual-schema writer transform."""
    if not operation:
        raise StateError("M1 mutation operation is required")
    raise StateError(
        f"Argus M1 writer cutover: direct {operation} mutation is disabled until its dual-schema transform is available"
    )


def privacy_writer() -> PrivacyMutationWriter:
    """Return the sole M1 privacy writer; its state is private runtime data."""
    runtime = root() / "runtime" / "argus" / "m1"
    return PrivacyMutationWriter(root() / "config" / "privacy.json", runtime / "state.sqlite3", runtime / "audit.sqlite3", runtime / "privacy-journal.jsonl")


def access_writer() -> AccessMutationWriter:
    """Return the sole M1 access writer; its state is private runtime data."""
    runtime = root() / "runtime" / "argus" / "m1"
    return AccessMutationWriter(root() / "config" / "access.json", runtime / "state.sqlite3", runtime / "audit.sqlite3", runtime / "access-journal.jsonl")
