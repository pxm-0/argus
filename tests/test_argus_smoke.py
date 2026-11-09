from __future__ import annotations

import contextlib
import io
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "smoke-test"
loader = importlib.machinery.SourceFileLoader("argus_smoke", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class LatestBackupArtifactSmokeTests(unittest.TestCase):
    def write_workload(self, root: Path, *, backup_allowed: bool) -> None:
        (root / "config").mkdir()
        (root / "config" / "workloads.json").write_text(
            json.dumps({"workloads": [{"id": "candidate"}]}),
            encoding="utf-8",
        )
        manifest = root / "workloads" / "candidate" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "operations": {"backupAllowed": backup_allowed},
                    "backup": {
                        "backupAllowed": backup_allowed,
                        "destination": str(root / "backups" / "candidate"),
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_no_active_backup_enabled_is_a_passing_no_op(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.write_workload(root, backup_allowed=False)
            smoke = module.Smoke()
            with contextlib.redirect_stdout(io.StringIO()):
                module.check_latest_backup_artifact(root, smoke, offline=False)
        self.assertEqual([], smoke.failures)

    def test_enabled_backup_still_requires_an_artifact(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.write_workload(root, backup_allowed=True)
            smoke = module.Smoke()
            with contextlib.redirect_stdout(io.StringIO()):
                module.check_latest_backup_artifact(root, smoke, offline=False)
        self.assertEqual(["candidate latest approved backup artifact exists"], smoke.failures)


if __name__ == "__main__":
    unittest.main()
