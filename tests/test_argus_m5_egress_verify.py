from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    loader = importlib.machinery.SourceFileLoader(
        "argus_m5_egress_verify_test", str(ROOT / "scripts" / "argus-m5-egress-verify")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RetiredWorkloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = load_verifier()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / "config" / "argus").mkdir(parents=True)
        (root / "config" / "argus" / "retired-workloads.json").write_text(
            json.dumps({"schemaVersion": 1, "workloads": ["nodens"]})
        )
        cutover = types.SimpleNamespace(
            SPECS={
                "kadath": {"domain": "personal-sandbox"},
                "nodens": {"domain": "personal-sandbox"},
            },
            validated_egress=lambda workload, spec: None,
            sandbox_bridge=lambda workload: None,
            egress_policy_drift=lambda spec: [],
        )
        self.probed: list[dict] = []
        for name, value in {
            "ROOT": root,
            "cutover_module": lambda: cutover,
            "probe_container": lambda module, spec: self.probed.append(spec) or "probe",
            "expectations_for": lambda module, spec, policy, container: [],
            "scored": lambda checks: [],
        }.items():
            patcher = mock.patch.object(self.verifier, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(self.verifier.os, "geteuid", return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_domain_run_skips_retired_workloads(self) -> None:
        # The cutover SPECS still hold retired nodens; probing it failed the whole domain.
        result = self.verifier.verify("personal-sandbox")
        self.assertEqual(["kadath"], [item["workloadId"] for item in result["workloads"]])
        self.assertEqual(1, len(self.probed))

    def test_naming_a_retired_workload_finds_nothing(self) -> None:
        with self.assertRaises(self.verifier.VerifyError):
            self.verifier.verify("personal-sandbox", ["nodens"])


if __name__ == "__main__":
    unittest.main()
