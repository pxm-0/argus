import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_common  # noqa: E402

DIGEST = "sha256:" + "a" * 64


class ComposeImagePinTests(unittest.TestCase):
    def pin(self, text, service=""):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compose.yml"
            path.write_text(text)
            return argus_common.compose_image_pin(str(path), service)

    def test_single_digest_is_returned(self):
        self.assertEqual(DIGEST, self.pin(f"services:\n  app:\n    image: repo/app@{DIGEST}\n"))

    def test_mutable_tag_has_no_pin(self):
        self.assertEqual("", self.pin("services:\n  app:\n    image: repo/app:latest\n"))

    def test_ambiguous_digests_have_no_pin(self):
        other = "sha256:" + "b" * 64
        self.assertEqual("", self.pin(f"    image: a@{DIGEST}\n    image: b@{other}\n"))

    def test_real_format_bare_digest_with_comment_selects_service(self):
        caddy = "sha256:" + "c" * 64
        text = (
            "services:\n"
            "  nodens:\n"
            f"    image: {DIGEST}  # ghcr.io/x/nodens@{DIGEST} (nodens abc)\n"
            "  caddy:\n"
            f"    image: {caddy}  # caddy:2 (docker.io/library/caddy@{caddy})\n"
            "networks:\n  internal: {}\n"
        )
        self.assertEqual(DIGEST, self.pin(text, "nodens"))
        self.assertEqual(caddy, self.pin(text, "caddy"))
        self.assertEqual("", self.pin(text, "absent"))
        self.assertEqual("", self.pin(text))  # two digests, no service: ambiguous

    def test_placeholder_digest_has_no_pin(self):
        self.assertEqual("", self.pin("services:\n  nodens:\n    image: sha256:PENDING-import\n", "nodens"))

    def test_missing_file_has_no_pin(self):
        self.assertEqual("", argus_common.compose_image_pin("/nonexistent/compose.yml"))
        self.assertEqual("", argus_common.compose_image_pin(""))


if __name__ == "__main__":
    unittest.main()
