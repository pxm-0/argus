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
        self.assertEqual(
            ["hastur", "kadath", "nodens-production", "nodens-staging"],
            report["supersededLegacyClassification"],
        )
        self.assertNotIn("hello-nginx", {item["id"] for item in workloads})

    def test_report_fails_closed_for_registry_drift(self) -> None:
        report = classification_report([{"id":"a"},{"id":"b"}], {"workloads":{"a":dict(QUARANTINE)}})
        self.assertFalse(report["complete"])
        self.assertEqual(["b"], report["missingClassification"])

    def test_report_accepts_disjoint_valid_target_placement(self) -> None:
        target = {"realm":"personal","zone":"sandbox","stage":"none","trustDomain":"personal-sandbox","status":"classified","admission":"allowed"}
        report = classification_report([{"id":"legacy"},{"id":"moved"}], {"workloads":{"legacy":dict(QUARANTINE)}}, {"workloads":{"moved":target}})
        self.assertTrue(report["complete"])
        self.assertEqual(1, report["targetCount"])

    def test_report_allows_personal_sandbox_staging_only(self) -> None:
        base = {"realm":"personal","zone":"sandbox","trustDomain":"personal-sandbox","status":"classified","admission":"allowed"}
        staging = classification_report([{"id":"s"}], {"workloads":{}}, {"workloads":{"s":{**base,"stage":"staging"}}})
        self.assertTrue(staging["complete"])
        production = classification_report([{"id":"p"}], {"workloads":{}}, {"workloads":{"p":{**base,"stage":"production"}}})
        self.assertEqual(["p"], production["invalidTargetClassification"])
        work = {**base,"realm":"work","trustDomain":"work-sandbox","stage":"staging"}
        self.assertEqual(["w"], classification_report([{"id":"w"}], {"workloads":{}}, {"workloads":{"w":work}})["invalidTargetClassification"])

    def test_report_records_superseded_legacy_state_and_rejects_invalid_target(self) -> None:
        report = classification_report([{"id":"a"}], {"workloads":{"a":dict(QUARANTINE)}}, {"workloads":{"a":{"realm":"personal"}}})
        self.assertFalse(report["complete"])
        self.assertEqual(["a"], report["supersededLegacyClassification"])
        self.assertEqual(["a"], report["invalidTargetClassification"])
        self.assertEqual(1, report["classifiedCount"])
