#!/usr/bin/env python3
"""Fail-closed validation of Tailscale Funnel status output."""

from __future__ import annotations

import argparse
import sys


DISABLED_PHRASES = (
    "no funnel",
    "funnel is not",
    "not configured",
    "not running",
    "no serve config",
)
PUBLIC_MARKERS = (
    "available on the internet",
    "funnel on",
    "(public)",
)


def funnel_disabled(status: str) -> bool:
    normalized = status.strip().lower()
    if not normalized or any(marker in normalized for marker in PUBLIC_MARKERS):
        return False
    if any(phrase in normalized for phrase in DISABLED_PHRASES):
        return True
    routes = [
        line.strip().lower()
        for line in status.splitlines()
        if line.strip().lower().startswith(("http://", "https://"))
    ]
    return bool(routes) and all("(tailnet only)" in route for route in routes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-funnel-disabled", action="store_true")
    args = parser.parse_args()
    if not args.validate_funnel_disabled:
        parser.error("--validate-funnel-disabled is required")
    if not funnel_disabled(sys.stdin.read()):
        return 1
    print("TAILSCALE_FUNNEL_OK exposure=tailnet-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
