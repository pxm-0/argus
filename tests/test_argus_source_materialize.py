from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-workload-source-materialize"
loader = importlib.machinery.SourceFileLoader("argus_source_materialize", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


TEMPLATE = """services:
  web:
    image: nginx@sha256:8b1e78743a03dbb2c95171cc58639fef29abc8816598e27fb910ed2e621e589a
    restart: unless-stopped
    ports:
      - \"127.0.0.1:18080:80\"
    healthcheck:
      test: [\"CMD\", \"wget\", \"-q\", \"--spider\", \"http://127.0.0.1/\"]
"""


class SourceMaterializationTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path]:
        workload = root / "workloads" / "demo"
        workload.mkdir(parents=True)
        target = workload / "source" / "docker-compose.yml"
        (workload / "manifest.json").write_text(
            json.dumps(
                {
                    "runtime": {"compose": {"path": str(target)}},
                    "security": {"trackedByArgusGit": False},
                }
            ),
            encoding="utf-8",
        )
        (workload / "compose.template.yml").write_text(TEMPLATE, encoding="utf-8")
        return workload, target

    def test_preflight_materialize_and_rollback_restore_prior_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _workload, target = self.fixture(root)
            target.parent.mkdir()
            target.write_text("services: {old: {image: old}}\n", encoding="utf-8")
            baseline = module.preflight(root, "demo")
            self.assertTrue(baseline["ok"])
            self.assertTrue(baseline["targetExists"])
            applied = module.apply(root, "demo", owner=None)
            self.assertTrue(applied["backup"])
            self.assertEqual(TEMPLATE, target.read_text(encoding="utf-8"))
            self.assertEqual(0o640, target.stat().st_mode & 0o777)
            journal = root / "runtime" / "argus" / "source-materialization" / "demo" / "latest.json"
            self.assertEqual(0o2710, journal.parent.stat().st_mode & 0o7777)
            self.assertEqual(0o640, journal.stat().st_mode & 0o777)
            self.assertEqual(0o600, Path(applied["backup"]).stat().st_mode & 0o777)
            rolled_back = module.rollback(root, "demo", owner=None)
            self.assertTrue(rolled_back["restoredBackup"])
            self.assertEqual("services: {old: {image: old}}\n", target.read_text(encoding="utf-8"))

    def test_rejects_tracked_source_or_unsafe_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workload, _target = self.fixture(root)
            manifest_path = workload / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["security"]["trackedByArgusGit"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(module.MaterializationError, "untracked workload source"):
                module.preflight(root, "demo")
            manifest["security"]["trackedByArgusGit"] = False
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (workload / "compose.template.yml").write_text(TEMPLATE + "    volumes: [\"/tmp:/tmp\"]\n", encoding="utf-8")
            with self.assertRaisesRegex(module.MaterializationError, "forbidden"):
                module.preflight(root, "demo")

    def test_refuses_a_symlinked_runtime_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _workload, target = self.fixture(root)
            target.parent.mkdir()
            outside = root / "outside.yml"
            outside.write_text("outside\n", encoding="utf-8")
            target.symlink_to(outside)
            with self.assertRaisesRegex(module.MaterializationError, "symlink"):
                module.preflight(root, "demo")

    def test_apply_uses_the_documented_named_acknowledgement_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with (
                patch.object(module, "apply", return_value={"ok": True}) as apply,
                patch.object(module, "_runtime_owner", return_value=None),
                patch.object(module.os, "geteuid", return_value=0),
                patch.dict(module.os.environ, {"ARGUS_ROOT": str(root)}),
                patch.object(
                    sys,
                    "argv",
                    [
                        str(SCRIPT),
                        "--workload",
                        "demo",
                        "--apply",
                        "--acknowledge-source-materialization",
                    ],
                ),
            ):
                self.assertEqual(0, module.main())
            apply.assert_called_once_with(root, "demo", owner=None)


if __name__ == "__main__":
    unittest.main()
