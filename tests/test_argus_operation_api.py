from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


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
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = Path(self.directory.name)
        self.server = load_server(self.runtime)
        self.handler = object.__new__(self.server.Handler)
        self.responses: list[tuple[int, dict[str, object]]] = []
        self.handler.send_json = (
            lambda status, payload: self.responses.append((status, payload))
        )
        self.session = self.server.Session(
            session_id="session",
            identity="operator@example.com",
            csrf_token="csrf",
            created_at=int(time.time()),
            expires_at=int(time.time()) + 60,
            step_up_at=int(time.time()),
        )
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

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create_operation(self) -> dict[str, object]:
        operation, _ = self.server.LEDGER.create(
            workload_id="hello-nginx",
            trust_domain="personal-sandbox",
            operation_type="workload.restart",
            requested_by=self.session.identity,
            parameters={},
            preview_digest="preview",
            expected_revision="revision",
            policy_version="1",
            idempotency_key=f"api-{time.time_ns()}",
            preview=self.preview,
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
