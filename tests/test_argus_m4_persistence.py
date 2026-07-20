from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m4_persistence import REQUIRED, evaluate_persistence  # noqa: E402


class PersistenceTest(unittest.TestCase):
    def test_accepts_only_complete_positive_evidence(self) -> None:
        result = evaluate_persistence({key: True for key in REQUIRED})
        self.assertTrue(result["verified"])
        self.assertEqual([], result["failedChecks"])

    def test_reports_every_failed_gate_without_private_output(self) -> None:
        facts = {key: True for key in REQUIRED}
        facts["cgroupDriverCorrect"] = False
        facts["hostRebootedAfterCutover"] = False
        result = evaluate_persistence(facts)
        self.assertFalse(result["verified"])
        self.assertEqual(["cgroupDriverCorrect", "hostRebootedAfterCutover"], result["failedChecks"])
        self.assertNotIn("socket", json_text := __import__("json").dumps(result).lower())
        self.assertNotIn("path", json_text)

    def test_rejects_missing_or_non_boolean_facts(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_persistence({})
        facts = {key: True for key in REQUIRED}
        facts["daemonActive"] = "yes"
        with self.assertRaises(ValueError):
            evaluate_persistence(facts)
