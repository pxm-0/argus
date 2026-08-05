"""Fixture-backed reference adapter for the normalized observation boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from argus_observations import ObservationError, SourceSpec


def adapt_fixture(path: Path, source: SourceSpec) -> list[dict[str, Any]]:
    """Map one pinned native fixture; repository consumers never see native fields."""
    if "fixture:reference-compose:v1" not in source.allowlist["apis"]:
        raise ObservationError("source does not allow the reference fixture adapter")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"fixtureVersion", "collector", "records"}:
        raise ObservationError("fixture envelope has unknown or missing fields")
    if payload["fixtureVersion"] != 1 or payload["collector"] != "reference-compose":
        raise ObservationError("unsupported fixture adapter input")
    if not isinstance(payload["records"], list):
        raise ObservationError("fixture records must be a list")
    native_records = payload["records"]
    for native in native_records:
        if not isinstance(native, dict) or set(native) != {
            "object_type", "object_id", "captured_at", "name", "lifecycle", "project"
        }:
            raise ObservationError("reference fixture record has unknown or missing fields")
    native_records = sorted(
        native_records,
        key=lambda item: (str(item["object_type"]), str(item["object_id"])),
    )
    records = []
    for ordinal, native in enumerate(native_records):
        records.append({
            "schemaVersion": 1,
            "resourceKind": native["object_type"],
            "nativeId": native["object_id"],
            "observedAt": native["captured_at"],
            "attributes": {
                "lifecycle": native["lifecycle"],
                "name": native["name"],
                "project": native["project"],
            },
            "provenance": {
                "adapter": "reference-compose",
                "adapterVersion": "1",
                "ordinal": ordinal,
            },
        })
    return records
