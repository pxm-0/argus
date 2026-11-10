"""PR6 runtime evidence: live dashboard health, observer restrictions, workload metrics, worker finish audit, deploy result."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "control-plane" / "monitoring"))

import collect_metrics  # noqa: E402
from argus_operation_worker import OperationWorker  # noqa: E402
from argus_operations import OperationLedger  # noqa: E402
from tests.test_argus_operation_api import load_server  # noqa: E402


class ObservedHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.directory.name))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_without_ledger_rows_falls_back_to_the_static_migration_timestamp(self) -> None:
        workload = {"id": "w", "health": {"enabled": True}, "migration": {"lastHealthCheck": "2026-07-29T13:51:08Z"}}
        health = self.server.observed_health(workload, [])
        self.assertEqual(("2026-07-29T13:51:08Z", None, "migration"), (health["lastObservedAt"], health["ok"], health["observedFrom"]))
        self.assertTrue(health["enabled"])

    def test_newest_finished_refresh_wins_and_unfinished_rows_are_ignored(self) -> None:
        rows = [
            {"state": "running", "created_at": "2026-11-10T05:05:00Z", "redactedResult": {}},
            {"state": "succeeded", "finished_at": "2026-11-10T05:00:09Z", "redactedResult": {"health": {"ok": True}}},
            {"state": "failed", "finished_at": "2026-11-10T04:55:09Z", "redactedResult": {}},
        ]
        health = self.server.observed_health({"id": "w", "migration": {"lastHealthCheck": "old"}}, rows)
        self.assertEqual(("2026-11-10T05:00:09Z", True, "ledger"), (health["lastObservedAt"], health["ok"], health["observedFrom"]))

    def test_unhealthy_report_and_failed_operation_are_not_ok(self) -> None:
        unhealthy = {"state": "succeeded", "finished_at": "t", "redactedResult": {"health": {"ok": False}}}
        failed = {"state": "failed", "created_at": "t2", "redactedResult": {}}
        self.assertIs(False, self.server.observed_health({"id": "w"}, [unhealthy])["ok"])
        self.assertEqual(("t2", False), tuple(self.server.observed_health({"id": "w"}, [failed]).get(k) for k in ("lastObservedAt", "ok")))

    def test_stage_runtime_reads_the_real_ledger_without_mutating_the_input(self) -> None:
        workload = {"id": "demo", "health": {"enabled": True}, "migration": {"lastHealthCheck": "static"}}
        before = json.dumps(workload, sort_keys=True)
        self.assertEqual("static", self.server.stage_runtime(workload)["health"]["lastObservedAt"])
        operation, _ = self.server.LEDGER.create(
            workload_id="demo", trust_domain="personal-sandbox", operation_type="health.refresh",
            requested_by="op@example.com", parameters={}, preview_digest="p", expected_revision="r",
            policy_version="1", idempotency_key="k1",
        )
        operation_id = str(operation["operation_id"])
        self.server.LEDGER.transition(operation_id, {"queued"}, "running")
        self.server.LEDGER.transition(
            operation_id, {"running"}, "succeeded", finished_at=int(time.time()),
            redacted_result_json=json.dumps({"health": {"ok": True, "status": "healthy"}}),
        )
        health = self.server.stage_runtime(workload)["health"]
        self.assertEqual(("ledger", True), (health["observedFrom"], health["ok"]))
        self.assertNotEqual("static", health["lastObservedAt"])
        self.assertEqual(before, json.dumps(workload, sort_keys=True))


class ObserverRestrictionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = load_server(self.root)
        (self.root / "observer-token").write_text("OBSERVER-TOKEN\n")
        (self.root / "control-token").write_text("OWNER-TOKEN\n")
        self.patches = [
            patch.object(self.server, "OBSERVER_TOKEN_FILE", self.root / "observer-token"),
            patch.object(self.server, "TOKEN_FILE", self.root / "control-token"),
        ]
        for item in self.patches:
            item.start()
        self.responses: list[tuple[int, dict]] = []

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.directory.cleanup()

    def handler(self, identity: str, path: str):
        handler = object.__new__(self.server.Handler)
        handler.path = path
        handler.headers = {}
        handler.send_json = lambda status, payload: self.responses.append((status, payload))
        handler.current_session = lambda: self.server.SESSIONS.create(identity)
        return handler

    def test_each_identity_exchanges_only_its_own_token(self) -> None:
        observer, owner = self.server.OBSERVER_LOGIN, "owner@example.com"
        self.assertTrue(self.server.bootstrap_valid("OBSERVER-TOKEN", observer))
        self.assertFalse(self.server.bootstrap_valid("OWNER-TOKEN", observer))
        self.assertTrue(self.server.bootstrap_valid("OWNER-TOKEN", owner))
        self.assertFalse(self.server.bootstrap_valid("OBSERVER-TOKEN", owner))

    def test_missing_observer_token_file_fails_closed(self) -> None:
        with patch.object(self.server, "OBSERVER_TOKEN_FILE", self.root / "absent"):
            self.assertFalse(self.server.bootstrap_valid("", self.server.OBSERVER_LOGIN))

    def test_observer_is_limited_to_operation_endpoints(self) -> None:
        allowed = ("/api/workloads/nodens-staging/operations/preview", "/api/workloads/nodens-staging/operations", f"/api/operations/{'a' * 8}-b/approve")
        denied = ("/api/session/step-up", "/api/estate/refresh", "/api/workloads/discover", "/api/operations", "/api/migrations/" + "a" * 36 + "/approve", "/api/operations/abc/cancel")
        for path in allowed:
            with self.subTest(path):
                self.assertIsNotNone(self.handler(self.server.OBSERVER_LOGIN, path).require_session())
        for path in denied:
            with self.subTest(path):
                self.assertIsNone(self.handler(self.server.OBSERVER_LOGIN, path).require_session())
                self.assertEqual(403, self.responses[-1][0])

    def test_owner_sessions_are_not_path_restricted(self) -> None:
        self.assertIsNotNone(self.handler("owner@example.com", "/api/estate/refresh").require_session())

    def test_observer_cannot_deploy_but_can_refresh_health(self) -> None:
        handler = self.handler(self.server.OBSERVER_LOGIN, "/")
        session = self.server.SESSIONS.create(self.server.OBSERVER_LOGIN)
        self.assertTrue(handler.observer_denied(session, "workload.deploy"))
        self.assertEqual(403, self.responses[-1][0])
        self.assertFalse(handler.observer_denied(session, "health.refresh"))
        owner = self.server.SESSIONS.create("owner@example.com")
        self.assertFalse(handler.observer_denied(owner, "workload.deploy"))


class WorkloadMetricsTests(unittest.TestCase):
    def build(self, directory: Path) -> tuple[Path, Path]:
        database = directory / "observations.sqlite3"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE sources (source_id TEXT PRIMARY KEY, active INTEGER, current_run_id TEXT);
            CREATE TABLE observations (source_id TEXT, run_id TEXT, resource_kind TEXT, native_id TEXT,
                                       observed_at TEXT, attributes_json TEXT);
            """
        )
        connection.executemany("INSERT INTO sources VALUES (?,?,?)", [
            ("rootless-managed", 1, "run-new"), ("rootless-sandbox", 1, "run-s"), ("retired", 0, "run-x"),
        ])

        def container(source, run, native, project, service, lifecycle, health, at="2026-11-10T05:32:43Z"):
            attributes = {"project": project, "service": service, "lifecycle": lifecycle, "health": health, "name": "secret-name-1"}
            return (source, run, "container", native, at, json.dumps(attributes))

        connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?)", [
            container("rootless-managed", "run-new", "c1", "nodens-production", "nodens", "running", "healthy"),
            container("rootless-managed", "run-new", "c2", "nodens-production", "argus-ingress", "running", ""),
            container("rootless-managed", "run-old", "c3", "nodens-production", "stale", "exited", "unhealthy"),  # superseded run
            container("rootless-sandbox", "run-s", "c4", "kadath-live", "postgres", "running", "unhealthy"),
            container("retired", "run-x", "c5", "gone", "svc", "running", "healthy"),  # inactive source
            ("rootless-sandbox", "run-s", "image", "i1", "t", "{}"),
        ])
        connection.commit()
        connection.close()
        config = directory / "workloads.json"
        config.write_text(json.dumps({"workloads": [{"id": "nodens-production", "runtime": {"composeProject": "nodens-production"}}]}))
        return database, config

    def test_groups_latest_run_containers_by_project_across_rootless_domains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, config = self.build(Path(directory))
            rows = collect_metrics.workload_metrics(database, config)
        self.assertEqual(["kadath-live", "nodens-production"], [row["project"] for row in rows])
        production = rows[1]
        self.assertEqual(("nodens-production", 2, 2, 0), (production["workloadId"], production["containers"], production["running"], production["unhealthy"]))
        self.assertEqual("2026-11-10T05:32:43Z", production["observedAt"])
        kadath = rows[0]
        self.assertEqual(("", 1, 1), (kadath["workloadId"], kadath["unhealthy"], kadath["containers"]))
        self.assertNotIn("secret-name-1", json.dumps(rows))

    def test_missing_or_unreadable_database_yields_an_empty_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual([], collect_metrics.workload_metrics(Path(directory) / "none.sqlite3", Path(directory) / "none.json"))
            garbage = Path(directory) / "garbage.sqlite3"
            garbage.write_bytes(b"not sqlite" * 100)
            self.assertEqual([], collect_metrics.workload_metrics(garbage, Path(directory) / "none.json"))

    def test_collect_keeps_existing_keys_and_adds_workloads(self) -> None:
        with patch.object(collect_metrics, "cpu_percent", return_value=0.0), patch.object(
            collect_metrics, "docker_containers", return_value=[]
        ), patch.object(collect_metrics, "docker_stats", return_value=[]), patch.object(
            collect_metrics, "workload_metrics", return_value=[{"project": "p"}]
        ), patch.object(collect_metrics, "uptime_seconds", return_value=1), patch.object(
            collect_metrics, "memory", return_value={}
        ), patch.object(collect_metrics, "network", return_value=[]), patch.object(
            collect_metrics, "processes", return_value=[]
        ), patch.object(collect_metrics, "temperatures", return_value=[]), patch.object(
            collect_metrics, "load_average", return_value={}
        ):
            metrics = collect_metrics.collect()
        for key in ("timestamp", "hostname", "uptimeSeconds", "load", "cpu", "memory", "disk", "network", "docker", "processes", "temperatures"):
            self.assertIn(key, metrics)
        self.assertEqual([{"project": "p"}], metrics["workloads"])


class WorkerFinishAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = OperationLedger(Path(self.directory.name) / "operations.sqlite3")
        self.lines: list[dict] = []

    def tearDown(self) -> None:
        self.directory.cleanup()

    def audit(self, action, workload_id, result, **extra) -> None:
        self.lines.append({"action": action, "workloadId": workload_id, "result": result, **extra})

    def queued_operation(self, key: str = "k") -> str:
        operation, _ = self.ledger.create(
            workload_id="demo", trust_domain="personal-sandbox", operation_type="health.refresh",
            requested_by="op@example.com", parameters={}, preview_digest="p", expected_revision="r",
            policy_version="1", idempotency_key=key,
        )
        return str(operation["operation_id"])

    def test_finish_line_is_written_once_when_the_agent_persists_a_terminal_state(self) -> None:
        operation_id = self.queued_operation()
        worker = OperationWorker(self.ledger, Path(self.directory.name), audit=self.audit)
        with patch.object(worker, "agent_available", return_value=True), patch.object(worker, "dispatch", return_value=True):
            worker.run_once()
            self.assertEqual([], self.lines)  # accepted but still running
            self.ledger.transition(operation_id, {"running"}, "failed", finished_at=int(time.time()), error_class="RuntimeError")
            worker.run_once()
            worker.run_once()
        self.assertEqual(1, len(self.lines))
        line = self.lines[0]
        self.assertEqual("operation.finished", line["action"])
        self.assertEqual(
            {"operationId": operation_id, "workloadId": "demo", "state": "failed", "errorClass": "RuntimeError"},
            {key: line[key] for key in ("operationId", "workloadId", "state", "errorClass")},
        )

    def test_unconfirmed_dispatch_is_audited_as_indeterminate_immediately(self) -> None:
        operation_id = self.queued_operation()
        worker = OperationWorker(self.ledger, Path(self.directory.name), audit=self.audit)
        with patch.object(worker, "agent_available", return_value=True), patch.object(
            worker, "dispatch", side_effect=lambda op: self.ledger.mark_dispatch_indeterminate(str(op["operation_id"])) and False
        ):
            worker.run_once()
        self.assertEqual(("indeterminate", "agent-dispatch-unconfirmed"), (self.lines[0]["state"], self.lines[0]["errorClass"]))

    def test_unwritable_audit_never_breaks_dispatch(self) -> None:
        operation_id = self.queued_operation()

        def broken(*args, **kwargs):
            raise OSError("read-only file system")

        worker = OperationWorker(self.ledger, Path(self.directory.name), audit=broken)
        with patch.object(worker, "agent_available", return_value=True), patch.object(worker, "dispatch", return_value=True):
            self.ledger.transition(operation_id, {"queued"}, "running")
            worker.unfinished.add(operation_id)
            self.ledger.transition(operation_id, {"running"}, "succeeded", finished_at=int(time.time()))
            with patch("sys.stderr"):
                worker.run_once()
        self.assertEqual(set(), worker.unfinished)


if __name__ == "__main__":
    unittest.main()
