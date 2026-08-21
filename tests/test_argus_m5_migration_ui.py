from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_actions import _verify_backup_artifact, migration_preflight
from argus_common import policy_decision
from argus_operations import TYPED_OPERATIONS, validate_typed_parameters


class MigrationUiTests(unittest.TestCase):
    def assessment(
        self,
        *,
        workload: dict | None = None,
        manifest: dict | None = None,
        runtime: dict | None = None,
    ) -> tuple[dict, Mock]:
        candidate = workload if workload is not None else {
            "id": "candidate",
            "migration": {"status": "planned", "originalPath": "/srv/legacy/candidate"},
            "paths": {
                "legacy": "/srv/legacy/candidate",
                "source": "/srv/argus/workloads/candidate/source",
            },
        }
        contract = manifest if manifest is not None else {
            "id": "candidate",
            "sourcePath": "/srv/argus/workloads/candidate/source",
            "migration": {
                "status": "planned",
                "originalPath": "/srv/legacy/candidate",
                "rollback": "Fence target and reopen source.",
            },
            "operations": {"migrationPreflight": {"allowed": True}},
            "backup": {
                "backupAllowed": True,
                "restoreAllowed": True,
                "restoreTested": True,
            },
            "health": {"url": "http://127.0.0.1:8080"},
        }
        runtime_contract = runtime if runtime is not None else {
            "type": "docker-compose",
            "composePath": "/srv/argus/workloads/candidate/source/compose.yml",
            "composeProject": "candidate",
        }
        permission = contract.get("operations", {}).get("migrationPreflight")
        admission_allowed = (
            contract.get("operations", {}).get("migrationPreflightAllowed") is True
            or (
                isinstance(permission, dict)
                and permission.get("allowed") is True
            )
        )
        admission = Mock(
            allowed=admission_allowed,
            decision_code=("allowed" if admission_allowed else "operation-not-capable"),
        )
        audit = Mock()
        with (
            patch("argus_actions._workload", return_value=candidate),
            patch("argus_actions.evaluate_current", return_value=admission),
            patch("argus_actions.load_manifest", return_value=contract),
            patch("argus_actions.runtime_config", return_value=runtime_contract),
            patch("argus_actions.Path.is_dir", return_value=True),
            patch("argus_actions.Path.is_file", return_value=True),
            patch("argus_actions._backup_artifact_evidence", return_value=(True, "opaque-artifact")),
            patch("argus_actions._health_evidence", return_value=True),
            patch("argus_actions.audit", audit),
        ):
            result = migration_preflight("candidate")
        return result, audit

    def test_migrated_workload_preflight_is_disabled(self) -> None:
        with patch("argus_actions.audit"):
            result = migration_preflight("hastur")

        self.assertFalse(result["allowed"])
        self.assertIn("not a migration candidate", result["reason"])
        self.assertNotIn("sourcePath", result)

    def test_sandbox_reconcile_only_workload_blocks_shared_access_policy(self) -> None:
        decision = policy_decision("hastur", "none")
        self.assertFalse(decision["allowed"])
        self.assertEqual("operation-not-capable", decision["reason"])
        self.assertEqual("tailnet", decision["effective"])

    def test_non_candidate_workload_preflight_fails_closed(self) -> None:
        with patch("argus_actions.audit"):
            result = migration_preflight("hello-nginx")

        self.assertFalse(result["allowed"])
        self.assertEqual("operation-not-capable", result["reason"])

    def test_migration_preflight_is_a_parameterless_typed_operation(self) -> None:
        self.assertIn("migration.preflight", TYPED_OPERATIONS)
        validate_typed_parameters("migration.preflight", {})
        with self.assertRaises(ValueError):
            validate_typed_parameters("migration.preflight", {"cutover": True})

    def test_unknown_workload_and_non_candidate_fail_closed(self) -> None:
        with patch("argus_actions._workload", return_value=None):
            unknown = migration_preflight("missing", record_audit=False)
        self.assertFalse(unknown["allowed"])
        self.assertEqual(404, unknown["status"])

        manifest = {
            "migration": {"status": "migrated"},
            "operations": {"migrationPreflight": {"allowed": True}},
        }
        result, _audit = self.assessment(manifest=manifest)
        self.assertFalse(result["allowed"])
        self.assertIn("not a migration candidate", result["reason"])

    def test_legacy_flat_permission_remains_compatible(self) -> None:
        manifest = {
            "id": "candidate",
            "sourcePath": "/srv/argus/workloads/candidate/source",
            "migration": {
                "status": "planned",
                "originalPath": "/srv/legacy/candidate",
                "rollback": "Fence target and reopen source.",
            },
            "operations": {"migrationPreflightAllowed": True},
            "backup": {
                "backupAllowed": True,
                "restoreAllowed": True,
                "restoreTested": True,
            },
            "health": {"url": "http://127.0.0.1:8080"},
        }
        result, _audit = self.assessment(manifest=manifest)
        self.assertTrue(result["allowed"])
        self.assertTrue(result["readyForCutover"])

    def test_permission_values_fail_closed_unless_exactly_boolean_true(self) -> None:
        manifest = {
            "migration": {"status": "planned"},
            "operations": {"migrationPreflight": {"allowed": "false"}},
        }
        result, _audit = self.assessment(manifest=manifest)
        self.assertFalse(result["allowed"])
        self.assertEqual("operation-not-capable", result["reason"])

    def test_ready_contract_passes_and_records_success(self) -> None:
        result, audit = self.assessment()
        self.assertTrue(result["allowed"])
        self.assertTrue(result["readyForCutover"])
        self.assertEqual([], result["blockers"])
        audit.assert_called_once_with(
            "migration.preflight",
            "candidate",
            "ok",
            actor="local-cli",
            blockerCount=0,
        )

    def test_each_readiness_guard_reports_its_exact_blocker(self) -> None:
        base_workload = {
            "id": "candidate",
            "migration": {"status": "planned", "originalPath": "/srv/legacy/candidate"},
            "paths": {
                "legacy": "/srv/legacy/candidate",
                "source": "/srv/argus/workloads/candidate/source",
            },
        }
        base_manifest = {
            "id": "candidate",
            "sourcePath": "/srv/argus/workloads/candidate/source",
            "migration": {
                "status": "planned",
                "originalPath": "/srv/legacy/candidate",
                "rollback": "Fence target and reopen source.",
            },
            "operations": {"migrationPreflight": {"allowed": True}},
            "backup": {
                "backupAllowed": True,
                "restoreAllowed": True,
                "restoreTested": True,
            },
            "health": {"url": "http://127.0.0.1:8080"},
        }
        base_runtime = {
            "type": "docker-compose",
            "composePath": "/srv/argus/workloads/candidate/source/compose.yml",
            "composeProject": "candidate",
        }
        cases = {
            "Source path is not recorded.": lambda workload, manifest, runtime: (
                workload["migration"].update(originalPath=""),
                workload["paths"].update(legacy=""),
                manifest["migration"].update(originalPath=""),
            ),
            "Target source path is outside the canonical workload root.": (
                lambda workload, manifest, runtime: manifest.update(sourcePath="/srv/other")
            ),
            "Runtime is not Docker Compose.": (
                lambda workload, manifest, runtime: runtime.update(type="external")
            ),
            "Target Compose path is not recorded.": (
                lambda workload, manifest, runtime: runtime.update(composePath="")
            ),
            "Compose project name is not recorded.": (
                lambda workload, manifest, runtime: runtime.update(composeProject="")
            ),
            "Backup execution is not approved.": (
                lambda workload, manifest, runtime: manifest["backup"].update(backupAllowed=False)
            ),
            "Restore execution is not approved.": (
                lambda workload, manifest, runtime: manifest["backup"].update(restoreAllowed=False)
            ),
            "An isolated restore test is not recorded.": (
                lambda workload, manifest, runtime: manifest["backup"].update(restoreTested=False)
            ),
            "Rollback contract is not recorded.": (
                lambda workload, manifest, runtime: manifest["migration"].update(rollback="")
            ),
            "Target health URL is not recorded.": (
                lambda workload, manifest, runtime: manifest["health"].update(url="")
            ),
        }
        for blocker, mutate in cases.items():
            with self.subTest(blocker=blocker):
                workload = deepcopy(base_workload)
                manifest = deepcopy(base_manifest)
                runtime = deepcopy(base_runtime)
                mutate(workload, manifest, runtime)
                result, audit = self.assessment(
                    workload=workload,
                    manifest=manifest,
                    runtime=runtime,
                )
                self.assertTrue(result["allowed"])
                self.assertFalse(result["readyForCutover"])
                self.assertIn(blocker, result["blockers"])
                audit.assert_called_once_with(
                    "migration.preflight",
                    "candidate",
                    "blocked",
                    actor="local-cli",
                    blockerCount=len(result["blockers"]),
                )

    def test_live_evidence_is_required_even_for_a_complete_manifest(self) -> None:
        candidate = {
            "id": "candidate",
            "migration": {"status": "planned", "originalPath": "/definitely/missing/source"},
            "paths": {"source": "/srv/argus/workloads/candidate/source"},
        }
        manifest = {
            "sourcePath": "/srv/argus/workloads/candidate/source",
            "migration": {
                "status": "planned",
                "originalPath": "/definitely/missing/source",
                "rollback": "Fence target and reopen source.",
            },
            "operations": {"migrationPreflight": {"allowed": True}},
            "runtime": {
                "type": "docker-compose",
                "composePath": "/srv/argus/workloads/candidate/source/compose.yml",
                "composeProject": "candidate",
            },
            "backup": {
                "backupAllowed": True,
                "restoreAllowed": True,
                "restoreTested": True,
                "destination": "/srv/argus/runtime/backups/candidate",
            },
            "health": {
                "url": "http://127.0.0.1:1",
                "expectedStatus": 200,
                "timeoutSeconds": 1,
            },
        }
        with (
            patch("argus_actions._workload", return_value=candidate),
            patch(
                "argus_actions.evaluate_current",
                return_value=Mock(allowed=True, decision_code="allowed"),
            ),
            patch("argus_actions.load_manifest", return_value=manifest),
            patch("argus_actions.runtime_config", return_value=manifest["runtime"]),
            patch("argus_actions.audit"),
        ):
            result = migration_preflight("candidate")
        self.assertFalse(result["readyForCutover"])
        self.assertIn("Recorded source path is unavailable.", result["blockers"])
        self.assertIn("Target source path is unavailable.", result["blockers"])
        self.assertIn("Target Compose file is unavailable.", result["blockers"])
        self.assertIn("A checksum-verified backup artifact is unavailable.", result["blockers"])
        self.assertIn(
            "Target health check did not return the expected status.",
            result["blockers"],
        )

    def test_backup_artifact_requires_checksum_coverage_for_every_required_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            payloads = {
                "manifest.json": b"{}",
                "files.tar.gz": b"archive",
                "restore-plan.md": b"restore",
                "backup-summary.json": json.dumps({"workloadId": "candidate"}).encode(),
            }
            for name, payload in payloads.items():
                (artifact / name).write_bytes(payload)
            one_name = "files.tar.gz"
            (artifact / "checksums.sha256").write_text(
                f"{hashlib.sha256(payloads[one_name]).hexdigest()}  {one_name}\n"
            )
            self.assertFalse(_verify_backup_artifact(artifact, "candidate"))

            (artifact / "checksums.sha256").write_text(
                "".join(
                    f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
                    for name, payload in payloads.items()
                )
            )
            self.assertTrue(_verify_backup_artifact(artifact, "candidate"))


if __name__ == "__main__":
    unittest.main()
