#!/usr/bin/env python3
"""Minimal deterministic Argus command dispatcher."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse


TAILSCALE_HTTPS_URL = re.compile(
    r"^https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.ts\.net(?::[1-9][0-9]{0,4})?/?$"
)
MAX_ROUTE_BYTES = 65536


class CliInvocationError(ValueError):
    pass


class DuplicateJsonKey(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey
        result[key] = value
    return result


class ArgusArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliInvocationError(message)


def _error(code: str, problem: str, next_action: str, *, exit_code: int) -> dict[str, Any]:
    return {
        "error": {
            "authority": "none",
            "code": code,
            "message": problem,
            "nextAction": next_action,
            "retrySafe": False,
        },
        "exitCode": exit_code,
        "ok": False,
        "schemaVersion": 1,
    }


def dashboard_url(repo: Path) -> dict[str, Any]:
    routes_path = repo / "config" / "routes.json"
    try:
        content = routes_path.read_bytes()
        if len(content) > MAX_ROUTE_BYTES:
            raise ValueError("route configuration exceeds the bounded input limit")
        routes = json.loads(content, object_pairs_hook=reject_duplicate_keys)
    except FileNotFoundError:
        return _error(
            "dashboard-routes-missing",
            "The dashboard route configuration is unavailable.",
            "Run this command from an Argus checkout or set ARGUS_ROOT.",
            exit_code=4,
        )
    except DuplicateJsonKey:
        return _error(
            "dashboard-routes-invalid",
            "The dashboard route configuration contains duplicate JSON fields.",
            "Remove duplicate fields and validate config/routes.json.",
            exit_code=3,
        )
    except (json.JSONDecodeError, RecursionError, ValueError):
        return _error(
            "dashboard-routes-invalid",
            "The dashboard route configuration is invalid bounded JSON.",
            "Validate config/routes.json with python3 -m json.tool.",
            exit_code=3,
        )
    except (PermissionError, UnicodeError, OSError):
        return _error(
            "dashboard-routes-unreadable",
            "The dashboard route configuration cannot be read safely.",
            "Check the Argus root and config/routes.json permissions.",
            exit_code=4,
        )

    if not isinstance(routes, dict):
        return _error(
            "dashboard-routes-invalid",
            "The dashboard route configuration must be a JSON object.",
            "Validate config/routes.json against the reviewed route contract.",
            exit_code=3,
        )
    dashboard = routes.get("dashboard")
    if not isinstance(dashboard, dict):
        return _error(
            "dashboard-route-unconfigured",
            "No dashboard route is configured.",
            "Review the private Tailscale Serve route on oreochiserver.",
            exit_code=3,
        )
    observed = routes.get("observed")
    funnel = observed.get("funnel") if isinstance(observed, dict) else None
    if (
        not isinstance(funnel, dict)
        or funnel.get("enabled") is not False
        or funnel.get("allowedInP0") is not False
        or funnel.get("url", "") != ""
        or funnel.get("target", "") != ""
    ):
        return _error(
            "dashboard-funnel-state-unsafe",
            "The dashboard route cannot be confirmed tailnet-only.",
            "Confirm Funnel is disabled on oreochiserver and record observed.funnel.enabled=false through a reviewed update.",
            exit_code=3,
        )
    url = dashboard.get("url")
    try:
        parsed = urlparse(url) if isinstance(url, str) else None
        port_valid = parsed is not None and (parsed.port is None or 1 <= parsed.port <= 65535)
    except ValueError:
        parsed = None
        port_valid = False
    if (
        dashboard.get("bind") != "tailscale"
        or not parsed
        or not isinstance(url, str)
        or not TAILSCALE_HTTPS_URL.fullmatch(url)
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not port_valid
    ):
        return _error(
            "dashboard-private-route-invalid",
            "The configured dashboard URL is not an approved private HTTPS route.",
            "Inspect Tailscale Serve on oreochiserver and update config/routes.json through a reviewed PR.",
            exit_code=3,
        )
    return {
        "data": {
            "access": "configured-tailnet",
            "command": "dashboard.url",
            "effectiveState": "unverified",
            "source": "config/routes.json",
            "url": url,
        },
        "ok": True,
        "schemaVersion": 1,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = ArgusArgumentParser(prog="argus", description="Private Argus operator commands.")
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=ArgusArgumentParser)
    dashboard = commands.add_parser("dashboard", help="private dashboard information")
    dashboard_commands = dashboard.add_subparsers(dest="dashboard_command", required=True, parser_class=ArgusArgumentParser)
    url = dashboard_commands.add_parser(
        "url",
        help="print the configured private dashboard URL",
        description=(
            "Print the reviewed configured tailnet dashboard URL. Live effective state is not inferred.\n\n"
            "Privilege: unprivileged, read-only.\n"
            "Prerequisites: an Argus checkout with a reviewed config/routes.json and Funnel recorded disabled.\n"
            "Source: config/routes.json; no runtime evidence is written.\n"
            "Example: argus dashboard url --json\n"
            "Recovery: verify Tailscale Serve and Funnel on oreochiserver, then update routes through a reviewed PR."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    url.add_argument("--json", action="store_true", dest="command_json", help="emit canonical JSON")
    return parser


def run(argv: list[str], *, repo: Path, stdout: TextIO, stderr: TextIO) -> int:
    json_output = "--json" in argv
    try:
        args = build_parser().parse_args(argv)
    except CliInvocationError:
        result = _error(
            "invalid-invocation",
            "The command arguments are invalid.",
            "Run argus --help or argus dashboard url --help.",
            exit_code=2,
        )
        if json_output:
            public = {key: value for key, value in result.items() if key != "exitCode"}
            print(json.dumps(public, sort_keys=True, separators=(",", ":")), file=stdout)
        else:
            print(f"ERROR {result['error']['code']}: {result['error']['message']}", file=stderr)
            print(f"NEXT {result['error']['nextAction']}", file=stderr)
        return 2
    json_output = args.json or getattr(args, "command_json", False)
    if args.command == "dashboard" and args.dashboard_command == "url":
        result = dashboard_url(repo)
    else:  # pragma: no cover - argparse prevents this path
        result = _error("command-unsupported", "The command is unsupported.", "Run argus --help.", exit_code=2)

    if json_output:
        public = {key: value for key, value in result.items() if key != "exitCode"}
        print(json.dumps(public, sort_keys=True, separators=(",", ":")), file=stdout)
    elif result["ok"]:
        print(f"CONFIGURED_URL {result['data']['url']}", file=stdout)
        print(f"EFFECTIVE_STATE {result['data']['effectiveState']}", file=stdout)
    else:
        print(f"ERROR {result['error']['code']}: {result['error']['message']}", file=stderr)
        print(f"NEXT {result['error']['nextAction']}", file=stderr)
    return 0 if result["ok"] else result["exitCode"]


def main(argv: list[str] | None = None) -> int:
    override = os.environ.get("ARGUS_ROOT")
    repo = Path(override).expanduser().resolve() if override else Path(__file__).resolve().parents[1]
    return run(list(sys.argv[1:] if argv is None else argv), repo=repo, stdout=sys.stdout, stderr=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
