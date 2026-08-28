from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_canonical import (  # noqa: E402
    canonical_policy_version,
    canonical_records,
    canonical_revision,
)


class CanonicalBindingTests(unittest.TestCase):
    def test_revision_contains_every_required_workload_record(self) -> None:
        records = canonical_records(ROOT, "hastur")
        self.assertEqual(
            {
                "workload",
                "privacy",
                "access",
                "classification",
                "manifest",
                "policy",
                "route",
            },
            set(records),
        )
        self.assertIsNotNone(records["workload"])
        self.assertIsNotNone(records["classification"])
        self.assertEqual(64, len(canonical_revision(ROOT, "hastur")))
        self.assertEqual("1", canonical_policy_version(ROOT, "hastur"))

    def test_policy_and_route_drift_change_the_expected_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            shutil.copytree(ROOT / "config", clone / "config")
            shutil.copytree(
                ROOT / "workloads" / "hastur",
                clone / "workloads" / "hastur",
            )
            revision = canonical_revision(clone, "hastur")
            policy_version = canonical_policy_version(clone, "hastur")

            routes_path = clone / "config" / "routes.json"
            routes = json.loads(routes_path.read_text())
            routes["workloadRoutes"]["hastur"]["approved"] = True
            routes_path.write_text(json.dumps(routes))
            self.assertNotEqual(
                revision,
                canonical_revision(clone, "hastur"),
            )
            self.assertEqual(
                policy_version,
                canonical_policy_version(clone, "hastur"),
            )

            manifest_path = (
                clone / "workloads" / "hastur" / "manifest.json"
            )
            manifest = json.loads(manifest_path.read_text())
            manifest["operations"]["restartAllowed"] = True
            manifest_path.write_text(json.dumps(manifest))
            self.assertEqual(
                policy_version,
                canonical_policy_version(clone, "hastur"),
            )
            self.assertNotEqual(
                revision,
                canonical_revision(clone, "hastur"),
            )

            policy_path = clone / "config" / "policy.json"
            policy = json.loads(policy_path.read_text())
            policy["version"] = 2
            policy_path.write_text(json.dumps(policy))
            self.assertEqual("2", canonical_policy_version(clone, "hastur"))


if __name__ == "__main__":
    unittest.main()
