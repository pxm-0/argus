from __future__ import annotations

import json
import socket
import struct
from typing import Any

from argus_operations import canonical_json


MAX_FRAME_BYTES = 65_536


def encode_frame(payload: dict[str, Any]) -> bytes:
    encoded = canonical_json(payload).encode("utf-8")
    if len(encoded) > MAX_FRAME_BYTES:
        raise ValueError("typed message exceeds 64 KiB")
    return struct.pack(">I", len(encoded)) + encoded


def receive_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ValueError("truncated typed message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def receive_frame(connection: socket.socket) -> dict[str, Any]:
    header = receive_exact(connection, 4)
    length = struct.unpack(">I", header)[0]
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise ValueError("invalid typed message length")
    payload = json.loads(receive_exact(connection, length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("typed message must be an object")
    return payload


def send_frame(connection: socket.socket, payload: dict[str, Any]) -> None:
    connection.sendall(encode_frame(payload))


def request(
    socket_path: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout_seconds)
        connection.connect(socket_path)
        send_frame(connection, payload)
        return receive_frame(connection)
