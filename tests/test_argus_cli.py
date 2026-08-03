from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_cli import run  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
