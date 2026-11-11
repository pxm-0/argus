"""Read-only `argus status`: one offline view of what is broken right now, from the existing readers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import argus_alert_sources as sources
import argus_cli_alerts
from argus_alerting import iso

EXIT_REFUSAL = 3
EXIT_UNAVAILABLE = 4
FAILED_WINDOW = 24 * 3600
IN_FLIGHT = ("awaiting-approval", "queued", "running", "rollback-running")


def register(commands: Any, leaf: Callable[..., Any], description: Callable[..., str]) -> None:
    leaf(
        commands,
        "status",
        help_text="show what is broken right now across local evidence",
        contract=description(
            "Aggregate doctor, open alerts, smoke, backup freshness, recent operations and estate coverage into one view.",
            "server read-only",
            "run on the server for full evidence; elsewhere missing sources are reported as unavailable, never as healthy",
            "none",
            "one row per source with state (ok, degraded, unavailable), age and summary; exit 3 when any source is degraded, 4 when none is degraded but any is unavailable",
            "argus status --json",
            "run the named source's own command (argus alerts, argus smoke status, ...) for its full report",
            "the same local evidence and read-only ledger the per-source commands read",
        ),
    )


def _state(result: dict[str, Any]) -> str:
    if result["ok"]:
        return "ok"
    return "unavailable" if result["exitCode"] == EXIT_UNAVAILABLE else "degraded"


def _row(source: str, result: dict[str, Any], age: Any, summary: str, state: str = "") -> dict[str, Any]:
    return {
        "source": source,
        "state": state or _state(result),
        "code": None if result["ok"] else result["error"]["code"],
        "ageSeconds": None if age is None else int(age),
        "summary": summary if result["ok"] else result["error"]["message"],
    }


def _doctor(repo: Path, cli: Any, runner: Any) -> dict[str, Any]:
    result = cli.doctor_command(repo, runner)
    data = result.get("data", {})
    drift = data.get("m1Drift", {}).get("state", "unknown")
    degraded = result["ok"] and (data.get("compatibility") == "incompatible" or drift == "drift")
    summary = f"compatibility {data.get('compatibility')}, m1 {drift}"
    return _row("doctor", result, None, summary, "degraded" if degraded else "")


def _operations(repo: Path, cli: Any, now: float) -> dict[str, Any]:
    marks = ",".join("?" for _ in IN_FLIGHT)
    rows = cli.query_operations(
        repo,
        f"WHERE state IN ({marks}) OR state = 'indeterminate' OR (state = 'failed' AND created_at >= ?) "
        "ORDER BY created_at DESC LIMIT 200",
        (*IN_FLIGHT, iso(now - FAILED_WINDOW)),
    )
    if isinstance(rows, dict):
        return _row("operations", rows, None, "")
    newest = cli.query_operations(repo, "ORDER BY created_at DESC LIMIT 1", ())
    age = sources.age_seconds(newest[0]["created_at"], now) if isinstance(newest, list) and newest else None
    in_flight = sum(1 for row in rows if row["state"] in IN_FLIGHT)
    problems = [row for row in rows if row["state"] not in IN_FLIGHT]
    result = cli._success("operations")
    summary = f"{in_flight} in flight, {len(problems)} failed (24h) or indeterminate"
    return _row("operations", result, age, summary, "degraded" if problems else "")


def _estate(repo: Path, cli: Any, now: float) -> dict[str, Any]:
    result = cli.estate_command(repo, "status")
    if not result["ok"]:
        return _row("estate", result, None, "")
    data = result["data"]
    refresh, coverage = data["refresh"], data["coverage"]
    summary = f"{len(coverage['freshSources'])}/{len(coverage['requiredSources'])} sources fresh; next: {data['nextAction']}"
    if refresh.get("state") == "never-run":
        state = "unavailable"
    elif coverage["complete"] and refresh.get("state") == "completed":
        state = "ok"
    else:
        state = "degraded"
    return _row("estate", result, sources.age_seconds(refresh.get("finishedAt"), now), summary, state)


def status_command(repo: Path, cli: Any, runner: Any, *, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    common = {"error": cli._error, "success": cli._success, "current": now}
    alerts = argus_cli_alerts.alerts_status(repo, **common)
    smoke = argus_cli_alerts.smoke_status(repo, 1, **common)
    backup = argus_cli_alerts.backup_freshness(**common)
    backup_ages = [row["ageSeconds"] for row in backup.get("data", {}).get("sources", []) if "ageSeconds" in row]
    alerts_data = alerts.get("data", {})
    rows = [
        _doctor(repo, cli, runner),
        _row("alerts", alerts, alerts_data.get("ageSeconds"), f"{alerts_data.get('open')} open, {alerts_data.get('page')} page"),
        _row("smoke", smoke, smoke.get("data", {}).get("ageSeconds"), "latest scheduled run passed"),
        _row("backup", backup, max(backup_ages) if backup_ages else None, "all sources fresh"),
        _operations(repo, cli, now),
        _estate(repo, cli, now),
    ]
    states = {row["state"] for row in rows}
    overall = "degraded" if "degraded" in states else "unavailable" if "unavailable" in states else "ok"
    report = cli._success("status", state=overall, sources=rows, checkedAt=iso(now))
    named = ", ".join(row["source"] for row in rows if row["state"] == overall)
    if overall == "degraded":
        return cli._error("status-degraded", f"Degraded: {named}.", "Run each named source's own command for its full report.", exit_code=EXIT_REFUSAL, retry_safe=True, data=report["data"])
    if overall == "unavailable":
        return cli._error("status-unavailable", f"No evidence: {named}.", "Run this on the server, where every source writes its evidence.", exit_code=EXIT_UNAVAILABLE, retry_safe=True, data=report["data"])
    return report
