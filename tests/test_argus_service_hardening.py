from __future__ import annotations

import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "control-plane" / "monitoring"))

import collect_metrics  # noqa: E402


def unit_keys(name: str) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in (ROOT / "systemd" / name).read_text().splitlines():
        if "=" in line and not line.startswith(("#", "[")):
            key, value = line.split("=", 1)
            keys.setdefault(key, []).append(value.strip())
    return keys


class ApiUnitHardeningTests(unittest.TestCase):
    def test_hardening_keys(self) -> None:
        keys = unit_keys("argus-control-api.service")
        self.assertEqual(["argus-api"], keys["User"])
        self.assertEqual(["argus-control"], keys["Group"])
        self.assertEqual([""], keys["CapabilityBoundingSet"])
        self.assertEqual(["AF_UNIX AF_INET AF_INET6"], keys["RestrictAddressFamilies"])
        self.assertEqual(["@system-service"], keys["SystemCallFilter"])
        for key in ("NoNewPrivileges", "ProtectHome", "PrivateTmp", "MemoryDenyWriteExecute", "LockPersonality"):
            self.assertIn(keys[key][0], {"yes", "true"}, key)
        self.assertEqual(["strict"], keys["ProtectSystem"])
        self.assertIn("/var/lib/argus/control", keys["ReadWritePaths"][0].split())

    def test_state_directory_is_not_managed_by_the_api_unit(self) -> None:
        # StateDirectory would re-chown the shared ledger directory to the API user.
        self.assertNotIn("StateDirectory", unit_keys("argus-control-api.service"))

    def test_sysusers_creates_unprivileged_member_of_control_group(self) -> None:
        text = (ROOT / "systemd" / "sysusers.d" / "argus-api.conf").read_text()
        self.assertIn("u argus-api", text)
        self.assertIn("m argus-api argus-control", text)
        self.assertNotIn("sudo", text.replace("no sudo", ""))

    def test_metrics_unit_is_bounded(self) -> None:
        keys = unit_keys("argus-metrics.service")
        self.assertEqual(["60"], keys["TimeoutStartSec"])
        self.assertIn("RuntimeMaxSec", keys)


class DoctorApiUserTests(unittest.TestCase):
    def run_doctor(self, show: str, groups: str, sudoers: str | None = None) -> list[dict]:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
        func = namespace["api_service_user_checks"]
        checks: list[dict] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, show if command[0] == "systemctl" else groups, "")

        with tempfile.TemporaryDirectory() as tmp:
            if sudoers is not None:
                (Path(tmp) / "90-x").write_text(sudoers)
            real_path = Path
            func.__globals__["run"] = runner
            func.__globals__["Path"] = lambda a, *r: real_path(tmp) if a == "/etc/sudoers.d" else real_path(a, *r)
            func(checks)
        return checks

    GOOD = "User=argus-api\nCapabilityBoundingSet=\n"

    def test_clean_unit_passes(self) -> None:
        checks = self.run_doctor(self.GOOD, "argus-api argus-control")
        self.assertTrue(all(c["ok"] for c in checks), checks)

    def test_sudo_or_docker_member_fails(self) -> None:
        for groups in ("oreo sudo", "oreo docker"):
            checks = self.run_doctor("User=oreo\nCapabilityBoundingSet=\n", groups)
            self.assertFalse(all(c["ok"] for c in checks), groups)

    def test_nonempty_capability_set_fails(self) -> None:
        checks = self.run_doctor("User=argus-api\nCapabilityBoundingSet=cap_net_admin\n", "argus-api")
        self.assertTrue(any(not c["ok"] and "capability" in c["message"] for c in checks))

    def test_nopasswd_dropin_warns_without_failing(self) -> None:
        checks = self.run_doctor(self.GOOD, "argus-api", "argus-api ALL=(ALL) NOPASSWD: ALL\n")
        warns = [c for c in checks if c.get("warn")]
        self.assertEqual(1, len(warns))
        self.assertTrue(all(c["ok"] for c in checks))


class MetricsTimeoutTests(unittest.TestCase):
    def test_stuck_docker_stats_returns_empty_instead_of_hanging(self) -> None:
        def stuck(command, **kwargs):
            self.assertIsNotNone(kwargs.get("timeout"))
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with patch.object(collect_metrics.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            collect_metrics.subprocess, "run", side_effect=stuck
        ):
            self.assertEqual([], collect_metrics.docker_stats())


class ApiIdentityScriptTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (ROOT / "scripts" / name).read_text()

    def test_scripts_expect_argus_api_service_user(self) -> None:
        self.assertIn('SERVICE_USER="argus-api"', self.read("argus-control-plane-reconcile"))
        boundary = self.read("argus-m5-session-boundary")
        self.assertIn("argus-api:argus-control", boundary)
        self.assertNotIn('== "oreo" ]]', boundary)

    def test_runtime_permissions_gives_session_db_to_argus_api(self) -> None:
        script = self.read("argus-m5-runtime-permissions")
        self.assertIn('SESSION_OWNER="argus-api"', script)
        self.assertIn('chown "$SESSION_OWNER:$CONTROL_GROUP" "$path"', script)

    def test_runtime_permissions_reconciles_audit_log_and_discovery(self) -> None:
        script = self.read("argus-m5-runtime-permissions")
        self.assertIn('AUDIT_LOG="$ROOT/runtime/audit.log"', script)
        self.assertIn('"$DISCOVERY_DIR/latest.json"', script)
        self.assertIn('install -m 0664 -o "$API_USER" -g "$CONTROL_GROUP" /dev/null "$AUDIT_LOG"', script)
        self.assertRegex(script, r'install -d -m 2775 [^\n]*"\$DISCOVERY_DIR"')

    def test_runbook_covers_audit_log_and_discovery(self) -> None:
        runbook = (ROOT / "docs" / "RUNBOOKS" / "api-service-user-migration.md").read_text()
        for needle in ("runtime/audit.log", "runtime/discovery", "chgrp argus-control"):
            self.assertIn(needle, runbook)
        self.assertNotIn("chown root:argus-control /var/lib/argus/control", runbook)


if __name__ == "__main__":
    unittest.main()
