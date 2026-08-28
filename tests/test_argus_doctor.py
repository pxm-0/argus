from __future__ import annotations

import json
import runpy
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class DoctorBoundaryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
        self.core_boundary_check = self.namespace["core_boundary_check"]
        self.globals = self.core_boundary_check.__globals__

    def audit_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        payload = {
            "auditResult": "pass",
            "policyVersion": "argus-core-boundary-v1",
            "auditVersion": "argus-core-boundary-audit-v1",
            "sbomDigest": "sha256:fixture",
            "endpointDigest": "sha256:fixture",
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    def test_host_doctor_runs_boundary_audit_as_reviewed_checkout_owner(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return self.audit_result(command)

        with (
            patch.object(self.globals["os"], "geteuid", return_value=0),
            patch.object(self.globals["pwd"], "getpwuid", return_value=SimpleNamespace(pw_name="oreo")),
            patch.object(self.globals["shutil"], "which", return_value="/usr/sbin/runuser"),
            patch.dict(self.globals, {"run": runner}),
        ):
            checks: list[dict[str, object]] = []
            self.core_boundary_check(checks)

        self.assertEqual(1, len(calls))
        self.assertEqual(
            ["/usr/sbin/runuser", "-u", "oreo", "--", str(ROOT / "scripts" / "argus-check"), "--boundary-only", "--boundary-json"],
            calls[0],
        )
        self.assertTrue(checks[0]["ok"])

    def test_non_root_doctor_keeps_direct_boundary_audit(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return self.audit_result(command)

        with (
            patch.object(self.globals["os"], "geteuid", return_value=1000),
            patch.dict(self.globals, {"run": runner}),
        ):
            checks: list[dict[str, object]] = []
            self.core_boundary_check(checks)

        self.assertEqual([[str(ROOT / "scripts" / "argus-check"), "--boundary-only", "--boundary-json"]], calls)
        self.assertTrue(checks[0]["ok"])


if __name__ == "__main__":
    unittest.main()
