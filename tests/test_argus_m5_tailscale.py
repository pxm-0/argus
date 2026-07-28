from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_tailscale import funnel_disabled  # noqa: E402


class TailscaleStatusTests(unittest.TestCase):
    def test_tailnet_only_routes_prove_funnel_is_disabled(self) -> None:
        status = """
https://oreochiserver.example.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8090

https://oreochiserver.example.ts.net:8448 (tailnet only)
|-- / proxy http://127.0.0.1:8088
"""
        self.assertTrue(funnel_disabled(status))

    def test_explicit_disabled_phrases_are_accepted(self) -> None:
        for status in (
            "No Funnel",
            "Funnel is not configured",
            "Funnel is not running",
            "No serve config",
        ):
            with self.subTest(status=status):
                self.assertTrue(funnel_disabled(status))

    def test_public_or_ambiguous_status_fails_closed(self) -> None:
        statuses = (
            "",
            "backend error",
            "Available on the internet:\nhttps://example.ts.net",
            "https://example.ts.net (Funnel on)",
            "https://example.ts.net",
            (
                "https://example.ts.net (tailnet only)\n"
                "https://example.ts.net:8448 (public)"
            ),
        )
        for status in statuses:
            with self.subTest(status=status):
                self.assertFalse(funnel_disabled(status))


if __name__ == "__main__":
    unittest.main()
