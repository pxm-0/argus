from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_server(environment: dict[str, str]):
    with patch.dict(os.environ, environment):
        spec = importlib.util.spec_from_file_location(
            "argus_control_session_boundary",
            ROOT / "control-plane" / "api" / "server.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


class SessionBoundaryTests(unittest.TestCase):
    def test_proxy_marker_peer_and_structured_allowlist_are_all_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            operators = base / "operators.json"
            marker = base / "operator-proxy-token"
            token = base / "control-token"
            operators.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "operators": [
                            {
                                "tailnetLogin": "owner@example.invalid",
                                "role": "owner",
                                "enabled": True,
                            }
                        ],
                    }
                )
            )
            marker.write_text("ARGUS_OPERATOR_PROXY_TOKEN=proxy-marker\n")
            token.write_text("bootstrap-value\n")
            server = load_server(
                {
                    "ARGUS_RUNTIME": str(base / "runtime"),
                    "ARGUS_OPERATORS_FILE": str(operators),
                    "ARGUS_PROXY_TOKEN_FILE": str(marker),
                    "ARGUS_TOKEN_FILE": str(token),
                }
            )
            headers = {
                "X-Argus-Tailnet-Login": "OWNER@example.invalid",
                "X-Argus-Proxy-Token": "proxy-marker",
            }
            self.assertEqual(
                {"identity": "owner@example.invalid", "role": "owner"},
                server.trusted_operator(headers, "127.0.0.1"),
            )
            self.assertIsNone(server.trusted_operator(headers, "192.0.2.1"))
            self.assertIsNone(
                server.trusted_operator(
                    {"X-Argus-Tailnet-Login": "owner@example.invalid"},
                    "127.0.0.1",
                )
            )
            self.assertTrue(server.bootstrap_valid("bootstrap-value"))
            self.assertFalse(server.bootstrap_valid("wrong"))

            data = json.loads(operators.read_text())
            data["operators"][0]["enabled"] = False
            operators.write_text(json.dumps(data))
            self.assertIsNone(server.trusted_operator(headers, "127.0.0.1"))

    def test_operator_disablement_revokes_an_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            operators = base / "operators.json"
            marker = base / "operator-proxy-token"
            token = base / "control-token"
            record = {
                "tailnetLogin": "owner@example.invalid",
                "role": "owner",
                "enabled": True,
            }
            operators.write_text(json.dumps({"schemaVersion": 1, "operators": [record]}))
            marker.write_text("ARGUS_OPERATOR_PROXY_TOKEN=proxy-marker\n")
            token.write_text("bootstrap-value\n")
            server = load_server(
                {
                    "ARGUS_RUNTIME": str(base / "runtime"),
                    "ARGUS_OPERATORS_FILE": str(operators),
                    "ARGUS_PROXY_TOKEN_FILE": str(marker),
                    "ARGUS_TOKEN_FILE": str(token),
                }
            )
            session = server.SESSIONS.create("owner@example.invalid")
            handler = object.__new__(server.Handler)
            handler.client_address = ("127.0.0.1", 12345)
            handler.headers = {
                "Cookie": f"argus_session={session.session_id}; argus_csrf={session.csrf_token}",
                "X-Argus-Tailnet-Login": "owner@example.invalid",
                "X-Argus-Proxy-Token": "proxy-marker",
            }
            self.assertIsNotNone(handler.current_session())

            record["enabled"] = False
            operators.write_text(json.dumps({"schemaVersion": 1, "operators": [record]}))
            self.assertIsNone(handler.current_session())

            record["enabled"] = True
            operators.write_text(json.dumps({"schemaVersion": 1, "operators": [record]}))
            self.assertIsNone(handler.current_session())

    def test_caddy_and_api_units_preserve_the_trusted_proxy_boundary(self) -> None:
        caddy = (ROOT / "caddy" / "dashboard.Caddyfile").read_text()
        api_unit = (ROOT / "systemd" / "argus-control-api.service").read_text()
        caddy_dropin = (
            ROOT / "systemd" / "caddy.service.d" / "argus-operator-proxy.conf"
        ).read_text()
        dashboard = (ROOT / "control-plane" / "dashboard" / "generate_dashboard.py").read_text()

        self.assertIn("header_up -X-Argus-*", caddy)
        self.assertIn("header_up -Tailscale-*", caddy)
        self.assertIn(
            "vars argus_tailnet_login {http.request.header.Tailscale-User-Login}",
            caddy,
        )
        self.assertIn(
            "header_up X-Argus-Tailnet-Login {vars.argus_tailnet_login}",
            caddy,
        )
        self.assertLess(
            caddy.index("vars argus_tailnet_login"),
            caddy.index("header_up -Tailscale-*"),
        )
        self.assertNotIn(
            "header_up X-Argus-Tailnet-Login "
            "{http.request.header.Tailscale-User-Login}",
            caddy,
        )
        self.assertIn("header_up X-Argus-Proxy-Token {$ARGUS_OPERATOR_PROXY_TOKEN}", caddy)
        self.assertIn("EnvironmentFile=/etc/argus/operator-proxy-token", caddy_dropin)

        self.assertIn("LoadCredential=operators.json:/etc/argus/operators.json", api_unit)
        self.assertIn("LoadCredential=operator-proxy-token:/etc/argus/operator-proxy-token", api_unit)
        self.assertIn("ARGUS_OPERATORS_FILE=%d/operators.json", api_unit)
        self.assertIn("ARGUS_PROXY_TOKEN_FILE=%d/operator-proxy-token", api_unit)
        self.assertIn("ARGUS_SESSION_DB=/var/lib/argus/control/session.sqlite3", api_unit)
        self.assertIn("InaccessiblePaths=-/var/run/docker.sock -/run/docker.sock", api_unit)

        self.assertNotIn("headers.Authorization", dashboard)
        self.assertIn('{ bootstrapToken: credential }', dashboard)
        self.assertIn('cookieValue("argus_csrf")', dashboard)
        self.assertIn('"X-Argus-CSRF-Bootstrap": bootstrapNonce()', dashboard)

    def test_activation_is_acknowledged_backed_up_and_validates_before_reload(self) -> None:
        script_path = ROOT / "scripts" / "argus-m5-session-boundary"
        script = script_path.read_text()
        self.assertTrue(os.access(script_path, os.X_OK))
        self.assertIn("--acknowledge-m5-session-boundary", script)
        self.assertIn("/var/backups/argus-m5-phase1/session-boundary", script)
        self.assertIn('validate_caddy', script)
        self.assertLess(script.index("validate_caddy\n  systemctl daemon-reload"), script.index("systemctl reload caddy.service"))
        self.assertIn("wait_for_api_fail_closed", script)
        self.assertIn("SESSION_API_READY", script)
        self.assertIn("control API did not become ready within 10 seconds", script)
        self.assertIn(
            "wait_for_api_fail_closed\n  systemctl reload caddy.service",
            script,
        )
        self.assertIn("trap rollback_on_exit EXIT", script)
        self.assertIn("restore_session_db", script)
        self.assertIn("SESSION_BOUNDARY_ROLLED_BACK", script)
        self.assertIn("publicExposureChanged=false", script)
        self.assertIn("secretsPrinted=false", script)
        self.assertNotIn("tailscale funnel --", script)
        self.assertNotIn("cloudflared tunnel", script)


if __name__ == "__main__":
    unittest.main()
