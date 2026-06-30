#!/usr/bin/env python3
"""Shared helpers for Oreo Cloud CLI scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def root() -> Path:
    override = os.environ.get("OREO_CLOUD_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def load_json(name: str) -> dict[str, Any]:
    path = root() / "config" / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"missing {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from None


def workloads() -> list[dict[str, Any]]:
    data = load_json("workloads.json")
    items = data.get("workloads", [])
    if not isinstance(items, list):
        raise SystemExit("config/workloads.json must contain a workloads list")
    return items


def by_id() -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in workloads()}


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    fmt = "  ".join("{:<" + str(width) + "}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * width for width in widths]))
    for row in rows:
        print(fmt.format(*row))


def http_status(url: str, timeout: float = 3.0) -> tuple[str, str]:
    if not url:
        return "skip", "no-url"
    request = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(NoRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            return str(response.status), "ok"
    except urllib.error.HTTPError as exc:
        return str(exc.code), "http-error"
    except Exception as exc:  # noqa: BLE001 - CLI should report concise failure.
        return "fail", exc.__class__.__name__


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None
