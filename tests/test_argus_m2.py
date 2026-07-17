from __future__ import annotations
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m2 import evaluate_pilot  # noqa: E402


class ArgusM2Test(unittest.TestCase):
    def test_pilot_requires_every_prerequisite(self) -> None:
        complete = evaluate_pilot(subordinate_ids=True, rootless_tool=True, uid_mapping=True, linger=True, cgroup_v2=True, storage=True, namespace_tool=True, rootless_networking=True)
        self.assertTrue(complete["complete"])
        failed = evaluate_pilot(subordinate_ids=True, rootless_tool=False, uid_mapping=True, linger=True, cgroup_v2=True, storage=True, namespace_tool=True, rootless_networking=True)
        self.assertFalse(failed["complete"])
        self.assertEqual(["rootlessTooling"], failed["missing"])
        mapping_failed = evaluate_pilot(subordinate_ids=True, rootless_tool=True, uid_mapping=False, linger=True, cgroup_v2=True, storage=True, namespace_tool=True, rootless_networking=True)
        self.assertEqual(["uidMapping"], mapping_failed["missing"])
