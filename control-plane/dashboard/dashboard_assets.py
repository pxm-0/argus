"""Deterministically generate the local Argus dashboard identity family."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import struct
import xml.etree.ElementTree as ElementTree
import zlib


ASSET_ROOT = Path(__file__).resolve().parent / "assets"
MASTER = ASSET_ROOT / "argus-mark.svg"

SVG = ElementTree.fromstring(MASTER.read_text())
SVG_NAMESPACE = {"svg": "http://www.w3.org/2000/svg"}


def _rgba(value: str) -> tuple[int, int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5)) + (255,)


INK = _rgba(SVG.find("svg:rect", SVG_NAMESPACE).attrib["fill"])
GOLD = _rgba(SVG.find("svg:path", SVG_NAMESPACE).attrib["stroke"])
BLUE = _rgba(SVG.findall("svg:circle", SVG_NAMESPACE)[0].attrib["fill"])
EYE_HORIZONTAL = float(SVG.attrib["data-eye-horizontal"])
EYE_VERTICAL = float(SVG.attrib["data-eye-vertical"])
INNER_SCALE_X = float(SVG.attrib["data-inner-scale-x"])
INNER_SCALE_Y = float(SVG.attrib["data-inner-scale-y"])
PUPIL_INNER = float(SVG.attrib["data-pupil-inner"])
PUPIL_OUTER = float(SVG.attrib["data-pupil-outer"])
MASKABLE_SCALE = float(SVG.attrib["data-maskable-scale"])


def _inside_eye(x: float, y: float) -> bool:
    """Return whether a normalized point is inside the compact eye silhouette."""
    horizontal = abs(x - 0.5) / EYE_HORIZONTAL
    vertical = abs(y - 0.5) / EYE_VERTICAL
    return horizontal + vertical <= 1.0


def _pixel(size: int, px: int, py: int, *, maskable: bool) -> tuple[int, int, int, int]:
    # Four deterministic samples keep the 16px fallback legible without an image library.
    samples = []
    safe_scale = MASKABLE_SCALE if maskable else 1.0
    for offset_x, offset_y in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
        x = ((px + offset_x) / size - 0.5) / safe_scale + 0.5
        y = ((py + offset_y) / size - 0.5) / safe_scale + 0.5
        distance = ((x - 0.5) ** 2 + (y - 0.5) ** 2) ** 0.5
        if distance <= PUPIL_INNER:
            samples.append(INK)
        elif distance <= PUPIL_OUTER:
            samples.append(BLUE)
        elif _inside_eye(x, y) and not _inside_eye(
            0.5 + (x - 0.5) / INNER_SCALE_X,
            0.5 + (y - 0.5) / INNER_SCALE_Y,
        ):
            samples.append(GOLD)
        else:
            samples.append(INK)
    return tuple(sum(sample[index] for sample in samples) // len(samples) for index in range(4))  # type: ignore[return-value]


@lru_cache(maxsize=None)
def png_bytes(size: int, *, maskable: bool = False) -> bytes:
    """Render the mark as a deterministic RGBA PNG using only the standard library."""
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(_pixel(size, x, y, maskable=maskable))
    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    return signature + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress(bytes(raw), level=9)
    ) + chunk(b"IEND", b"")


def manifest_text() -> str:
    manifest = {
        "name": "Argus private control plane",
        "short_name": "Argus",
        "start_url": "./",
        "display": "standalone",
        "background_color": "#070a12",
        "theme_color": "#0d1324",
        "icons": [
            {"src": "./icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "./icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "./icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def write_assets(public: Path) -> None:
    """Write installed browser assets from the reviewed source mark."""
    public.mkdir(parents=True, exist_ok=True)
    (public / "favicon.svg").write_bytes(MASTER.read_bytes())
    for name, size, maskable in (
        ("favicon-16.png", 16, False),
        ("favicon-32.png", 32, False),
        ("apple-touch-icon.png", 180, False),
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ):
        (public / name).write_bytes(png_bytes(size, maskable=maskable))
    (public / "manifest.webmanifest").write_text(manifest_text())
