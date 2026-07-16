from __future__ import annotations
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m2 import evaluate_pilot  # noqa: E402


class ArgusM2Test(unittest.TestCase):
    def test_pilot_requires_every_prerequisite(self) -> None:
        complete = evaluate_pilot(subordinate_ids=True, rootless_tool=True, linger=True, cgroup_v2=True, storage=True, namespace_tool=True)
        self.assertTrue(complete["complete"])
        failed = evaluate_pilot(subordinate_ids=True, rootless_tool=False, linger=True, cgroup_v2=True, storage=True, namespace_tool=True)
        self.assertFalse(failed["complete"])
        self.assertEqual(["rootlessTooling"], failed["missing"])
