from __future__ import annotations
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m2_bootstrap import BootstrapError, pilot_contract  # noqa: E402
class M2BootstrapTest(unittest.TestCase):
    def test_contract_is_fixed_and_has_no_exposure_path(self) -> None:
        contract = pilot_contract(domain="personal-sandbox-pilot", user="argus-pilot")
        self.assertTrue(contract["contractDigest"].startswith("sha256:"))
        self.assertIn("no-published-ports", contract["prohibitions"])
        with self.assertRaises(BootstrapError):
            pilot_contract(domain="work-managed", user="anything")
