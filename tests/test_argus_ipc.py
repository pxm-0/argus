from __future__ import annotations

import socket
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_ipc import MAX_FRAME_BYTES, encode_frame, receive_frame  # noqa: E402


class IpcTests(unittest.TestCase):
    def test_canonical_length_prefixed_round_trip(self) -> None:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            left.sendall(encode_frame({"z": 1, "a": "value"}))
            self.assertEqual({"a": "value", "z": 1}, receive_frame(right))
        finally:
            left.close()
            right.close()

    def test_oversized_non_object_and_truncated_frames_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds 64 KiB"):
            encode_frame({"value": "x" * MAX_FRAME_BYTES})
        cases = [
            struct.pack(">I", MAX_FRAME_BYTES + 1),
            struct.pack(">I", 2) + b"[]",
            struct.pack(">I", 5) + b"{}",
        ]
        for encoded in cases:
            with self.subTest(encoded=encoded[:4]):
                left, right = socket.socketpair(
                    socket.AF_UNIX,
                    socket.SOCK_STREAM,
                )
                try:
                    left.sendall(encoded)
                    left.shutdown(socket.SHUT_WR)
                    with self.assertRaises(ValueError):
                        receive_frame(right)
                finally:
                    left.close()
                    right.close()


if __name__ == "__main__":
    unittest.main()
