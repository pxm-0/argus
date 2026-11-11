from __future__ import annotations

import io
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_cli import run  # noqa: E402
from argus_common import APPROVED_OPERATOR_LINKS  # noqa: E402
from argus_operations import OperationLedger, digest  # noqa: E402


class ArgusCliTests(unittest.TestCase):
    def repo(self, dashboard: object) -> tempfile.TemporaryDirectory[str]:
        directory = tempfile.TemporaryDirectory()
        config = Path(directory.name) / "config"
        config.mkdir()
        (config / "routes.json").write_text(
            json.dumps(
                {
                    "dashboard": dashboard,
                    "observed": {"funnel": {"enabled": False, "allowedInP0": False, "url": "", "target": ""}},
                }
            )
        )
        return directory

    def test_dashboard_url_human_output_is_private_configured_url(self) -> None:
        directory = self.repo({"bind": "tailscale", "url": "https://host.example.ts.net:8448"})
        self.addCleanup(directory.cleanup)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(["dashboard", "url"], repo=Path(directory.name), stdout=stdout, stderr=stderr)
        self.assertEqual(0, code)
        self.assertEqual(
            "CONFIGURED_URL https://host.example.ts.net:8448\nEFFECTIVE_STATE unverified\n",
            stdout.getvalue(),
        )
        self.assertEqual("", stderr.getvalue())

    def test_dashboard_url_json_is_canonical_and_contains_no_route_internals(self) -> None:
        directory = self.repo({"bind": "tailscale", "port": 8088, "url": "https://host.example.ts.net:8448"})
        self.addCleanup(directory.cleanup)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(["dashboard", "url", "--json"], repo=Path(directory.name), stdout=stdout, stderr=stderr)
        self.assertEqual(0, code)
        self.assertEqual(
            {
                "data": {
                    "access": "configured-tailnet",
                    "command": "dashboard.url",
                    "effectiveState": "unverified",
                    "source": "config/routes.json",
                    "url": "https://host.example.ts.net:8448",
                },
                "ok": True,
                "schemaVersion": 1,
            },
            json.loads(stdout.getvalue()),
        )
        self.assertNotIn("8088", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_dashboard_url_rejects_non_private_contract(self) -> None:
        for dashboard in (
            {"bind": "public", "url": "https://example.com"},
            {"bind": "tailscale", "url": "https://example.com"},
            {"bind": "tailscale", "url": "http://host.example.ts.net:8088"},
            {"bind": "tailscale", "url": "https://user:secret@host.example.ts.net"},
            {"bind": "tailscale", "url": "https://host.example.ts.net:99999"},
            {"bind": "tailscale", "url": "https://host.example.ts.net\nPASS forged"},
        ):
            with self.subTest(dashboard=dashboard):
                directory = self.repo(dashboard)
                self.addCleanup(directory.cleanup)
                stdout, stderr = io.StringIO(), io.StringIO()
                code = run(["--json", "dashboard", "url"], repo=Path(directory.name), stdout=stdout, stderr=stderr)
                self.assertEqual(3, code)
                payload = json.loads(stdout.getvalue())
                self.assertEqual("dashboard-private-route-invalid", payload["error"]["code"])
                self.assertFalse(payload["ok"])
                self.assertNotIn("secret", stdout.getvalue())
                self.assertEqual("", stderr.getvalue())

    def test_routes_root_must_be_an_object(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "config"
        config.mkdir()
        (config / "routes.json").write_text("[]")
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(["--json", "dashboard", "url"], repo=Path(directory.name), stdout=stdout, stderr=stderr)
        self.assertEqual(3, code)
        self.assertEqual("dashboard-routes-invalid", json.loads(stdout.getvalue())["error"]["code"])
        self.assertEqual("", stderr.getvalue())

    def test_duplicate_route_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.mkdir()
            (config / "routes.json").write_text(
                '{"dashboard":{"bind":"tailscale","url":"https://host.example.ts.net"},'
                '"observed":{"funnel":{"enabled":true,"enabled":false,"allowedInP0":false,"url":"","target":""}}}'
            )
            stdout, stderr = io.StringIO(), io.StringIO()
            code = run(["--json", "dashboard", "url"], repo=Path(directory), stdout=stdout, stderr=stderr)
            self.assertEqual(3, code)
            self.assertEqual("dashboard-routes-invalid", json.loads(stdout.getvalue())["error"]["code"])

    def test_adversarial_route_json_uses_stable_error_envelope(self) -> None:
        for content in (
            '{"dashboard":' + "9" * 5000 + "}",
            "[" * 30000 + "]" * 30000,
            " " * 65537,
        ):
            with self.subTest(size=len(content)), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "config"
                config.mkdir()
                (config / "routes.json").write_text(content)
                stdout, stderr = io.StringIO(), io.StringIO()
                code = run(["--json", "dashboard", "url"], repo=Path(directory), stdout=stdout, stderr=stderr)
                self.assertEqual(3, code)
                self.assertEqual("dashboard-routes-invalid", json.loads(stdout.getvalue())["error"]["code"])
                self.assertNotIn("Traceback", stdout.getvalue())
                self.assertEqual("", stderr.getvalue())

    def test_executable_help_and_argus_root_override(self) -> None:
        help_result = subprocess.run([str(ROOT / "scripts" / "argus"), "--help"], text=True, capture_output=True, check=False)
        self.assertEqual(0, help_result.returncode)
        self.assertIn("dashboard", help_result.stdout)
        command_help = subprocess.run(
            [str(ROOT / "scripts" / "argus"), "dashboard", "url", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, command_help.returncode)
        for contract in ("Privilege: unprivileged, read-only", "Prerequisites:", "Source:", "Example:", "Recovery:"):
            self.assertIn(contract, command_help.stdout)

        directory = self.repo({"bind": "tailscale", "url": "https://override.example.ts.net:8448"})
        self.addCleanup(directory.cleanup)
        environment = os.environ.copy()
        environment["ARGUS_ROOT"] = directory.name
        result = subprocess.run(
            [str(ROOT / "scripts" / "argus"), "dashboard", "url", "--json"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("https://override.example.ts.net:8448", json.loads(result.stdout)["data"]["url"])

    def test_funnel_enabled_or_missing_fails_closed(self) -> None:
        for observed in (
            {"funnel": {"enabled": True, "allowedInP0": False, "url": "", "target": ""}},
            {"funnel": {"enabled": False, "allowedInP0": True, "url": "", "target": ""}},
            {"funnel": {"enabled": False, "allowedInP0": False, "url": "https://host.example.ts.net", "target": ""}},
            {},
            None,
        ):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "config"
                config.mkdir()
                (config / "routes.json").write_text(
                    json.dumps(
                        {
                            "dashboard": {"bind": "tailscale", "url": "https://host.example.ts.net"},
                            "observed": observed,
                        }
                    )
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                code = run(["--json", "dashboard", "url"], repo=Path(directory), stdout=stdout, stderr=stderr)
                self.assertEqual(3, code)
                self.assertEqual("dashboard-funnel-state-unsafe", json.loads(stdout.getvalue())["error"]["code"])

    def test_entrypoint_refuses_unsupported_python_with_a_typed_hint(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "version_info", (3, 9, 6, "final", 0)),
            mock.patch.object(sys, "stderr", stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_path(str(ROOT / "scripts" / "argus"), run_name="__main__")
        self.assertEqual(2, raised.exception.code)
        self.assertIn("ERROR unsupported-python", stderr.getvalue())
        self.assertIn("Python 3.14", stderr.getvalue())
        self.assertIn("mise", stderr.getvalue())

    def test_invalid_json_invocation_uses_versioned_envelope(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(["--json", "dashboard", "unknown"], repo=ROOT, stdout=stdout, stderr=stderr)
        self.assertEqual(2, code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual({"error", "ok", "schemaVersion"}, set(payload))
        self.assertEqual("invalid-invocation", payload["error"]["code"])
        self.assertIn("unknown", payload["error"]["message"])
        self.assertEqual("", stderr.getvalue())

    def test_invalid_invocation_names_the_argparse_reason(self) -> None:
        for argv, needle in (
            (["workload", "lst"], "invalid choice: 'lst'"),
            (["smoke", "status", "--last", "abc"], "invalid int value: 'abc'"),
            (["doctor", "--host"], "unrecognized arguments: --host"),
            (["workload", "show"], "the following arguments are required: workload_id"),
        ):
            with self.subTest(argv=argv):
                stdout, stderr = io.StringIO(), io.StringIO()
                code = run(argv, repo=ROOT, stdout=stdout, stderr=stderr)
                self.assertEqual(2, code)
                self.assertEqual("", stdout.getvalue())
                self.assertIn("ERROR invalid-invocation: ", stderr.getvalue())
                self.assertIn(needle, stderr.getvalue())


class StableCliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "config" / "argus").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        (self.root / "workloads" / "demo").mkdir(parents=True)
        fixtures = {
            "config/workloads.json": {
                "version": 1,
                "workloads": [
                    {
                        "id": "demo",
                        "name": "Demo",
                        "kind": "web-app",
                        "lifecycle": "active",
                        "migration": {"status": "planned"},
                    }
                ],
            },
            "config/privacy.json": {"workloads": {"demo": {"privacy": "personal"}}},
            "config/access.json": {
                "workloads": {"demo": {"desired": "tailnet", "effective": "tailnet"}}
            },
            "config/argus/workload-classification.json": {
                "workloads": {"demo": {"trustDomain": "personal-sandbox"}}
            },
            "workloads/demo/manifest.json": {
                "operations": {
                    "logs": {"allowed": True},
                    "restart": {"allowed": False},
                }
            },
            "config/core-boundary-policy.json": {
                "policyVersion": "argus-core-boundary-v1",
                "auditVersion": "argus-core-boundary-audit-v1",
            },
        }
        for relative, payload in fixtures.items():
            (self.root / relative).write_text(json.dumps(payload))

    def invoke(self, arguments: list[str], *, runner=None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        kwargs = {}
        if runner is not None:
            kwargs["command_runner"] = runner
        code = run(arguments, repo=self.root, stdout=stdout, stderr=stderr, **kwargs)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_estate_truth_is_success_and_refresh_queues_an_inert_request(self) -> None:
        code, output, error = self.invoke(["estate", "coverage", "--json"])
        self.assertEqual(0, code)
        coverage = json.loads(output)["data"]["coverage"]
        self.assertFalse(coverage["complete"])
        self.assertEqual("rootful-compose-containers-only", coverage["legacyRefreshScope"])
        self.assertIn("rootless-docker", coverage["requiredSources"])
        self.assertEqual("", error)

        code, output, error = self.invoke(["estate", "refresh", "--json"])
        self.assertEqual(0, code)
        payload = json.loads(output)
        self.assertEqual("queued", payload["data"]["request"]["state"])
        self.assertFalse(payload["data"]["safeToMoveWorkloads"])
        self.assertEqual("", error)

    def test_workload_list_and_show_are_sanitized_and_deterministic(self) -> None:
        code, output, _ = self.invoke(["workload", "list", "--json"])
        self.assertEqual(0, code)
        row = json.loads(output)["data"]["workloads"][0]
        self.assertEqual("personal-sandbox", row["trustDomain"])
        self.assertNotIn("path", output.lower())

        code, output, _ = self.invoke(["workload", "show", "demo", "--json"])
        self.assertEqual(0, code)
        workload = json.loads(output)["data"]["workload"]
        self.assertEqual({"logs": True, "restart": False}, workload["capabilities"])
        self.assertNotIn("secret", output.lower())

    def test_malformed_nested_workload_shapes_fail_closed(self) -> None:
        privacy_path = self.root / "config" / "privacy.json"
        privacy_path.write_text(json.dumps({"workloads": []}))
        code, output, error = self.invoke(["workload", "list", "--json"])
        self.assertEqual(3, code)
        self.assertEqual("workload-registry-invalid", json.loads(output)["error"]["code"])
        self.assertNotIn("Traceback", output + error)

    def test_duplicate_ids_control_text_and_bad_manifest_fail_closed(self) -> None:
        workloads_path = self.root / "config" / "workloads.json"
        duplicate = {
            "version": 1,
            "workloads": [
                {"id": "demo", "name": "Demo", "migration": {}},
                {"id": "demo", "name": "Other", "migration": {}},
            ],
        }
        workloads_path.write_text(json.dumps(duplicate))
        code, output, _ = self.invoke(["workload", "list", "--json"])
        self.assertEqual(3, code)
        self.assertEqual("workload-registry-invalid", json.loads(output)["error"]["code"])

        duplicate["workloads"] = [{"id": "demo", "name": "forged\nPASS", "migration": {}}]
        workloads_path.write_text(json.dumps(duplicate))
        code, output, error = self.invoke(["workload", "list"])
        self.assertEqual(3, code)
        self.assertEqual("", output)
        self.assertNotIn("forged", error)

        duplicate["workloads"] = [{"id": "demo", "name": "Demo", "migration": {}}]
        workloads_path.write_text(json.dumps(duplicate))
        (self.root / "workloads" / "demo" / "manifest.json").write_text(
            json.dumps({"operations": []})
        )
        code, output, _ = self.invoke(["workload", "show", "demo", "--json"])
        self.assertEqual(3, code)
        self.assertEqual("workload-manifest-invalid", json.loads(output)["error"]["code"])

    def test_move_preview_status_refusal_and_unavailable_are_distinct(self) -> None:
        code, output, _ = self.invoke(["workload", "move", "preview", "demo", "--json"])
        self.assertEqual(0, code)
        preview = json.loads(output)["data"]
        self.assertFalse(preview["eligible"])
        self.assertEqual([], preview["eligibleTargets"])
        self.assertIsNone(preview["migrationId"])
        self.assertEqual("not-started", preview["phase"])
        self.assertEqual("personal-sandbox", preview["currentAuthority"])
        self.assertTrue(preview["retrySafe"])
        self.assertEqual("argus workload move status demo --json", preview["statusCommand"])
        self.assertEqual("argus workload move preview demo --json", preview["recoveryCommand"])

        code, output, _ = self.invoke(["workload", "move", "preflight", "demo", "--json"])
        self.assertEqual(3, code)
        preflight = json.loads(output)
        self.assertEqual("workload-move-preflight-blocked", preflight["error"]["code"])
        self.assertEqual("workload.move.preflight", preflight["data"]["command"])
        self.assertTrue(preflight["data"]["retrySafe"])

        code, output, _ = self.invoke(["workload", "move", "apply", "demo", "--json"])
        self.assertEqual(3, code)
        unconfirmed = json.loads(output)
        self.assertEqual("workload-move-confirmation-required", unconfirmed["error"]["code"])
        self.assertEqual("not-started", unconfirmed["data"]["phase"])
        self.assertTrue(unconfirmed["data"]["retrySafe"])

        code, output, _ = self.invoke(
            ["workload", "move", "apply", "demo", "--confirm", "demo", "--json"]
        )
        self.assertEqual(3, code)
        unavailable = json.loads(output)
        self.assertEqual("workload-move-preflight-blocked", unavailable["error"]["code"])
        self.assertIsNone(unavailable["data"]["migrationId"])
        self.assertEqual("personal-sandbox", unavailable["data"]["currentAuthority"])

        code, output, _ = self.invoke(["workload", "move", "status", "demo", "--json"])
        self.assertEqual(0, code)
        status = json.loads(output)["data"]
        self.assertEqual("not-started", status["phase"])
        self.assertEqual("workload.move.status", status["command"])
        self.assertEqual("argus workload move preview demo --json", status["recoveryCommand"])

    def test_unreadable_migration_ledger_has_a_typed_preview(self) -> None:
        ledger = self.root / "unreadable-operations.sqlite3"
        ledger.touch()
        with (
            patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger)}, clear=False),
            patch("argus_cli.OperationLedger", side_effect=sqlite3.OperationalError("permission denied")),
        ):
            code, output, error = self.invoke(["workload", "move", "preview", "demo", "--json"])
        self.assertEqual(4, code)
        payload = json.loads(output)
        self.assertEqual("migration-ledger-unreadable", payload["error"]["code"])
        self.assertNotIn("internal-error", output)
        self.assertEqual("", error)

    def test_corrupt_migration_ledger_is_an_error_not_not_started(self) -> None:
        ledger = self.root / "corrupt-operations.sqlite3"
        ledger.write_text("junk")
        with patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger)}, clear=False):
            for action in ("preview", "status"):
                with self.subTest(action=action):
                    code, output, _ = self.invoke(["workload", "move", action, "demo", "--json"])
                    self.assertEqual(4, code)
                    payload = json.loads(output)
                    self.assertEqual("migration-ledger-unreadable", payload["error"]["code"])
                    self.assertNotIn("not-started", output)

    def test_operation_show_is_read_only_and_recovery_is_typed(self) -> None:
        ledger = self.root / "operations.sqlite3"
        durable = OperationLedger(ledger)
        operation_id = "00000000-0000-0000-0000-000000000001"
        operation, _ = durable.create(
            workload_id="demo",
            trust_domain="personal-sandbox",
            operation_type="health.refresh",
            requested_by="operator@example.com",
            parameters={},
            preview_digest="preview",
            expected_revision="revision",
            policy_version="1",
            idempotency_key="cli-operation-show",
        )
        operation_id = str(operation["operation_id"])
        durable.transition(operation_id, {"queued"}, "running", started_at=1)
        durable.transition(
            operation_id,
            {"running"},
            "succeeded",
            finished_at=2,
            redacted_summary="Healthy.",
        )
        before = ledger.read_bytes()
        with mock.patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger)}):
            code, output, _ = self.invoke(["operation", "show", operation_id, "--json"])
        self.assertEqual(0, code)
        self.assertEqual("succeeded", json.loads(output)["data"]["operation"]["state"])
        self.assertEqual(before, ledger.read_bytes())

        code, _, _ = self.invoke(["operation", "recover", operation_id, "--json"])
        self.assertEqual(2, code)

    def test_completed_migration_remains_available_for_an_inert_rollback_draft(self) -> None:
        ledger_path = self.root / "operations.sqlite3"
        ledger = OperationLedger(ledger_path)
        payload = {
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
        preview = {**payload, "previewDigest": digest(payload)}
        parent, _ = ledger.create_migration(
            workload_id="demo",
            source_trust_domain="personal-sandbox",
            target_trust_domain="personal-managed",
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
            preview=preview,
            preview_digest=preview["previewDigest"],
            expected_revision="revision",
            policy_version="1",
            observation_digest="sha256:" + "a" * 64,
            idempotency_key="completed-migration",
        )
        migration_id = str(parent["migration_id"])
        ledger.approve_migration(
            migration_id,
            requested_by="operator@example.com",
            originating_session_hash="b" * 64,
        )
        phase = "source-fencing"
        for next_phase in (
            "source-fenced", "target-preparing", "target-starting",
            "target-verified", "route-switching", "authority-committed",
            "canonical-committed", "verifying", "succeeded",
        ):
            ledger.transition_migration(migration_id, {phase}, next_phase)
            phase = next_phase
        with mock.patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger_path)}):
            code, output, _ = self.invoke(
                ["workload", "move", "rollback", "demo", "--confirm", "demo", "--json"]
            )
        self.assertEqual(0, code)
        result = json.loads(output)["data"]
        self.assertEqual("rollback-drafted", result["phase"])
        self.assertEqual("none", result["authority"])
        self.assertEqual(migration_id, result["draft"]["migrationId"])

    def test_eligible_apply_creates_only_an_inert_dashboard_handoff_draft(self) -> None:
        ledger_path = self.root / "operations.sqlite3"
        ledger = OperationLedger(ledger_path)
        preview_payload = {
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
        preview = {**preview_payload, "previewDigest": digest(preview_payload)}
        with (
            mock.patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger_path)}),
            mock.patch("argus_cli.migration_preview", return_value=preview),
        ):
            code, output, _ = self.invoke(
                ["workload", "move", "apply", "demo", "--confirm", "demo", "--json"]
            )
        self.assertEqual(0, code)
        result = json.loads(output)["data"]
        self.assertEqual("workload.move.apply-draft", result["command"])
        self.assertEqual("drafted", result["phase"])
        self.assertEqual("none", result["authority"])
        self.assertEqual([], ledger.list_migrations_for_workload("demo"))

    def test_operation_missing_is_unavailable_not_not_found(self) -> None:
        operation_id = "00000000-0000-0000-0000-000000000001"
        code, output, _ = self.invoke(["operation", "show", operation_id, "--json"])
        self.assertEqual(4, code)
        self.assertEqual("operation-ledger-unavailable", json.loads(output)["error"]["code"])

    def test_doctor_reports_only_safe_compatibility_fields(self) -> None:
        revision = "a" * 40

        def runner(command, _repo):
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, revision + "\n", "")
            return subprocess.CompletedProcess(command, 0, '{"ok":true,"checks":[]}', "")

        code, output, error = self.invoke(["doctor", "--json"], runner=runner)
        self.assertEqual(0, code)
        data = json.loads(output)["data"]
        self.assertEqual(revision, data["argusRevision"])
        self.assertEqual("not-installed", data["collectorProtocol"]["deployed"])
        self.assertEqual("partial-discovery-not-installed", data["compatibility"])
        self.assertNotIn("credential", output.lower())
        self.assertNotIn("topology", output.lower())
        self.assertEqual("", error)

    def test_doctor_audit_failure_names_the_failing_checks(self) -> None:
        checks = [
            {"ok": True, "message": "tracked secrets absent"},
            {"ok": False, "message": "deterministic core boundary audit available"},
            {"ok": False, "message": "sudoers drop-in reviewed", "path": "/etc/sudoers.d/argus"},
        ]

        def runner(command, _repo):
            return subprocess.CompletedProcess(command, 1, json.dumps({"ok": False, "checks": checks}), "")

        code, output, _ = self.invoke(["doctor", "--json"], runner=runner)
        self.assertEqual(3, code)
        payload = json.loads(output)
        self.assertEqual("doctor-audit-failed", payload["error"]["code"])
        self.assertIn("deterministic core boundary audit available", payload["error"]["message"])
        self.assertEqual(
            ["deterministic core boundary audit available", "sudoers drop-in reviewed"],
            payload["data"]["failedChecks"],
        )
        self.assertNotIn("/etc/sudoers.d", output)

    def test_doctor_and_check_run_helpers_under_the_current_interpreter(self) -> None:
        calls: list[list[str]] = []

        def runner(command, _repo):
            calls.append(command)
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, "c" * 40 + "\n", "")
            return subprocess.CompletedProcess(command, 0, '{"ok":true,"checks":[]}', "")

        self.invoke(["doctor", "--json"], runner=runner)
        self.invoke(["check", "--json"], runner=runner)
        helpers = [command for command in calls if command[0] != "git"]
        self.assertEqual(
            [
                [sys.executable, str(self.root / "scripts" / "argus-doctor"), "--json"],
                [sys.executable, str(self.root / "scripts" / "argus-check")],
            ],
            helpers,
        )

    def test_check_pass_failure_and_interruption_have_stable_classes(self) -> None:
        revision = "b" * 40

        def passing(command, _repo):
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, revision + "\n", "")
            return subprocess.CompletedProcess(command, 0, "ARGUS_CHECK_PASS\n", "")

        code, output, _ = self.invoke(["check", "--json"], runner=passing)
        self.assertEqual(0, code)
        self.assertEqual("pass", json.loads(output)["data"]["result"])

        def failing(command, _repo):
            return subprocess.CompletedProcess(command, 1, "private-looking failure detail", "")

        code, output, _ = self.invoke(["check", "--json"], runner=failing)
        self.assertEqual(1, code)
        payload = json.loads(output)
        self.assertEqual("repository-check-failed", payload["error"]["code"])
        self.assertNotIn("private-looking", output)
        self.assertTrue(payload["error"]["evidenceId"].startswith("sha256:"))

        def interrupted(command, _repo):
            return subprocess.CompletedProcess(command, 130, "partial", "")

        code, output, _ = self.invoke(["check", "--json"], runner=interrupted)
        self.assertEqual(5, code)
        self.assertEqual("repository-check-interrupted", json.loads(output)["error"]["code"])

        def crashes(_command, _repo):
            raise RuntimeError("private-looking internal detail")

        code, output, error = self.invoke(["check", "--json"], runner=crashes)
        self.assertEqual(1, code)
        payload = json.loads(output)
        self.assertEqual("internal-error", payload["error"]["code"])
        self.assertRegex(payload["error"]["evidenceId"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("private-looking", output + error)
        self.assertNotIn("argus check", payload["error"]["nextAction"])
        self.assertIn("TRACE RuntimeError", error)
        self.assertIn("argus_cli.py:", error)
        self.assertIn("in crashes", error)

        def other_crash(_command, _repo):
            raise RuntimeError("different site")

        other = json.loads(self.invoke(["check", "--json"], runner=other_crash)[1])
        self.assertNotEqual(payload["error"]["evidenceId"], other["error"]["evidenceId"])

    def test_human_failure_is_stderr_only_and_actionable(self) -> None:
        code, output, error = self.invoke(["estate", "refresh"])
        self.assertEqual(0, code)
        self.assertIn("estate.refresh", output)
        self.assertEqual("", error)

        code, output, error = self.invoke(["workload", "move", "preflight", "demo"])
        self.assertEqual(3, code)
        self.assertEqual("", output)
        for marker in (
            "MIGRATION_ID none PHASE not-started",
            "STATUS argus workload move status demo --json",
            "RECOVERY argus workload move preview demo --json",
        ):
            self.assertIn(marker, error)

    def test_compatibility_aliases_emit_exact_replacements(self) -> None:
        code, output, error = self.invoke(["workloads"])
        self.assertEqual(0, code)
        self.assertIn("demo", output)
        self.assertIn("use argus workload list", error)

        code, output, _ = self.invoke(["migration-plan", "demo", "--json"])
        self.assertEqual(0, code)
        self.assertIn("argus workload move preview", json.loads(output)["data"]["deprecation"])

    def test_documented_and_installed_public_surface_is_bidirectional(self) -> None:
        contract = json.loads((ROOT / "config" / "public-cli.json").read_text())
        operations = (ROOT / "docs" / "OPERATIONS.md").read_text()
        self.assertEqual(contract["executableLinks"], APPROVED_OPERATOR_LINKS)
        self.assertEqual({"argus": "argus"}, contract["executableLinks"])
        for item in contract["commands"]:
            self.assertIn(f"`{item['privilege']}` — `{item['command']}`", operations)
        for legacy, replacement in contract["compatibility"].items():
            self.assertIn(f"`{legacy}` → `{replacement}`", operations)

    def test_every_public_leaf_help_has_complete_contract(self) -> None:
        commands = (
            ["dashboard", "url"],
            ["estate", "status"],
            ["estate", "refresh"],
            ["estate", "coverage"],
            ["workload", "list"],
            ["workload", "show"],
            ["workload", "move", "preview"],
            ["workload", "move", "preflight"],
            ["workload", "move", "apply"],
            ["workload", "move", "status"],
            ["workload", "move", "rollback"],
            ["operation", "show"],
            ["op", "preview"],
            ["op", "create"],
            ["op", "show"],
            ["op", "watch"],
            ["workload", "deploy"],
            ["workload", "start"],
            ["workload", "stop"],
            ["workload", "restart"],
            ["doctor"],
            ["check"],
        )
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(
                    [str(ROOT / "scripts" / "argus"), *command, "--help"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                for marker in (
                    "Privilege:",
                    "Prerequisites:",
                    "Side effects:",
                    "Source:",
                    "Output:",
                    "Example:",
                    "Recovery:",
                ):
                    self.assertIn(marker, result.stdout)


class OperatorLinkTransitionTests(unittest.TestCase):
    def run_installer(self, prefix: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["ARGUS_ROOT"] = str(ROOT)
        return subprocess.run(
            [str(ROOT / "scripts" / "install-operator-links"), "--prefix", str(prefix), *arguments],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    def test_check_and_dry_run_report_retired_link_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            retired = prefix / "argus-logs"
            target = ROOT / "scripts" / "argus-logs"
            retired.symlink_to(target)

            checked = self.run_installer(prefix, "--check")
            self.assertEqual(1, checked.returncode)
            self.assertIn("retired public link remains", checked.stdout)
            self.assertTrue(retired.is_symlink())

            previewed = self.run_installer(prefix, "--dry-run")
            self.assertEqual(0, previewed.returncode)
            self.assertIn("DRY  retire", previewed.stdout)
            self.assertTrue(retired.is_symlink())
            self.assertFalse((prefix / "argus").exists())

    def test_apply_retires_owned_link_and_installs_only_argus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            retired = prefix / "argus-logs"
            retired.symlink_to(ROOT / "scripts" / "argus-logs")

            applied = self.run_installer(prefix)
            self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
            self.assertFalse(retired.exists())
            installed = prefix / "argus"
            self.assertTrue(installed.is_symlink())
            self.assertEqual(ROOT / "scripts" / "argus", installed.resolve())

    def test_unowned_retired_path_causes_zero_apply_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            owned = prefix / "argus-logs"
            owned.symlink_to(ROOT / "scripts" / "argus-logs")
            unowned = prefix / "argus-events"
            unowned.write_text("operator-owned file\n")

            applied = self.run_installer(prefix)
            self.assertEqual(1, applied.returncode)
            self.assertIn("refusing to retire an unowned or changed path", applied.stdout)
            self.assertTrue(owned.is_symlink())
            self.assertEqual("operator-owned file\n", unowned.read_text())
            self.assertFalse((prefix / "argus").exists())


if __name__ == "__main__":
    unittest.main()
