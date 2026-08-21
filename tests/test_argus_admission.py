from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_admission import (  # noqa: E402
    CANONICAL_RECORD_ORDER,
    DECISION_CODES,
    AdmissionRequest,
    canonical_json,
    canonical_records,
    canonical_revision,
    current_request,
    evaluate,
)
from argus_cloudflare_activation import (  # noqa: E402
    activation_plan,
    lower_effective,
    set_effective_cloudflare_protected,
)
from argus_state import Classification  # noqa: E402


class AdmissionDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / "config", self.root / "config")
        shutil.copytree(ROOT / "workloads", self.root / "workloads")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def load(self, relative: str) -> dict[str, object]:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def save(self, relative: str, value: object) -> None:
        (self.root / relative).write_text(
            json.dumps(value, indent=2) + "\n",
            encoding="utf-8",
        )

    def decision(self, operation_type: str = "workload.restart"):
        return evaluate(
            self.root,
            current_request(self.root, "hello-nginx", operation_type),
        )

    def test_allowed_decision_and_canonical_binding_are_exact(self) -> None:
        decision = self.decision()
        self.assertTrue(decision.allowed)
        self.assertEqual("allowed", decision.decision_code)
        self.assertEqual("1", decision.policy_version)
        self.assertEqual(("admission-allowed",), decision.reasons)
        self.assertEqual([], decision.as_dict()["requiredEvidence"])

        records = canonical_records(self.root, "hello-nginx")
        ordered = [records[name] for name in CANONICAL_RECORD_ORDER]
        expected = hashlib.sha256(canonical_json(ordered).encode()).hexdigest()
        self.assertEqual(expected, canonical_revision(self.root, "hello-nginx"))

    def test_unknown_manifest_and_capability_fail_closed(self) -> None:
        unknown = evaluate(
            self.root,
            current_request(self.root, "not-registered", "workload.restart"),
        )
        self.assertEqual("unknown-workload", unknown.decision_code)

        manifest = self.load("workloads/hello-nginx/manifest.json")
        manifest.pop("name")
        self.save("workloads/hello-nginx/manifest.json", manifest)
        invalid = self.decision()
        self.assertEqual("manifest-invalid", invalid.decision_code)

        (self.root / "workloads" / "hello-nginx" / "manifest.json").write_text(
            "{",
            encoding="utf-8",
        )
        malformed = evaluate(
            self.root,
            AdmissionRequest(
                workload_id="hello-nginx",
                operation_type="workload.restart",
                expected_revision="",
                policy_version="1",
                target=Classification(
                    "personal",
                    "sandbox",
                    "none",
                    "personal-sandbox",
                    "workload",
                ),
            ),
        )
        self.assertEqual("manifest-invalid", malformed.decision_code)

        capable = evaluate(
            ROOT,
            current_request(ROOT, "hello-nginx", "workload.deploy"),
        )
        self.assertEqual("operation-not-capable", capable.decision_code)

    def test_classification_admission_legacy_and_target_matrix(self) -> None:
        classification = self.load("config/argus/workload-classification.json")
        entry = classification["workloads"]["hello-nginx"]
        entry["status"] = "pending"
        self.save("config/argus/workload-classification.json", classification)
        self.assertEqual("classification-incomplete", self.decision().decision_code)

        entry["status"] = "classified"
        entry["admission"] = "denied"
        self.save("config/argus/workload-classification.json", classification)
        self.assertEqual("admission-denied", self.decision().decision_code)

        entry.update(
            {
                "realm": "unclassified",
                "zone": "legacy",
                "stage": "none",
                "trustDomain": "legacy-rootful",
                "admission": "allowed",
            }
        )
        self.save("config/argus/workload-classification.json", classification)
        self.assertEqual("legacy-domain-denied", self.decision().decision_code)

        request = current_request(ROOT, "hello-nginx", "workload.restart")
        mismatch = replace(
            request,
            target=Classification(
                "personal",
                "managed",
                "production",
                "personal-managed",
                "workload",
            ),
        )
        self.assertEqual("target-mismatch", evaluate(ROOT, mismatch).decision_code)

    def test_stale_policy_and_revision_are_distinct(self) -> None:
        request = current_request(self.root, "hello-nginx", "workload.restart")
        stale_policy = replace(request, policy_version="0")
        self.assertEqual(
            "policy-version-stale",
            evaluate(self.root, stale_policy).decision_code,
        )

        routes = self.load("config/routes.json")
        routes["workloadRoutes"]["hello-nginx"]["tailnet"]["mode"] = "changed"
        self.save("config/routes.json", routes)
        self.assertEqual("revision-stale", evaluate(self.root, request).decision_code)

    def test_missing_and_unavailable_dependencies_are_distinct(self) -> None:
        access = self.load("config/access.json")
        del access["workloads"]["hello-nginx"]
        self.save("config/access.json", access)
        missing = self.decision()
        self.assertEqual("evidence-missing", missing.decision_code)
        self.assertIn("access", missing.required_evidence)

        request = current_request(ROOT, "hello-nginx", "workload.restart")
        (self.root / "config" / "policy.json").write_text("{", encoding="utf-8")
        unavailable = evaluate(self.root, request)
        self.assertEqual("dependency-unavailable", unavailable.decision_code)

    def test_read_only_evidence_can_remain_available_when_admission_is_denied(self) -> None:
        classification = self.load("config/argus/workload-classification.json")
        classification["workloads"]["hello-nginx"]["admission"] = "denied"
        self.save("config/argus/workload-classification.json", classification)
        logs = self.decision("logs.preview")
        self.assertTrue(logs.allowed)
        self.assertEqual("allowed", logs.decision_code)

    def test_decision_code_set_is_closed(self) -> None:
        self.assertEqual(
            {
                "allowed",
                "unknown-workload",
                "manifest-invalid",
                "operation-not-capable",
                "classification-incomplete",
                "admission-denied",
                "legacy-domain-denied",
                "target-mismatch",
                "revision-stale",
                "policy-version-stale",
                "evidence-missing",
                "evidence-stale",
                "dependency-unavailable",
            },
            DECISION_CODES,
        )

    def test_deferred_cloudflare_paths_share_the_default_deny_admission(self) -> None:
        plan = activation_plan("hello-nginx")
        self.assertFalse(plan["ok"])
        self.assertEqual(
            "operation-not-capable",
            plan["admission"]["decisionCode"],
        )
        self.assertIn("operation-not-capable", plan["blockers"])
        with self.assertRaisesRegex(PermissionError, "operation-not-capable"):
            set_effective_cloudflare_protected("hello-nginx")
        with self.assertRaisesRegex(PermissionError, "operation-not-capable"):
            lower_effective("hello-nginx")


if __name__ == "__main__":
    unittest.main()
