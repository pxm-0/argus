from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m4_hello_nginx import PreflightError, evaluate_preflight  # noqa: E402


def arguments() -> dict:
    return {
        "backup_summary": {"workloadId": "hello-nginx", "sourceIncluded": True, "envIncluded": False, "volumesIncluded": False, "databaseIncluded": False},
        "backup_manifest": {"id": "hello-nginx"},
        "archive_digest": "sha256:archive",
        "expected_archive_digest": "sha256:archive",
        "restore_compose_present": True,
        "source_health": True,
        "target_daemon_active": True,
        "target_socket_present": True,
        "target_empty": True,
        "target_has_no_tcp_listeners": True,
    }


class HelloNginxPreflightTest(unittest.TestCase):
    def test_accepts_complete_read_only_evidence_without_approving_migration(self) -> None:
        result = evaluate_preflight(**arguments())
        self.assertFalse(result["migrationApproved"])
        self.assertEqual("review-controlled-cutover-plan", result["nextGate"])

    def test_rejects_missing_isolation_or_wrong_backup(self) -> None:
        missing_listener_check = arguments()
        missing_listener_check["target_has_no_tcp_listeners"] = False
        with self.assertRaises(PreflightError):
            evaluate_preflight(**missing_listener_check)
        wrong_backup = arguments()
        wrong_backup["backup_summary"]["workloadId"] = "hastur"
        with self.assertRaises(PreflightError):
            evaluate_preflight(**wrong_backup)
