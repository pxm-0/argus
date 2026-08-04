from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_host_guard import HostGuardError, render_host_guard  # noqa: E402


class HostGuardTest(unittest.TestCase):
    def test_personal_sandbox_allows_only_https_before_default_drop(self) -> None:
        rendered = render_host_guard("personal-sandbox", 1002)

        allowance = (
            "meta skuid 1002 tcp dport 443 ct state new,established accept"
        )
        self.assertIn(allowance, rendered)
        self.assertNotIn("udp dport", rendered)
        self.assertNotIn("tcp dport 80", rendered)
        self.assertLess(
            rendered.index(allowance), rendered.index("meta skuid 1002 drop")
        )

    def test_work_sandbox_remains_fully_sealed(self) -> None:
        rendered = render_host_guard("work-sandbox", 1003)

        self.assertNotIn(" dport ", rendered)
        self.assertIn('meta skuid 1003 oifname "lo" accept', rendered)
        self.assertIn("meta skuid 1003 drop", rendered)

    def test_unknown_domain_and_unsafe_uid_are_rejected(self) -> None:
        with self.assertRaises(HostGuardError):
            render_host_guard("unknown", 1002)
        for uid in (0, -1, True):
            with self.subTest(uid=uid):
                with self.assertRaises(HostGuardError):
                    render_host_guard("personal-sandbox", uid)


if __name__ == "__main__":
    unittest.main()
