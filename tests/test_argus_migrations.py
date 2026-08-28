from __future__ import annotations

import json
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "scripts"))

from argus_migrations import (  # noqa: E402
    MigrationCoordinator,
    create_draft,
    migration_preview,
    read_draft,
)
from argus_observations import ObservationRepository, load_registry  # noqa: E402
from argus_operations import (  # noqa: E402
    OperationConflict,
    OperationLedger,
    OperationValidationError,
    digest,
)


def preview() -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "workloadId": "demo",
        "sourceTrustDomain": "personal-sandbox",
        "targetTrustDomain": "personal-managed",
        "currentAuthority": "personal-sandbox",
        "eligibleTargets": ["personal-managed"],
        "eligible": True,
        "blockers": [],
        "expectedRevision": "revision",
        "policyVersion": "1",
        "observationDigest": "sha256:" + "a" * 64,
        "sourceMaterialization": {"state": "verified"},
        "statelessContract": {"state": "stateless"},
        "observation": {"state": "verified"},
        "retrySafe": True,
        "phase": "not-started",
        "confirmationPhrase": "migrate demo to personal-managed",
        "rollbackConfirmationPhrase": "rollback migration demo",
    }
    return {**payload, "previewDigest": digest(payload)}


class MigrationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.ledger = OperationLedger(self.root / "operations.sqlite3")
        self.preview = preview()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create_parent(self) -> dict[str, object]:
        parent, created = self.ledger.create_migration(
            workload_id="demo",
            source_trust_domain="personal-sandbox",
            target_trust_domain="personal-managed",
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
            preview=self.preview,
            preview_digest=str(self.preview["previewDigest"]),
            expected_revision="revision",
            policy_version="1",
            observation_digest="sha256:" + "a" * 64,
            idempotency_key="migration-parent",
        )
        self.assertTrue(created)
        return parent

    def test_parent_locks_all_generic_mutations_and_issues_one_bound_child(self) -> None:
        parent = self.create_parent()
        self.assertEqual("awaiting-approval", parent["phase"])
        self.assertEqual(
            ["planned", "preflight", "awaiting-approval"],
            [event["phase"] for event in self.ledger.migration_events(str(parent["migration_id"]))],
        )
        with self.assertRaisesRegex(OperationConflict, "active migration"):
            self.ledger.create(
                workload_id="demo",
                trust_domain="personal-sandbox",
                operation_type="workload.restart",
                requested_by="operator@example.com",
                parameters={},
                preview_digest="preview",
                expected_revision="revision",
                policy_version="1",
                idempotency_key="blocked-generic-mutation",
            )
        self.ledger.approve_migration(
            str(parent["migration_id"]),
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
        )
        child, created = self.ledger.ensure_migration_child(str(parent["migration_id"]))
        repeated, repeated_created = self.ledger.ensure_migration_child(str(parent["migration_id"]))
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(child["operation_id"], repeated["operation_id"])
        self.assertEqual("migration.source-fence", child["operation_type"])
        self.assertEqual("queued", child["state"])
        self.assertIsNotNone(child["approved_at"])
        binding = self.ledger.migration_child_authorized(
            str(child["operation_id"]),
            workload_id="demo",
            operation_type="migration.source-fence",
            trust_domain="personal-sandbox",
            parameters=dict(child["parameters"]),
        )
        self.assertIsNotNone(binding)
        forged = dict(child["parameters"])
        forged["authorityEpoch"] = "00000000-0000-4000-8000-000000000001"
        self.assertIsNone(
            self.ledger.migration_child_authorized(
                str(child["operation_id"]),
                workload_id="demo",
                operation_type="migration.source-fence",
                trust_domain="personal-sandbox",
                parameters=forged,
            )
        )
        with self.assertRaises(OperationValidationError):
            self.ledger.create(
                workload_id="demo",
                trust_domain="personal-sandbox",
                operation_type="migration.source-fence",
                requested_by="operator@example.com",
                parameters=dict(child["parameters"]),
                preview_digest="preview",
                expected_revision="revision",
                policy_version="1",
                idempotency_key="forged-child",
            )

    def test_coordinator_advances_only_from_durable_child_outcomes(self) -> None:
        parent = self.create_parent()
        migration_id = str(parent["migration_id"])
        self.ledger.approve_migration(
            migration_id,
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
        )
        child, _ = self.ledger.ensure_migration_child(migration_id)
        self.ledger.transition(
            str(child["operation_id"]),
            {"queued"},
            "running",
            started_at=int(time.time()),
        )
        self.ledger.transition(
            str(child["operation_id"]),
            {"running"},
            "succeeded",
            finished_at=int(time.time()),
        )
        coordinator = MigrationCoordinator(self.root, self.ledger)
        self.assertEqual("source-fenced", coordinator.advance(migration_id))
        self.assertEqual("target-preparing", coordinator.advance(migration_id))
        self.assertEqual("child-queued", coordinator.advance(migration_id))
        parent = self.ledger.get_migration(migration_id)
        self.assertEqual("target-preparing", parent["phase"])
        target_child = parent["children"][-1]
        self.ledger.transition(
            str(target_child["operation_id"]),
            {"queued"},
            "running",
            started_at=int(time.time()),
        )
        self.ledger.transition(
            str(target_child["operation_id"]),
            {"running"},
            "indeterminate",
            finished_at=int(time.time()),
        )
        self.assertEqual("indeterminate", coordinator.advance(migration_id))
        self.assertEqual("indeterminate", self.ledger.get_migration(migration_id)["phase"])

    def test_coordinator_leaves_a_transient_pass_error_pending(self) -> None:
        self.create_parent()
        coordinator = MigrationCoordinator(self.root, self.ledger)
        with patch.object(coordinator, "advance", side_effect=OSError("temporary evidence unavailable")):
            self.assertEqual(
                {"advanced": 0, "pending": 1, "indeterminate": 0},
                coordinator.run_once(),
            )

    def test_cli_drafts_are_inert_expire_and_carry_no_authority(self) -> None:
        draft = create_draft(self.root, self.preview, action="apply", clock=100)
        self.assertEqual("none", draft["authority"])
        loaded = read_draft(self.root, str(draft["draftId"]), clock=101)
        self.assertEqual("drafted", loaded["state"])
        self.assertEqual("none", loaded["authority"])
        expired = read_draft(self.root, str(draft["draftId"]), clock=100 + 15 * 60)
        self.assertEqual("expired", expired["state"])

    def test_completed_migration_can_enter_the_fenced_rollback_path(self) -> None:
        parent = self.create_parent()
        migration_id = str(parent["migration_id"])
        self.ledger.approve_migration(
            migration_id,
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
        )
        phase = "source-fencing"
        for next_phase in (
            "source-fenced",
            "target-preparing",
            "target-starting",
            "target-verified",
            "route-switching",
            "authority-committed",
            "canonical-committed",
            "verifying",
            "succeeded",
        ):
            self.ledger.transition_migration(
                migration_id,
                {phase},
                next_phase,
                event_detail="test progression",
            )
            phase = next_phase
        rollback = self.ledger.begin_migration_rollback(
            migration_id,
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
        )
        self.assertEqual("rollback-target-stopping", rollback["phase"])
        self.assertIsNone(rollback["finished_at"])
        self.assertEqual(
            "personal-managed",
            self.ledger.runtime_domain("demo", "personal-sandbox"),
        )

    def test_parent_rejects_a_preview_that_is_not_eligible_for_its_target(self) -> None:
        forged = dict(self.preview)
        forged["eligibleTargets"] = []
        forged["previewDigest"] = digest({
            key: value for key, value in forged.items() if key != "previewDigest"
        })
        with self.assertRaisesRegex(OperationValidationError, "target is not eligible"):
            self.ledger.create_migration(
                workload_id="demo",
                source_trust_domain="personal-sandbox",
                target_trust_domain="personal-managed",
                requested_by="operator@example.com",
                originating_session_hash="b" * 64,
                preview=forged,
                preview_digest=str(forged["previewDigest"]),
                expected_revision="revision",
                policy_version="1",
                observation_digest="sha256:" + "a" * 64,
                idempotency_key="forged-parent",
            )

    def test_preview_requires_fresh_source_target_evidence_and_materialization(self) -> None:
        root = self.root / "preview-root"
        (root / "config/argus").mkdir(parents=True)
        (root / "workloads/demo/source").mkdir(parents=True)
        for name in ("observation-sources.json", "legacy-classification.json"):
            (root / "config/argus" / name).write_text(
                (ROOT / "config/argus" / name).read_text()
            )
        (root / "config/workloads.json").write_text(json.dumps({
            "version": 1,
            "workloads": [{
                "id": "demo",
                "name": "Demo",
                "runtime": {"composeProject": "demo"},
            }],
        }))
        (root / "config/policy.json").write_text(json.dumps({"version": 1}))
        (root / "config/access.json").write_text(json.dumps({
            "version": 1, "workloads": {"demo": {"desired": "none", "effective": "none"}},
        }))
        (root / "config/privacy.json").write_text(json.dumps({
            "version": 1, "workloads": {"demo": {"privacy": "internal"}},
        }))
        (root / "config/routes.json").write_text(json.dumps({
            "version": 1, "workloadRoutes": {"demo": {}},
        }))
        (root / "config/argus/workload-classification.json").write_text(json.dumps({
            "schemaVersion": 1,
            "workloads": {"demo": {
                "realm": "personal", "zone": "managed", "stage": "production",
                "trustDomain": "personal-managed", "status": "classified", "admission": "allowed",
            }},
        }))
        (root / "workloads/demo/manifest.json").write_text(json.dumps({
            "id": "demo", "name": "Demo", "schemaVersion": 1,
            "canonicalRoot": "/srv/argus/workloads/demo",
            "sourcePath": "/srv/argus/workloads/demo/source",
            "runtime": {"type": "docker-compose", "compose": {
                "path": "/srv/argus/workloads/demo/source/docker-compose.yml",
                "project": "demo", "service": "web",
            }},
            "health": {},
            "migration": {"runtimeTrustDomain": "personal-sandbox", "rollback": "restore source"},
            "operations": {
                "migrationPreflight": {"allowed": True},
                "migrationCutover": {"allowed": True},
                "migrationRollback": {"allowed": True},
            },
            "backup": {
                "backupAllowed": False, "restoreAllowed": False,
                "database": {"type": "none"}, "namedVolumes": [], "bindMounts": [],
            },
            "security": {"publicAllowed": False},
        }))
        template = root / "workloads/demo/compose.template.yml"
        target = root / "workloads/demo/source/docker-compose.yml"
        template.write_text("services: {}\n")
        target.write_text(template.read_text())
        template_digest = "sha256:" + hashlib.sha256(template.read_bytes()).hexdigest()
        journal = root / "runtime/argus/source-materialization/demo/latest.json"
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({
            "schemaVersion": 1, "state": "materialized", "workloadId": "demo",
            "templateDigest": template_digest, "targetDigest": template_digest,
            "targetPath": str(target),
        }))
        observations = root / "runtime/argus/observations.sqlite3"
        observations.parent.mkdir(parents=True, exist_ok=True)
        registry = load_registry(root / "config/argus/observation-sources.json", root)
        with ObservationRepository(observations) as repository:
            repository.sync_registry(registry, explicit_clock="2026-08-05T00:00:00Z")
            for index, source_id in enumerate(registry.sources):
                records = []
                if source_id == "oreochiserver.personal-sandbox.rootless-docker":
                    records = [{
                        "schemaVersion": 2,
                        "resourceKind": "container",
                        "nativeId": "demo-container",
                        "observedAt": "2026-08-05T00:00:01Z",
                        "attributes": {
                            "lifecycle": "running", "name": "demo", "project": "demo",
                        },
                        "provenance": {"adapter": "fixture", "adapterVersion": "1", "ordinal": 0},
                    }]
                elif source_id == "oreochiserver.rootful-docker":
                    # Retained terminal history must not be mistaken for a
                    # live foreign placement during migration preflight.
                    records = [{
                        "schemaVersion": 2,
                        "resourceKind": "container",
                        "nativeId": "demo-history",
                        "observedAt": "2026-08-05T00:00:01Z",
                        "attributes": {
                            "lifecycle": "exited", "name": "demo-history", "project": "demo",
                        },
                        "provenance": {"adapter": "fixture", "adapterVersion": "1", "ordinal": 0},
                    }]
                repository.ingest(
                    registry,
                    run_id=f"run-{index}",
                    source_id=source_id,
                    sequence=None,
                    state="completed",
                    started_at="2026-08-05T00:00:00Z",
                    terminal_at="2026-08-05T00:00:01Z",
                    records=records,
                )
        ledger = OperationLedger(root / "operations.sqlite3")
        ready = migration_preview(
            root,
            ledger,
            "demo",
            observations_db=observations,
            explicit_clock="2026-08-05T00:01:00Z",
        )
        self.assertTrue(ready["eligible"])
        self.assertEqual("personal-sandbox", ready["sourceTrustDomain"])
        self.assertEqual("personal-managed", ready["targetTrustDomain"])
        self.assertEqual("stateless", ready["statelessContract"]["state"])
        self.assertEqual(0, ready["observation"]["foreignContainerCount"])
        journal.write_text(json.dumps({
            "schemaVersion": 1, "state": "materialized", "workloadId": "demo",
            "templateDigest": template_digest, "targetDigest": template_digest,
            "targetPath": "/unexpected/source/docker-compose.yml",
        }))
        wrong_target = migration_preview(
            root,
            ledger,
            "demo",
            observations_db=observations,
            explicit_clock="2026-08-05T00:01:00Z",
        )
        self.assertFalse(wrong_target["eligible"])
        self.assertIn("source-materialization-unverified", wrong_target["blockers"])
        journal.write_text(json.dumps({
            "schemaVersion": 1, "state": "materialized", "workloadId": "demo",
            "templateDigest": template_digest, "targetDigest": template_digest,
            "targetPath": str(target),
        }))
        target.write_text("different\n")
        blocked = migration_preview(
            root,
            ledger,
            "demo",
            observations_db=observations,
            explicit_clock="2026-08-05T00:01:00Z",
        )
        self.assertFalse(blocked["eligible"])
        self.assertIn("source-materialization-unverified", blocked["blockers"])


if __name__ == "__main__":
    unittest.main()
