from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_cli import run  # noqa: E402
from argus_common import APPROVED_OPERATOR_LINKS  # noqa: E402


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

    def test_invalid_json_invocation_uses_versioned_envelope(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(["--json", "dashboard", "unknown"], repo=ROOT, stdout=stdout, stderr=stderr)
        self.assertEqual(2, code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual({"error", "ok", "schemaVersion"}, set(payload))
        self.assertEqual("invalid-invocation", payload["error"]["code"])
        self.assertEqual("", stderr.getvalue())


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

    def test_estate_truth_is_success_but_refresh_refuses_incomplete_scope(self) -> None:
        code, output, error = self.invoke(["estate", "coverage", "--json"])
        self.assertEqual(0, code)
        coverage = json.loads(output)["data"]["coverage"]
        self.assertFalse(coverage["complete"])
        self.assertEqual("rootful-compose-containers-only", coverage["legacyRefreshScope"])
        self.assertIn("rootless-docker", coverage["requiredSources"])
        self.assertEqual("", error)

        code, output, error = self.invoke(["estate", "refresh", "--json"])
        self.assertEqual(3, code)
        payload = json.loads(output)
        self.assertEqual("estate-refresh-contract-incomplete", payload["error"]["code"])
        self.assertFalse(payload["error"]["retrySafe"])
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
        self.assertFalse(unconfirmed["data"]["retrySafe"])

        code, output, _ = self.invoke(
            ["workload", "move", "apply", "demo", "--confirm", "demo", "--json"]
        )
        self.assertEqual(4, code)
        unavailable = json.loads(output)
        self.assertEqual("workload-move-kernel-unavailable", unavailable["error"]["code"])
        self.assertIsNone(unavailable["data"]["migrationId"])
        self.assertEqual("personal-sandbox", unavailable["data"]["currentAuthority"])

        code, output, _ = self.invoke(["workload", "move", "status", "demo", "--json"])
        self.assertEqual(0, code)
        status = json.loads(output)["data"]
        self.assertEqual("not-started", status["phase"])
        self.assertEqual("workload.move.status", status["command"])
        self.assertEqual("argus workload move preview demo --json", status["recoveryCommand"])

    def test_operation_show_is_read_only_and_recovery_is_typed(self) -> None:
        ledger = self.root / "operations.sqlite3"
        connection = sqlite3.connect(ledger)
        connection.execute("PRAGMA user_version=1")
        connection.execute(
            """
            CREATE TABLE operations (
                operation_id TEXT, workload_id TEXT, trust_domain TEXT,
                operation_type TEXT, state TEXT, created_at INTEGER,
                started_at INTEGER, finished_at INTEGER, error_class TEXT,
                redacted_summary TEXT
            )
            """
        )
        operation_id = "00000000-0000-0000-0000-000000000001"
        connection.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (operation_id, "demo", "personal-sandbox", "health.refresh", "succeeded", 1, 2, 3, None, "Healthy."),
        )
        connection.commit()
        connection.close()
        before = ledger.read_bytes()
        with mock.patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger)}):
            code, output, _ = self.invoke(["operation", "show", operation_id, "--json"])
        self.assertEqual(0, code)
        self.assertEqual("succeeded", json.loads(output)["data"]["operation"]["state"])
        self.assertEqual(before, ledger.read_bytes())

        code, output, _ = self.invoke(["operation", "recover", operation_id, "--json"])
        self.assertEqual(3, code)
        self.assertEqual("operation-recovery-confirmation-required", json.loads(output)["error"]["code"])
        code, output, _ = self.invoke(
            ["operation", "recover", operation_id, "--confirm", operation_id, "--json"]
        )
        self.assertEqual(4, code)
        self.assertEqual("operation-recovery-unavailable", json.loads(output)["error"]["code"])

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
        self.assertNotIn("private-looking", output)
        self.assertEqual("", error)

    def test_human_failure_is_stderr_only_and_actionable(self) -> None:
        code, output, error = self.invoke(["estate", "refresh"])
        self.assertEqual(3, code)
        self.assertEqual("", output)
        for marker in ("ERROR estate-refresh-contract-incomplete", "AUTHORITY", "RETRY_SAFE", "NEXT"):
            self.assertIn(marker, error)

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
            ["operation", "recover"],
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
