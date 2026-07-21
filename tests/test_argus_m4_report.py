from __future__ import annotations
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m4_report import QUARANTINE, classification_report  # noqa: E402
class M4ReportTest(unittest.TestCase):
    def test_tracked_registry_is_fully_reconciled(self) -> None:
        import json
        workloads = json.loads((ROOT / "config" / "workloads.json").read_text())["workloads"]
        legacy = json.loads((ROOT / "config" / "argus" / "legacy-classification.json").read_text())
        placements = json.loads((ROOT / "config" / "argus" / "workload-classification.json").read_text())
        report = classification_report(workloads, legacy, placements)
        self.assertTrue(report["complete"])
        self.assertEqual(["hello-nginx"], report["supersededLegacyClassification"])

        access = json.loads((ROOT / "config" / "access.json").read_text())["workloads"]["hello-nginx"]
        workload = next(item for item in workloads if item["id"] == "hello-nginx")
        self.assertEqual("none", access["effective"])
        self.assertEqual("", access["urls"]["local"])
        self.assertEqual([], workload["network"]["observedBindings"])
        self.assertFalse(workload["actions"]["restart"])

    def test_report_fails_closed_for_registry_drift(self) -> None:
        report = classification_report([{"id":"a"},{"id":"b"}], {"workloads":{"a":dict(QUARANTINE)}})
        self.assertFalse(report["complete"])
        self.assertEqual(["b"], report["missingClassification"])

    def test_report_accepts_disjoint_valid_target_placement(self) -> None:
        target = {"realm":"personal","zone":"sandbox","stage":"none","trustDomain":"personal-sandbox","status":"classified","admission":"allowed"}
        report = classification_report([{"id":"legacy"},{"id":"moved"}], {"workloads":{"legacy":dict(QUARANTINE)}}, {"workloads":{"moved":target}})
        self.assertTrue(report["complete"])
        self.assertEqual(1, report["targetCount"])

    def test_report_records_superseded_legacy_state_and_rejects_invalid_target(self) -> None:
        report = classification_report([{"id":"a"}], {"workloads":{"a":dict(QUARANTINE)}}, {"workloads":{"a":{"realm":"personal"}}})
        self.assertFalse(report["complete"])
        self.assertEqual(["a"], report["supersededLegacyClassification"])
        self.assertEqual(["a"], report["invalidTargetClassification"])
        self.assertEqual(1, report["classifiedCount"])
