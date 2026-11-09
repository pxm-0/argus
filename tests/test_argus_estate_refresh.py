from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_estate_refresh as refresh  # noqa: E402


class EstateRefreshCoordinatorTests(unittest.TestCase):
    def test_runner_identity_is_pinned_to_the_collector_peer_identity(self) -> None:
        with patch("argus_estate_refresh.os.geteuid", return_value=0):
            with self.assertRaisesRegex(refresh.EstateRefreshError, "uid 1000"):
                refresh.require_runner_identity()
        with patch("argus_estate_refresh.os.geteuid", return_value=1000):
            refresh.require_runner_identity()

    def test_wrapper_uses_identity_guard_for_each_mutating_mode(self) -> None:
        wrapper = (ROOT / "scripts" / "argus-estate-refresh").read_text(encoding="utf-8")
        self.assertEqual(3, wrapper.count("require_runner_identity()"))

    def test_request_and_status_are_inert_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = refresh.create_request(root, requested_by="local-cli")
            self.assertEqual("queued", request["state"])
            self.assertTrue(request["statusUrl"].endswith(request["runId"]))
            status = refresh.status_summary(root)
            self.assertEqual("never-run", status["state"])
            request_path = refresh.paths(root)["requests"] / f"{request['runId']}.json"
            self.assertTrue(request_path.is_file())
            self.assertEqual(0o640, request_path.stat().st_mode & 0o777)
            visible = refresh.read_request(root, request["runId"])
            self.assertEqual("queued", visible["state"])
            self.assertNotIn("requestedBy", visible)

    def test_pending_refresh_runs_once_and_removes_only_its_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = refresh.create_request(root, requested_by="local-cli")
            result = {
                "schemaVersion": 1,
                "runId": request["runId"],
                "state": "completed",
                "safeToMoveWorkloads": False,
            }
            with patch("argus_estate_refresh.run_refresh", return_value=result) as run_once:
                outcomes = refresh.run_pending(root)
            self.assertEqual([result], outcomes)
            run_once.assert_called_once_with(root, request["runId"], collector=None)
            self.assertFalse((refresh.paths(root)["requests"] / f"{request['runId']}.json").exists())

    def test_refresh_writes_sanitized_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "refresh-00000000-0000-4000-8000-000000000001"
            repository = MagicMock()
            repository.__enter__.return_value = repository
            repository.__exit__.return_value = False
            repository.recover_interrupted.return_value = 0
            repository.prune.return_value = 0
            scheduler = MagicMock()
            scheduler.refresh.return_value = {"schemaVersion": 1, "refreshId": run_id, "status": "completed", "sources": []}
            reconciliation = {
                "coverage": {"status": "complete", "configuredSources": 0, "freshSources": 0, "sources": [], "registryDigest": "digest", "gapDigest": "digest"},
                "status": "complete",
                "safeToMoveWorkloads": True,
                "evidenceDigest": "digest",
            }
            with (
                patch("argus_estate_refresh.load_registry", return_value=MagicMock()),
                patch("argus_estate_refresh.ObservationRepository", return_value=repository),
                patch("argus_estate_refresh.CollectorScheduler", return_value=scheduler),
                patch("argus_estate_refresh.reconcile", return_value=reconciliation),
            ):
                result = refresh.run_refresh(root, run_id, explicit_clock="2026-08-28T00:00:00Z")
            self.assertEqual("completed", result["state"])
            self.assertTrue(result["safeToMoveWorkloads"])
            self.assertEqual(0, result["prunedRuns"])
            stored = refresh.read_status(root, run_id)
            self.assertEqual(run_id, stored["runId"])
            repository.recover_interrupted.assert_called_once_with(terminal_at="2026-08-28T00:00:00Z")
            repository.prune.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
