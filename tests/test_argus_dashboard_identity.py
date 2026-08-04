from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "control-plane" / "dashboard"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DashboardIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assets = load_module("argus_dashboard_assets", DASHBOARD / "dashboard_assets.py")

    def test_asset_family_is_deterministic_and_manifest_is_local(self) -> None:
        self.assertEqual(self.assets.png_bytes(32), self.assets.png_bytes(32))
        self.assertEqual((13, 19, 36, 255), self.assets.INK)
        self.assertEqual((245, 200, 91, 255), self.assets.GOLD)
        self.assertEqual((104, 167, 255, 255), self.assets.BLUE)
        manifest = json.loads(self.assets.manifest_text())
        self.assertEqual("standalone", manifest["display"])
        self.assertEqual({"any", "maskable"}, {icon["purpose"] for icon in manifest["icons"]})
        self.assertTrue(all(icon["src"].startswith("./") for icon in manifest["icons"]))
        self.assertNotIn("http", self.assets.manifest_text())
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assets.write_assets(Path(first))
            self.assets.write_assets(Path(second))
            first_assets = {path.name: path.read_bytes() for path in Path(first).iterdir()}
            second_assets = {path.name: path.read_bytes() for path in Path(second).iterdir()}
            self.assertEqual(first_assets, second_assets)

    def test_16px_fallback_remains_legible_in_monochrome_light_and_dark_contexts(self) -> None:
        payload = self.assets.png_bytes(16)
        self.assertEqual(b"\x89PNG\r\n\x1a\n", payload[:8])
        width, height = struct.unpack(">II", payload[16:24])
        self.assertEqual((16, 16), (width, height))
        offset = 8
        compressed = bytearray()
        while offset < len(payload):
            length = struct.unpack(">I", payload[offset : offset + 4])[0]
            kind = payload[offset + 4 : offset + 8]
            if kind == b"IDAT":
                compressed.extend(payload[offset + 8 : offset + 8 + length])
            offset += length + 12
        rows = zlib.decompress(bytes(compressed))
        pixels = []
        for row_start in range(0, len(rows), 65):
            self.assertEqual(0, rows[row_start])
            pixels.extend(
                tuple(rows[index : index + 4])
                for index in range(row_start + 1, row_start + 65, 4)
            )
        luminance = {round(0.2126 * red + 0.7152 * green + 0.0722 * blue) for red, green, blue, _alpha in pixels}
        self.assertGreaterEqual(len(luminance), 3)
        self.assertGreater(max(luminance) - min(luminance), 100)
        self.assertTrue(all(pixel[3] == 255 for pixel in pixels), "opaque backing must survive light and dark browser chrome")

    def test_generated_page_installs_identity_and_fails_closed_without_javascript(self) -> None:
        generator = load_module("argus_dashboard_identity_generator", DASHBOARD / "generate_dashboard.py")
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            with patch.object(generator, "PUBLIC", public):
                self.assertEqual(0, generator.main())
            html = (public / "index.html").read_text()
            for name in (
                "favicon.svg",
                "favicon-16.png",
                "favicon-32.png",
                "apple-touch-icon.png",
                "icon-192.png",
                "icon-512.png",
                "icon-maskable-512.png",
                "manifest.webmanifest",
            ):
                self.assertTrue((public / name).is_file(), name)
            self.assertIn('<link rel="manifest" href="./manifest.webmanifest">', html)
            self.assertNotIn('href="data:,"', html)
            self.assertIn('<html lang="en" class="no-js">', html)
            self.assertIn('document.documentElement.classList.remove("no-js")', html)
            self.assertIn(".no-js .app-shell { display:none; }", (public / "style.css").read_text())
            no_script = html[html.index("<noscript>") : html.index("</noscript>")]
            self.assertIn("JavaScript required", no_script)
            self.assertNotIn("admin-token", no_script)
            self.assertNotIn("data-operation", no_script)


if __name__ == "__main__":
    unittest.main()
