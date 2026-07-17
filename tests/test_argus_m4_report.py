from __future__ import annotations
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m4_report import QUARANTINE, classification_report  # noqa: E402
class M4ReportTest(unittest.TestCase):
    def test_report_fails_closed_for_registry_drift(self) -> None:
        report = classification_report([{"id":"a"},{"id":"b"}], {"workloads":{"a":dict(QUARANTINE)}})
        self.assertFalse(report["complete"])
        self.assertEqual(["b"], report["missingClassification"])
