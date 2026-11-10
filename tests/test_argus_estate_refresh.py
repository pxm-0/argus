from __future__ import annotations

from datetime import UTC, datetime
import os
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


class StatusPruneTests(unittest.TestCase):
    NOW = datetime(2026, 1, 31, 12, 0, tzinfo=UTC).timestamp()

    def make(self, root: Path, run_number: int, mtime: float, *, state: str = "completed") -> str:
        run_id = f"refresh-{run_number:08x}-0000-4000-8000-000000000000"
        path = refresh.paths(root)["status"] / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return run_id

    def names(self, root: Path) -> set[str]:
        return {path.stem for path in refresh.paths(root)["status"].glob("*.json")}

    def test_prune_keeps_recent_720_newest_per_day_for_30_days_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recent = [self.make(root, i, self.NOW - i * 60) for i in range(1000)]  # ~16.6 hours
            day = 86400
            morning = {d: self.make(root, 10_000 + d, self.NOW - d * day - 6 * 3600) for d in range(2, 9)}
            evening = {d: self.make(root, 20_000 + d, self.NOW - d * day - 2 * 3600) for d in range(2, 9)}
            ancient = self.make(root, 30_000, self.NOW - 40 * day)
            referenced_old = self.make(root, 30_001, self.NOW - 45 * day)
            queued_old = self.make(root, 30_002, self.NOW - 46 * day)
            refresh._write_status(root, {"schemaVersion": 1, "runId": referenced_old, "state": "completed"})
            os.utime(refresh.paths(root)["status"] / f"{referenced_old}.json", (self.NOW - 45 * day,) * 2)
            (refresh.paths(root)["requests"]).mkdir(parents=True, exist_ok=True)
            (refresh.paths(root)["requests"] / f"{queued_old}.json").write_text("{}", encoding="utf-8")
            (refresh.paths(root)["status"] / "notes.txt").write_text("keep", encoding="utf-8")

            removed = refresh.prune_status(root, now=self.NOW)

            kept = self.names(root)
            # recent[721] is 23:59 the previous UTC day: outside the newest 720 but the newest of its day
            self.assertEqual(set(recent[:720]) | {recent[721]}, kept & set(recent))
            self.assertTrue(set(evening.values()) <= kept)
            self.assertFalse(kept & set(morning.values()))
            self.assertNotIn(ancient, kept)
            self.assertIn(referenced_old, kept)
            self.assertIn(queued_old, kept)
            self.assertTrue((refresh.paths(root)["status"] / "notes.txt").exists())
            self.assertTrue(refresh.paths(root)["latest"].is_file())
            self.assertEqual(279 + len(morning) + 1, removed)

    def test_prune_is_a_no_op_on_a_small_directory_and_tolerates_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = self.make(root, 1, self.NOW)
            self.assertEqual(0, refresh.prune_status(root, now=self.NOW))
            self.assertEqual({run_id}, self.names(root))


if __name__ == "__main__":
    unittest.main()
