from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m1 import deny_direct_legacy_mutation  # noqa: E402
from argus_state import StateError  # noqa: E402


class ArgusM1FreezeTest(unittest.TestCase):
    def test_direct_mutation_guard_fails_closed(self) -> None:
        with self.assertRaisesRegex(StateError, "direct privacy mutation is disabled"):
            deny_direct_legacy_mutation("privacy")

    def test_cli_mutation_surfaces_fail_before_writing(self) -> None:
        cases = [
            ("oreo-privacy-set", ["intake-os", "internal"]),
            ("oreo-access-apply", ["intake-os", "local"]),
            ("oreo-workload-add", ["test-workload", "Test workload"]),
        ]
        watched = [ROOT / "config" / name for name in ("workloads.json", "privacy.json", "access.json")]
        before = {path: path.read_bytes() for path in watched}
        for script, arguments in cases:
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *arguments], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("writer cutover", result.stderr)
        self.assertEqual(before, {path: path.read_bytes() for path in watched})
