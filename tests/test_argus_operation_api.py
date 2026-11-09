from __future__ import annotations

import importlib.util
import shutil
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_sqlite import ClosingConnection  # noqa: E402


def load_server(runtime: Path):
    with patch.dict(
        os.environ,
        {
            "ARGUS_RUNTIME": str(runtime),
            "ARGUS_SESSION_DB": str(runtime / "sessions.sqlite3"),
            "ARGUS_OPERATIONS_DB": str(runtime / "operations.sqlite3"),
        },
    ):
        spec = importlib.util.spec_from_file_location(
            f"argus_operation_api_{time.time_ns()}",
            ROOT / "control-plane" / "api" / "server.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


class OperationApiTests(unittest.TestCase):
    def test_lifecycle_confirmation_phrases_bind_exact_operation_intent(self) -> None:
        self.assertEqual(
            "deploy demo sha256:" + "a" * 64,
            self.server.confirmation_phrase(
                "demo", "workload.deploy", {"targetRevision": "sha256:" + "a" * 64}
            ),
        )
        self.assertEqual(
            "restore demo run-1",
            self.server.confirmation_phrase("demo", "backup.restore", {"artifactId": "run-1"}),
        )
        self.assertEqual(
            "promote demo to production",
            self.server.confirmation_phrase("demo", "production.promote", {}),
        )
        self.assertEqual(
            "migrate demo to managed-production",
            self.server.confirmation_phrase(
                "demo", "migration.cutover", {}, "managed-production"
            ),
        )
        self.assertEqual(
            "rollback migration demo",
            self.server.confirmation_phrase("demo", "migration.rollback", {}),
        )
        self.assertEqual(
            "rollback production demo",
            self.server.confirmation_phrase("demo", "production.rollback", {}),
        )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = Path(self.directory.name)
        self.server = load_server(self.runtime)
        self.handler = object.__new__(self.server.Handler)
        self.responses: list[tuple[int, dict[str, object]]] = []
        self.handler.send_json = (
            lambda status, payload: self.responses.append((status, payload))
        )
        self.session = self.server.SESSIONS.create("operator@example.com")
        self.preview = {
            "allowed": True,
            "reason": "allowed",
            "workloadId": "hello-nginx",
            "trustDomain": "personal-sandbox",
            "operationType": "workload.restart",
            "parameters": {},
            "expectedRevision": "revision",
            "policyVersion": "1",
            "previewDigest": "preview",
            "confirmationPhrase": "hello-nginx",
        }
        migration_payload = {
            "schemaVersion": 1,
            "workloadId": "hello-nginx",
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
            "confirmationPhrase": "migrate hello-nginx to personal-managed",
            "rollbackConfirmationPhrase": "rollback migration hello-nginx",
        }
        self.migration_preview = {
            **migration_payload,
            "previewDigest": self.server.digest(migration_payload),
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create_operation(self) -> dict[str, object]:
        idempotency_key = f"api-{time.time_ns()}"
        self.assertTrue(
            self.server.SESSIONS.reserve_operation(
                idempotency_key,
                self.session.session_id,
            )
        )
        operation, _ = self.server.LEDGER.create(
            workload_id="hello-nginx",
            trust_domain="personal-sandbox",
            operation_type="workload.restart",
            requested_by=self.session.identity,
            parameters={},
            preview_digest="preview",
            expected_revision="revision",
            policy_version="1",
            idempotency_key=idempotency_key,
            preview=self.preview,
        )
        self.assertTrue(
            self.server.SESSIONS.bind_operation(
                str(operation["operation_id"]),
                self.session.session_id,
            )
        )
        return operation

    def test_create_binds_preview_revision_and_policy(self) -> None:
        body = {
            "operationType": "workload.restart",
            "parameters": {},
            "previewDigest": "preview",
            "expectedRevision": "revision",
        }
        self.handler.headers = {"Idempotency-Key": "missing-policy"}
        with patch.object(
            self.server,
            "operation_preview",
            return_value=self.preview,
        ):
            self.handler.handle_operation_create(
                "hello-nginx",
                self.session,
                body,
            )
        self.assertEqual(409, self.responses[-1][0])

        body["policyVersion"] = "1"
        self.handler.headers = {"Idempotency-Key": "bound-intent"}
        with (
            patch.object(
                self.server,
                "operation_preview",
                return_value=self.preview,
            ),
            patch.object(self.server, "audit"),
        ):
            self.handler.handle_operation_create(
                "hello-nginx",
                self.session,
                body,
            )
        self.assertEqual(202, self.responses[-1][0])
        operation = self.responses[-1][1]
        self.assertEqual("awaiting-approval", operation["state"])
        self.assertEqual("revision", operation["expected_revision"])
        self.assertEqual("1", operation["policy_version"])
        self.assertEqual(self.preview, operation["preview"])

    def test_migration_parent_needs_dashboard_step_up_before_any_child_is_queued(self) -> None:
        body = {
            key: self.migration_preview[key]
            for key in (
                "targetTrustDomain",
                "previewDigest",
                "expectedRevision",
                "policyVersion",
                "observationDigest",
            )
        }
        self.handler.headers = {"Idempotency-Key": "migration-parent"}
        with (
            patch.object(
                self.server, "migration_preview", return_value=self.migration_preview
            ),
            patch.object(self.server, "audit"),
        ):
            self.handler.handle_migration_create("hello-nginx", self.session, body)
        self.assertEqual(202, self.responses[-1][0])
        created = self.responses[-1][1]
        self.assertEqual("awaiting-approval", created["phase"])
        self.assertEqual([], created["children"])
        migration_id = str(created["migrationId"])
        with (
            patch.object(
                self.server, "migration_preview", return_value=self.migration_preview
            ),
            patch.object(self.server, "audit"),
        ):
            self.handler.handle_migration_approve(
                migration_id,
                self.session,
                {"confirmation": "migrate hello-nginx to personal-managed"},
            )
        self.assertEqual(202, self.responses[-1][0])
        approved = self.responses[-1][1]
        self.assertEqual("source-fencing", approved["phase"])
        self.assertEqual([], approved["children"])

    def test_migration_approval_requires_the_originating_session(self) -> None:
        body = {
            key: self.migration_preview[key]
            for key in (
                "targetTrustDomain",
                "previewDigest",
                "expectedRevision",
                "policyVersion",
                "observationDigest",
            )
        }
        self.handler.headers = {"Idempotency-Key": "migration-session"}
        with patch.object(
            self.server, "migration_preview", return_value=self.migration_preview
        ):
            self.handler.handle_migration_create("hello-nginx", self.session, body)
        migration_id = str(self.responses[-1][1]["migrationId"])
        replacement = self.server.SESSIONS.create(self.session.identity)
        self.handler.handle_migration_approve(
            migration_id,
            replacement,
            {"confirmation": "migrate hello-nginx to personal-managed"},
        )
        self.assertEqual(403, self.responses[-1][0])
        self.assertEqual(
            "migration approval requires the originating session",
            self.responses[-1][1]["error"],
        )

    def test_request_shapes_reject_unknown_fields(self) -> None:
        with self.assertRaises(self.server.OperationValidationError):
            self.server.validate_body_keys(
                {
                    "operationType": "health.refresh",
                    "parameters": {},
                    "rawCommand": "forbidden",
                },
                {"operationType", "parameters"},
            )

    def test_preview_fails_closed_for_retired_workload(self) -> None:
        with patch.object(self.server, "agent_available", return_value=True):
            preview = self.server.operation_preview(
                "hello-nginx",
                "workload.restart",
                {},
            )
        self.assertFalse(preview["allowed"])
        self.assertEqual("unknown-workload", preview["admission"]["decisionCode"])
        self.assertEqual(
            preview["expectedRevision"],
            preview["admission"]["revision"],
        )
        self.assertEqual(
            preview["policyVersion"],
            preview["admission"]["policyVersion"],
        )

    def test_preview_fails_closed_when_admission_dependencies_are_malformed(self) -> None:
        clone = self.runtime / "repository"
        shutil.copytree(ROOT / "config", clone / "config")
        shutil.copytree(ROOT / "workloads", clone / "workloads")
        (clone / "config" / "argus" / "workload-classification.json").write_text(
            "{",
            encoding="utf-8",
        )
        with patch.object(self.server, "ROOT", clone):
            preview = self.server.operation_preview(
                "hello-nginx",
                "workload.restart",
                {},
            )
        self.assertFalse(preview["allowed"])
        self.assertEqual("dependency-unavailable", preview["reason"])
        self.assertEqual(
            "dependency-unavailable",
            preview["admission"]["decisionCode"],
        )
        self.assertEqual("legacy-rootful", preview["trustDomain"])

    def test_migration_preflight_preview_disables_completed_workload(self) -> None:
        with patch.object(self.server, "agent_available", return_value=True):
            preview = self.server.operation_preview(
                "hastur",
                "migration.preflight",
                {"targetTrustDomain": "personal-sandbox"},
            )
            access_policy = self.server.operation_policy(
                "hastur",
                "access.apply",
                {"desired": "none"},
            )
            health_policy = self.server.operation_policy(
                "hastur",
                "health.refresh",
                {},
            )
        self.assertFalse(preview["allowed"])
        self.assertIn("not a migration candidate", preview["reason"])
        self.assertEqual("", preview["confirmationPhrase"])
        self.assertIsNone(preview["migrationReadiness"]["readyForCutover"])
        self.assertEqual(
            (False, "operation-not-capable"),
            access_policy,
        )
        self.assertEqual(
            (False, "operation-not-capable"),
            health_policy,
        )

    def test_approval_expires_old_preview_and_releases_mutation_lock(self) -> None:
        operation = self.create_operation()
        created = self.server.parse_timestamp(str(operation["created_at"]))
        with patch.object(self.server.time, "time", return_value=created + 60):
            self.handler.handle_operation_approve(
                str(operation["operation_id"]),
                self.session,
                {"confirmation": "hello-nginx"},
            )
        self.assertEqual(410, self.responses[-1][0])
        self.assertEqual(
            "expired",
            self.server.LEDGER.get(str(operation["operation_id"]))["state"],
        )

    def test_approval_rechecks_drift_and_current_policy(self) -> None:
        drifted = self.create_operation()
        changed = {**self.preview, "expectedRevision": "changed"}
        with patch.object(
            self.server,
            "operation_preview",
            return_value=changed,
        ):
            self.handler.handle_operation_approve(
                str(drifted["operation_id"]),
                self.session,
                {"confirmation": "hello-nginx"},
            )
        self.assertEqual(409, self.responses[-1][0])
        self.assertEqual(
            "expired",
            self.server.LEDGER.get(str(drifted["operation_id"]))["state"],
        )

        denied = self.create_operation()
        current_denial = {**self.preview, "allowed": False, "reason": "policy denied"}
        with patch.object(
            self.server,
            "operation_preview",
            return_value=current_denial,
        ):
            self.handler.handle_operation_approve(
                str(denied["operation_id"]),
                self.session,
                {"confirmation": "hello-nginx"},
            )
        self.assertEqual(403, self.responses[-1][0])
        self.assertEqual(
            "denied",
            self.server.LEDGER.get(str(denied["operation_id"]))["state"],
        )

    def test_valid_approval_only_queues_for_the_worker(self) -> None:
        operation = self.create_operation()
        with patch.object(
            self.server,
            "operation_preview",
            return_value=self.preview,
        ):
            self.handler.handle_operation_approve(
                str(operation["operation_id"]),
                self.session,
                {"confirmation": "hello-nginx"},
            )
        self.assertEqual(202, self.responses[-1][0])
        self.assertEqual("queued", self.responses[-1][1]["state"])
        self.assertNotIn("dispatch_operation", self.server.__dict__)

    def test_reservation_allows_approval_after_pre_binding_api_crash(self) -> None:
        operation = self.create_operation()
        with sqlite3.connect(self.server.SESSION_DB, factory=ClosingConnection) as connection:
            connection.execute(
                "DELETE FROM operation_session_bindings WHERE operation_id = ?",
                (operation["operation_id"],),
            )
        with patch.object(
            self.server,
            "operation_preview",
            return_value=self.preview,
        ):
            self.handler.handle_operation_approve(
                str(operation["operation_id"]),
                self.session,
                {"confirmation": "hello-nginx"},
            )
        self.assertEqual(202, self.responses[-1][0])
        self.assertEqual("queued", self.responses[-1][1]["state"])

    def test_approval_requires_the_originating_session_not_only_identity(self) -> None:
        operation = self.create_operation()
        replacement = self.server.SESSIONS.create(self.session.identity)
        with patch.object(
            self.server,
            "operation_preview",
            return_value=self.preview,
        ):
            self.handler.handle_operation_approve(
                str(operation["operation_id"]),
                replacement,
                {"confirmation": "hello-nginx"},
            )
        self.assertEqual(403, self.responses[-1][0])
        self.assertEqual(
            "operation approval requires the originating session",
            self.responses[-1][1]["error"],
        )
        self.assertEqual(
            "awaiting-approval",
            self.server.LEDGER.get(str(operation["operation_id"]))["state"],
        )

    def test_idempotent_create_cannot_be_claimed_by_replacement_session(self) -> None:
        body = {
            "operationType": "workload.restart",
            "parameters": {},
            "previewDigest": "preview",
            "expectedRevision": "revision",
            "policyVersion": "1",
        }
        self.handler.headers = {"Idempotency-Key": "session-bound-intent"}
        with (
            patch.object(
                self.server,
                "operation_preview",
                return_value=self.preview,
            ),
            patch.object(self.server, "audit"),
        ):
            self.handler.handle_operation_create(
                "hello-nginx",
                self.session,
                body,
            )
            replacement = self.server.SESSIONS.create(self.session.identity)
            self.handler.handle_operation_create(
                "hello-nginx",
                replacement,
                body,
            )
        self.assertEqual(409, self.responses[-1][0])
        self.assertEqual(
            "idempotency key is bound to another session",
            self.responses[-1][1]["error"],
        )

    def test_cancel_status_and_workload_history_use_the_durable_ledger(self) -> None:
        operation = self.create_operation()
        operation_id = str(operation["operation_id"])
        with patch.object(self.server, "audit"):
            self.handler.handle_operation_cancel(
                operation_id,
                self.session,
            )
        self.assertEqual(200, self.responses[-1][0])
        self.assertEqual("denied", self.responses[-1][1]["state"])
        self.assertEqual("operator-cancelled", self.responses[-1][1]["error_class"])

        self.handler.path = f"/api/operations/{operation_id}"
        self.handler.require_session = lambda: self.session
        self.handler.handle_get()
        self.assertEqual(200, self.responses[-1][0])
        self.assertEqual(operation_id, self.responses[-1][1]["operation_id"])

        self.handler.path = "/api/workloads/hello-nginx/operations"
        self.handler.handle_get()
        self.assertEqual(200, self.responses[-1][0])
        history = self.responses[-1][1]["operations"]
        self.assertEqual([operation_id], [item["operation_id"] for item in history])

    def test_estate_refresh_request_is_inert_and_status_is_session_bound(self) -> None:
        with (
            patch.object(self.server, "ROOT", self.runtime),
            patch.object(self.server, "audit"),
        ):
            self.handler.handle_estate_refresh_create(self.session)
        self.assertEqual(202, self.responses[-1][0])
        request = self.responses[-1][1]["request"]
        self.assertEqual("queued", request["state"])
        self.assertTrue((self.runtime / "runtime" / "argus" / "estate-refresh" / "requests" / f"{request['runId']}.json").is_file())

        self.handler.path = request["statusUrl"]
        self.handler.require_session = lambda: self.session
        with patch.object(self.server, "ROOT", self.runtime):
            self.handler.handle_get()
        self.assertEqual(200, self.responses[-1][0])
        self.assertEqual("queued", self.responses[-1][1]["state"])

    def test_estate_coverage_returns_sanitized_reconciliation_only(self) -> None:
        self.handler.path = "/api/estate/coverage"
        self.handler.require_session = lambda: self.session
        reconciliation = {
            "schemaVersion": 1,
            "status": "incomplete",
            "safeToMoveWorkloads": False,
        }
        with (
            patch.object(self.server, "estate_reconciliation", return_value=reconciliation),
            patch.object(self.server, "estate_refresh_status", return_value={"state": "never-run"}),
        ):
            self.handler.handle_get()
        self.assertEqual(200, self.responses[-1][0])
        self.assertEqual(reconciliation, self.responses[-1][1]["reconciliation"])
        self.assertEqual({"state": "never-run"}, self.responses[-1][1]["refresh"])

    def test_compatibility_idempotency_returns_existing_queued_operation(self) -> None:
        self.handler.headers = {"Idempotency-Key": "compat-repeat"}
        body = {"confirmation": "hello-nginx"}
        with (
            patch.object(
                self.server,
                "operation_preview",
                return_value=self.preview,
            ),
            patch.object(self.server, "audit"),
        ):
            self.handler.handle_compatibility_apply(
                "hello-nginx",
                "workload.restart",
                self.session,
                body,
            )
            first = self.responses[-1]
            self.handler.handle_compatibility_apply(
                "hello-nginx",
                "workload.restart",
                self.session,
                body,
            )
            second = self.responses[-1]
        self.assertEqual(202, first[0])
        self.assertEqual(202, second[0])
        self.assertEqual(first[1]["operation_id"], second[1]["operation_id"])
        self.assertEqual("queued", second[1]["state"])


if __name__ == "__main__":
    unittest.main()
