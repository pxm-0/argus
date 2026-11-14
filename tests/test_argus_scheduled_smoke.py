from __future__ import annotations

import contextlib
import importlib.machinery
import io
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "argus-smoke-scheduled"
loader = importlib.machinery.SourceFileLoader("argus_smoke_scheduled", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class ScheduledSmokeTest(unittest.TestCase):
    def test_rootless_probe_requires_fresh_root_owned_success_for_all_domains(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            for domain in module.ROOTLESS_DOMAINS:
                (root / f"{domain}.json").write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "domain": domain,
                            "daemonActive": True,
                            "containerCreation": True,
                            "ok": True,
                            "reason": "passed",
                        }
                    ),
                    encoding="utf-8",
                )
                (root / f"{domain}.json").chmod(0o644)
            original_lstat = module.Path.lstat
            original_time = module.time.time

            def root_lstat(path, *args, **kwargs):
                metadata = original_lstat(path, *args, **kwargs)
                return SimpleNamespace(
                    st_uid=0,
                    st_mode=(
                        stat.S_IFDIR | 0o755
                        if path == root
                        else stat.S_IFREG | 0o644
                    ),
                    st_mtime=100,
                )

            module.Path.lstat = root_lstat
            module.time.time = lambda: 200
            try:
                result = module.rootless_probe_status(root)
            finally:
                module.Path.lstat = original_lstat
                module.time.time = original_time
        self.assertTrue(result["ok"])
        self.assertEqual(3, len(result["domains"]))

    def test_systemd_preflights_are_privileged_but_sockets_stay_private(self) -> None:
        unit = (ROOT / "systemd" / "argus-smoke.service").read_text()
        template = (ROOT / "templates" / "systemd" / "argus-smoke.service").read_text()
        self.assertEqual(unit, template)
        self.assertEqual(3, unit.count("ExecStartPre=-+"))
        self.assertIn("--domain personal-sandbox --probe", unit)
        self.assertIn("--domain work-sandbox --probe", unit)
        self.assertIn("--domain personal-managed --probe", unit)
        self.assertIn(
            "/usr/local/lib/argus/argus-m5-rootless-gid-repair", unit
        )
        self.assertNotIn(
            "+/srv/argus/scripts/argus-m5-rootless-gid-repair", unit
        )
        self.assertIn("User=oreo", unit)
        self.assertNotIn("DOCKER_HOST", unit)

    def test_scheduled_success_requires_zero_warnings_and_runtime_probe(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("warnings == 0", source)
        self.assertIn('rootless_probe["ok"]', source)
        self.assertIn("ROOTLESS_PROBE_MAX_AGE_SECONDS", source)

    def test_failed_checks_keep_fail_and_warn_lines_only_and_are_capped(self) -> None:
        output = "PASS a\nFAIL tracked secrets check ran\nWARN ss unavailable\n" + "FAIL x\n" * 30
        rows = module.failed_checks(output)
        self.assertEqual(["FAIL tracked secrets check ran", "WARN ss unavailable"], rows[:2])
        self.assertEqual(module.HISTORY_FAILED_CHECKS, len(rows))

    def test_history_appends_and_drops_rows_past_thirty_days(self) -> None:
        current = 1_800_000_000.0
        iso = lambda age: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current - age))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smoke-history.jsonl"
            old = {"timestamp": iso(30 * 86400 + 1), "ok": True}
            edge = {"timestamp": iso(30 * 86400), "ok": True}
            path.write_text("\n".join([json.dumps(old), "garbage", json.dumps(edge)]) + "\n")
            module.append_history(path, {"timestamp": iso(0), "ok": False}, current)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([edge["timestamp"], iso(0)], [row["timestamp"] for row in rows])

    def test_scheduled_run_persists_history_with_failed_check_names(self) -> None:
        output = "PASS a\nFAIL tracked file inventory available\nSmoke summary: 1 failure(s), 0 warning(s)\n"
        completed = SimpleNamespace(returncode=1, stdout=output)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {"ARGUS_ROOT": directory}):
            log_dir = Path(directory) / "smoke"
            with mock.patch.object(module.subprocess, "run", return_value=completed), mock.patch.object(
                module, "rootless_probe_status", return_value={"ok": True, "domains": []}
            ), mock.patch.object(module, "root", return_value=Path(directory)), mock.patch("sys.argv", ["x", "--log-dir", str(log_dir)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(1, module.main())
                    self.assertEqual(1, module.main())
            history = [json.loads(line) for line in (log_dir / "smoke-history.jsonl").read_text().splitlines()]
            latest = json.loads((log_dir / "latest.json").read_text())
        self.assertEqual(2, len(history))
        self.assertEqual(["FAIL tracked file inventory available"], history[0]["failedChecks"])
        self.assertFalse(latest["ok"])

    def test_offline_run_does_not_write_history(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="Smoke summary: 0 failure(s), 0 warning(s)\n")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {"ARGUS_ROOT": directory}):
            log_dir = Path(directory) / "smoke"
            with mock.patch.object(module.subprocess, "run", return_value=completed), mock.patch.object(module, "root", return_value=Path(directory)), mock.patch("sys.argv", ["x", "--offline", "--log-dir", str(log_dir)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(0, module.main())
            self.assertFalse((log_dir / "smoke-history.jsonl").exists())

    def test_smoke_timer_is_six_hourly(self) -> None:
        timer = (ROOT / "systemd" / "argus-smoke.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 00/6:00:00", timer)
        self.assertIn("RandomizedDelaySec=15m", timer)


if __name__ == "__main__":
    unittest.main()
