"""Fail-closed Argus V1 entity classification and SQLite repository primitives."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REALMS = {"unclassified", "personal", "work"}
ZONES = {"legacy", "sandbox", "managed"}
STAGES = {"none", "dev", "staging", "production"}
DOMAIN_KINDS = {"management", "legacy", "workload"}


class StateError(ValueError):
    """Raised when an entity cannot be safely represented or persisted."""


@dataclass(frozen=True)
class Classification:
    realm: str | None
    zone: str | None
    stage: str | None
    trust_domain: str
    domain_kind: str

    def validate(self) -> None:
        if self.domain_kind not in DOMAIN_KINDS:
            raise StateError("unknown trust-domain kind")
        if not self.trust_domain:
            raise StateError("trust domain is required")
        if self.domain_kind == "management":
            if any(value is not None for value in (self.realm, self.zone, self.stage)):
                raise StateError("management domains cannot carry workload classification")
            return
        if self.realm not in REALMS or self.zone not in ZONES or self.stage not in STAGES:
            raise StateError("workload classification has an invalid realm, zone, or stage")
        if self.domain_kind == "legacy":
            if (self.realm, self.zone, self.stage) != ("unclassified", "legacy", "none"):
                raise StateError("legacy domains must be unclassified, legacy, and stage none")
        elif self.realm == "unclassified" or self.zone == "legacy":
            raise StateError("workload domains require personal/work and sandbox/managed classification")

    def as_dict(self) -> dict[str, str | None]:
        self.validate()
        return {
            "realm": self.realm,
            "zone": self.zone,
            "stage": self.stage,
            "trustDomain": self.trust_domain,
            "domainKind": self.domain_kind,
        }


@dataclass(frozen=True)
class EntityState:
    declared: Classification
    observed: Classification
    effective: Classification

    def validate(self) -> None:
        self.declared.validate()
        self.observed.validate()
        self.effective.validate()
        if self.declared.domain_kind != self.observed.domain_kind:
            raise StateError("declared and observed domain kinds differ")
        if self.effective != self.observed:
            raise StateError("effective state must reflect the observed state until reconciliation exists")

    def as_dict(self) -> dict[str, dict[str, str | None]]:
        self.validate()
        return {
            "declared": self.declared.as_dict(),
            "observed": self.observed.as_dict(),
            "effective": self.effective.as_dict(),
        }


class SQLiteRepository:
    """The sole M1 writer for classified entities in a SQLite transaction."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_kind TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    state_json TEXT NOT NULL
                );
                """
            )

    def put_entity(self, entity_id: str, entity_kind: str, state: EntityState, *, expected_revision: int | None) -> int:
        if not entity_id or not entity_kind:
            raise StateError("entity ID and kind are required")
        encoded = json.dumps(state.as_dict(), separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT revision FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
            actual = None if current is None else int(current["revision"])
            if actual != expected_revision:
                raise StateError(f"revision mismatch: expected {expected_revision!r}, got {actual!r}")
            revision = 1 if actual is None else actual + 1
            connection.execute(
                "INSERT INTO entities(entity_id, entity_kind, revision, state_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(entity_id) DO UPDATE SET entity_kind=excluded.entity_kind, revision=excluded.revision, state_json=excluded.state_json",
                (entity_id, entity_kind, revision, encoded),
            )
            return revision

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT entity_id, entity_kind, revision, state_json FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["entity_id"],
            "kind": row["entity_kind"],
            "revision": row["revision"],
            "state": json.loads(row["state_json"]),
        }
