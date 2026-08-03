from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-check"
loader = importlib.machinery.SourceFileLoader("argus_check", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class ArgusCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(
            (ROOT / "config" / "core-boundary-policy.json").read_text()
        )
        self.bundle = json.loads(
            (ROOT / "tests" / "fixtures" / "replay" / "core-v1.json").read_text()
        )

    def test_core_boundary_is_closed_and_digest_locked(self) -> None:
        result = module.boundary_audit(ROOT, self.policy)
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual("boundary-ok", result["code"])
        self.assertNotEqual("PENDING", result["sbomDigest"])
        self.assertNotEqual("PENDING", result["endpointDigest"])

    def audit_fixture(self, source: str, *, declared_network: bool = False) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "probe.py").write_text(source)
            policy = copy.deepcopy(self.policy)
            policy["corePaths"] = ["scripts"]
            policy["dynamicLoadPolicy"]["allowedPaths"] = []
            policy["networkPolicy"]["declaredEntrypoints"] = (
                [{"path": "scripts/probe.py", "authority": "test"}]
                if declared_network
                else []
            )
            baseline = module.boundary_audit(root, policy)
            policy["dependencyPolicy"]["expectedSbomDigest"] = baseline["sbomDigest"]
            policy["networkPolicy"]["expectedEndpointDigest"] = baseline["endpointDigest"]
            return module.boundary_audit(root, policy)

    def test_model_sdk_import_fails_the_core_boundary(self) -> None:
        result = self.audit_fixture("import openai\n")
        self.assertEqual("core-boundary-violation", result["code"])
        self.assertTrue(
            any(item["reason"] == "model-sdk-import:openai" for item in result["violations"])
        )

    def test_undeclared_network_importer_fails_the_core_boundary(self) -> None:
        result = self.audit_fixture("import socket\n")
        self.assertTrue(
            any(item["reason"] == "undeclared-network-importer" for item in result["violations"])
        )

    def test_undeclared_dynamic_loader_fails_the_core_boundary(self) -> None:
        result = self.audit_fixture("import importlib\n")
        self.assertTrue(
            any(item["reason"] == "undeclared-dynamic-load" for item in result["violations"])
        )

    def test_future_companion_cannot_gain_core_authority(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["futureCompanionPolicy"]["mutationCapability"] = True
        result = module.boundary_audit(ROOT, policy)
        self.assertTrue(
            any(item["reason"] == "companion-boundary-weakened" for item in result["violations"])
        )

    def test_replay_is_byte_identical_one_hundred_times(self) -> None:
        outputs = {
            module.canonical_bytes(module.replay_output(self.bundle))
            for _ in range(100)
        }
        self.assertEqual(1, len(outputs))
        result = module.replay_bundle(self.bundle, {"canonical-json-v1"})
        self.assertEqual("replay-ok", result["code"])
        self.assertTrue(result["ok"])

    def test_shuffled_source_pages_preserve_output_digest(self) -> None:
        shuffled = copy.deepcopy(self.bundle)
        shuffled["inputs"]["sourcePages"].reverse()
        original = module.replay_output(self.bundle)
        changed = module.replay_output(shuffled)
        self.assertEqual(module.canonical_bytes(original), module.canonical_bytes(changed))
        result = module.replay_bundle(shuffled, {"canonical-json-v1"})
        self.assertTrue(result["ok"], result)

    def test_unicode_normalization_is_deterministic(self) -> None:
        self.assertEqual(
            module.canonical_bytes({"name": "café"}),
            module.canonical_bytes({"name": "cafe\u0301"}),
        )

    def test_incomplete_bundle_has_stable_result(self) -> None:
        result = module.replay_bundle({"schemaVersion": 1}, {"canonical-json-v1"})
        self.assertFalse(result["ok"])
        self.assertEqual("replay-bundle-incomplete", result["code"])

    def test_unsupported_transform_is_not_called_nondeterminism(self) -> None:
        bundle = copy.deepcopy(self.bundle)
        bundle["transformVersion"] = "retired-transform-v0"
        result = module.replay_bundle(bundle, {"canonical-json-v1"})
        self.assertFalse(result["ok"])
        self.assertEqual("replay-version-unsupported", result["code"])

    def test_changed_output_has_expected_and_actual_digests(self) -> None:
        bundle = copy.deepcopy(self.bundle)
        bundle["inputs"]["canonical"]["observedState"] = "stopped"
        result = module.replay_bundle(bundle, {"canonical-json-v1"})
        self.assertFalse(result["ok"])
        self.assertEqual("replay-mismatch", result["code"])
        self.assertIn("expected", result["mismatches"]["canonicalOutputDigest"])
        self.assertIn("actual", result["mismatches"]["canonicalOutputDigest"])

    def test_root_contract_fails_with_exact_recovery(self) -> None:
        ok, message = module.root_contract(euid=0)
        self.assertFalse(ok)
        self.assertIn("non-root", message)
        self.assertIn("./scripts/argus-check", message)


if __name__ == "__main__":
    unittest.main()
