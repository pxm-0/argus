from __future__ import annotations
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
from argus_m4_plan import REQUIRED, migration_plan  # noqa: E402
class M4PlanTest(unittest.TestCase):
 def test_plan_refuses_missing_gates_then_accepts_complete_evidence(self):
  self.assertFalse(migration_plan("pilot",{})["approved"])
  e={key:True for key in REQUIRED}
  e["physicalMappings"]={key:"sha256:x" for key in ("sourceRuntimeRef","targetRuntimeRef","sourceVolumeRef","targetVolumeRef")}
  self.assertTrue(migration_plan("pilot",e)["approved"])
