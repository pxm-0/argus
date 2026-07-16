from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_state import Classification, EntityState, SQLiteRepository, StateError  # noqa: E402


def legacy() -> Classification:
    return Classification("unclassified", "legacy", "none", "legacy-rootful", "legacy")


class ArgusStateTest(unittest.TestCase):
    def test_domain_constraints_fail_closed(self) -> None:
        legacy().validate()
        with self.assertRaises(StateError):
            Classification("personal", "legacy", "none", "legacy-rootful", "legacy").validate()
        with self.assertRaises(StateError):
            Classification(None, None, "none", "argus-management", "management").validate()
        with self.assertRaises(StateError):
            Classification("unclassified", "sandbox", "dev", "workload-a", "workload").validate()

    def test_effective_state_cannot_claim_more_than_observed(self) -> None:
        observed = legacy()
        effective = Classification("personal", "managed", "production", "personal-prod", "workload")
        with self.assertRaises(StateError):
            EntityState(observed, observed, effective).validate()

    def test_repository_requires_matching_revision_and_persists_atomically(self) -> None:
        state = EntityState(legacy(), legacy(), legacy())
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteRepository(Path(directory) / "argus.sqlite3")
            self.assertEqual(1, repository.put_entity("project-a", "project", state, expected_revision=None))
            self.assertEqual(2, repository.put_entity("project-a", "project", state, expected_revision=1))
            with self.assertRaises(StateError):
                repository.put_entity("project-a", "project", state, expected_revision=1)
            self.assertEqual(2, repository.get_entity("project-a")["revision"])
