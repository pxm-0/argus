from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_common import expected_server_host, on_expected_server_host  # noqa: E402


HOST_GATED_ACCEPTANCE = (
    "argus-collector-protocol-acceptance",
    "argus-d2a-rootful-docker-acceptance",
    "argus-d2b-rootless-docker-acceptance",
    "argus-d3-systemd-schedule-acceptance",
    "argus-d4-optional-evidence-acceptance",
    "argus-d5-reconciliation-acceptance",
    "argus-d6-dashboard-acceptance",
    "argus-observation-repository-acceptance",
)


class ExpectedServerHostTests(unittest.TestCase):
    def test_defaults_to_oreochiserver(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("oreochiserver", expected_server_host())
        with mock.patch.dict(os.environ, {"ARGUS_EXPECTED_HOST": ""}):
            self.assertEqual("oreochiserver", expected_server_host())

    def test_explicit_override_names_the_simulator(self) -> None:
        with mock.patch.dict(os.environ, {"ARGUS_EXPECTED_HOST": "oreochiserver-sim"}):
            self.assertEqual("oreochiserver-sim", expected_server_host())

    def test_compares_short_hostname(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("platform.node", return_value="oreochiserver.tail.ts.net"):
                self.assertTrue(on_expected_server_host())
            with mock.patch("platform.node", return_value="oreochiserver-sim"):
                self.assertFalse(on_expected_server_host())
        with mock.patch.dict(os.environ, {"ARGUS_EXPECTED_HOST": "oreochiserver-sim"}):
            with mock.patch("platform.node", return_value="oreochiserver-sim.orb.local"):
                self.assertTrue(on_expected_server_host())
            with mock.patch("platform.node", return_value="oreochiserver"):
                self.assertFalse(on_expected_server_host())

    def test_acceptance_scripts_use_the_shared_host_gate(self) -> None:
        for name in HOST_GATED_ACCEPTANCE:
            source = (ROOT / "scripts" / name).read_text()
            with self.subTest(script=name):
                self.assertNotIn("platform.node()", source)
                self.assertIn("on_expected_server_host()", source)


if __name__ == "__main__":
    unittest.main()
