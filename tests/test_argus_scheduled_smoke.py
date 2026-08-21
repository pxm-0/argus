from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "argus-smoke-scheduled"
loader = importlib.machinery.SourceFileLoader("argus_smoke_scheduled", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class ScheduledSmokeTest(unittest.TestCase):
    def test_rootless_probe_requires_fresh_root_owned_success_for_both_domains(
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
        self.assertEqual(2, len(result["domains"]))

    def test_systemd_preflights_are_privileged_but_sockets_stay_private(self) -> None:
        unit = (ROOT / "systemd" / "argus-smoke.service").read_text()
        template = (ROOT / "templates" / "systemd" / "argus-smoke.service").read_text()
        self.assertEqual(unit, template)
        self.assertEqual(2, unit.count("ExecStartPre=-+"))
        self.assertIn("--domain personal-sandbox --probe", unit)
        self.assertIn("--domain work-sandbox --probe", unit)
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


if __name__ == "__main__":
    unittest.main()
