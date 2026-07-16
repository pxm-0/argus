from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_portfolio import PortfolioError, build_artifact, validate_mirror, validate_promotion, validate_snapshot  # noqa: E402


def snapshot() -> dict:
    return {"version": 1, "projects": [{"synthetic": True, "title": "Example Atlas", "summary": "A synthetic public project summary.", "tags": ["example", "design"], "status": "Concept"}]}


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for provenance tests")
class ArgusPortfolioTest(unittest.TestCase):
    def keypair(self, root: Path) -> tuple[Path, Path]:
        private, public = root / "signing.key", root / "signing.pub"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, capture_output=True)
        return private, public

    def test_build_mirror_and_promotion_are_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, public = self.keypair(root)
            artifact, receipt = root / "artifact", root / "mirror.json"
            proof = build_artifact(snapshot(), artifact, private, public)
            self.assertTrue(proof["verified"])
            validate_mirror(artifact, public, receipt)
            self.assertEqual(proof, validate_promotion(artifact, public, receipt))
            (artifact / "index.html").write_text("changed")
            with self.assertRaises(PortfolioError):
                validate_promotion(artifact, public, receipt)

    def test_snapshot_and_artifact_fail_closed_for_private_content(self) -> None:
        unsafe = snapshot()
        unsafe["projects"][0]["summary"] = "Reach it at https://localhost/private"
        with self.assertRaises(PortfolioError):
            validate_snapshot(unsafe)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, public = self.keypair(root)
            artifact = root / "artifact"
            build_artifact(snapshot(), artifact, private, public)
            (artifact / "unexpected.js").write_text("fetch('/api')")
            with self.assertRaises(PortfolioError):
                validate_mirror(artifact, public, root / "mirror.json")

    def test_nested_or_unexpected_schema_fields_are_rejected(self) -> None:
        value = snapshot()
        value["projects"][0]["nested"] = {"secret": "no"}
        with self.assertRaises(PortfolioError):
            validate_snapshot(value)
        value = snapshot()
        value["projects"][0]["synthetic"] = False
        with self.assertRaises(PortfolioError):
            validate_snapshot(value)
