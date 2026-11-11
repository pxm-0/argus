"""Read-only `argus smoke status`, `argus backup list|freshness` and `argus alerts` leaves."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

import argus_alert_sources as sources
from argus_alerting import DB_BACKUP_MAX_AGE, PAGE, SMOKE_MAX_AGE, SNAPSHOT_MAX_AGE, iso

Error = Callable[..., dict[str, Any]]
Success = Callable[..., dict[str, Any]]
EXIT_UNAVAILABLE = 4
EXIT_REFUSAL = 3
EXIT_INVOCATION = 2
MAX_LAST = 200
PULL_MAX_AGE = 36 * 3600  # the Mac pull runs twice a day; the poller warns at 7d, the pull itself at 36h
ALERT_STATE_MAX_AGE = 2 * 120  # two argus-alert.timer periods (OnUnitActiveSec=2min)


def register(commands: Any, leaf: Callable[..., Any], description: Callable[..., str], parser_class: Any) -> None:
    smoke = commands.add_parser("smoke", help="scheduled smoke evidence")
    smoke_sub = smoke.add_subparsers(dest="smoke_command", required=True, parser_class=parser_class)
    status = leaf(
        smoke_sub,
        "status",
        help_text="show the latest scheduled smoke result and recent history",
        contract=description(
            "Show the newest scheduled smoke result and the capped 30-day history.",
            "server read-only",
            "run on the server (or a checkout with runtime/smoke evidence)",
            "none",
            "latest result, age, staleness against 26h, and the last N history rows with failed check names; exit 3 when the latest run failed or is stale, 4 when no evidence exists",
            "argus smoke status --last 5 --json",
            "run sudo systemctl start argus-smoke.service on the server to create evidence",
            "runtime/smoke evidence written by argus-smoke",
        ),
    )
    status.add_argument("--last", type=int, default=10, help=f"history rows to show (1-{MAX_LAST}, default 10)")

    backup = commands.add_parser("backup", help="off-host backup evidence")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True, parser_class=parser_class)
    for verb, purpose, output in (
        ("list", "List archives in the snapshot pull directory.", "archive names, sizes and ages, newest first; exit 4 when the directory is missing or unreadable"),
        ("freshness", "Report whether each backup source is inside its freshness limit.", "per-source age, limit and verdict plus allFresh; exit 3 when any source is stale, 4 when any is unavailable"),
    ):
        leaf(
            backup_sub,
            verb,
            help_text=purpose.lower().rstrip("."),
            contract=description(
                purpose,
                "server read-only",
                "run on the server; missing evidence is reported as unavailable, not as healthy",
                "none",
                output,
                f"argus backup {verb} --json",
                "see docs/MONITORING.md for where each source is written",
                "snapshot-last.json, backup-status.json and the snapshot pull directory on the server",
            ),
        )

    leaf(
        commands,
        "alerts",
        help_text="show open alerts from the evaluator",
        contract=description(
            "Show the alerts that argus-alert currently holds open.",
            "server read-only",
            "run on the server; argus-alert.timer must have run once",
            "none",
            "open alerts with severity, since, detail, ack state, the state file age and stale flag; exit 3 when a page alert is open or the state is stale, 4 when it is missing or unreadable",
            "argus alerts --json",
            "sudo systemctl enable --now argus-alert.timer, then re-run",
            "runtime/alerts/state.json written by argus-alert",
        ),
    )


def smoke_status(repo: Path, last: int, *, error: Error, success: Success, current: float | None = None) -> dict[str, Any]:
    if not 1 <= last <= MAX_LAST:
        return error("last-invalid", f"--last must be between 1 and {MAX_LAST}.", f"Pass --last between 1 and {MAX_LAST}.", exit_code=EXIT_INVOCATION)
    now = time.time() if current is None else current
    latest = sources.smoke_latest(repo)
    history = sources.smoke_history(repo, last)
    if latest is None and not history:
        return error(
            "smoke-evidence-unavailable",
            "No scheduled smoke evidence exists under runtime/smoke.",
            "Run this on the server, or start argus-smoke.service there to create evidence.",
            exit_code=EXIT_UNAVAILABLE,
            retry_safe=True,
        )
    age = sources.age_seconds((latest or {}).get("timestamp"), now)
    report = success(
        "smoke.status",
        latest=None if latest is None else {key: latest.get(key) for key in ("ok", "timestamp", "failures", "warnings", "exitCode")},
        ageSeconds=None if age is None else int(age),
        stale=age is None or age > SMOKE_MAX_AGE,
        history=history,
        historyShown=len(history),
    )
    if latest is not None and latest.get("ok") is not True:
        return error("smoke-failed", "The latest scheduled smoke run failed.", "Inspect the failed checks in the history and fix them on the server.", exit_code=EXIT_REFUSAL, retry_safe=True, data=report["data"])
    if report["data"]["stale"]:
        return error("smoke-stale", "The latest scheduled smoke result is missing or older than 26h.", "Check argus-smoke.timer on the server.", exit_code=EXIT_REFUSAL, retry_safe=True, data=report["data"])
    return report


def _freshness_row(name: str, stamp: Any, limit: int, now: float) -> dict[str, Any]:
    age = sources.age_seconds(stamp, now)
    if age is None:
        return {"source": name, "state": "unavailable", "limitSeconds": limit}
    return {"source": name, "state": "stale" if age > limit else "fresh", "ageSeconds": int(age), "limitSeconds": limit}


def backup_list(*, error: Error, success: Success, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    directory = sources.pull_dir()
    if not directory.is_dir() or not os.access(directory, os.R_OK | os.X_OK):
        return error(
            "backup-pull-dir-unavailable",
            f"The snapshot pull directory {directory} is missing or unreadable.",
            "Run this on the server; see docs/MONITORING.md for where the pull writes.",
            exit_code=EXIT_UNAVAILABLE,
            retry_safe=True,
        )
    archives = [
        {"name": row["name"], "size": row["size"], "ageSeconds": int(max(0, now - row["mtime"]))}
        for row in sources.pull_archives(directory)
    ]
    return success("backup.list", directory=str(directory), archives=archives, count=len(archives))


def backup_freshness(*, error: Error, success: Success, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    snapshot = sources.read_dict(sources.snapshot_last_path())
    pulled = sources.pull_archives(sources.pull_dir())
    rows = [
        _freshness_row("snapshot-last", (snapshot or {}).get("timestamp"), SNAPSHOT_MAX_AGE, now),
        _freshness_row("pull-dir-newest", pulled[0]["mtime"] if pulled else None, PULL_MAX_AGE, now),
    ]
    status = sources.scalar_fields(sources.read_dict(sources.backup_status_path()))
    report = success(
        "backup.freshness",
        allFresh=all(row["state"] == "fresh" for row in rows),
        sources=rows,
        backupStatus=status,
        dbBackupLimitSeconds=DB_BACKUP_MAX_AGE,
        checkedAt=iso(now),
    )
    states = {row["state"] for row in rows}
    if "unavailable" in states:
        return error("backup-evidence-unavailable", "At least one backup source has no readable evidence.", "Run this on the server; see docs/MONITORING.md for where each source is written.", exit_code=EXIT_UNAVAILABLE, retry_safe=True, data=report["data"])
    if "stale" in states:
        return error("backup-stale", "At least one backup source is older than its freshness limit.", "Check the snapshot and pull timers named in docs/MONITORING.md.", exit_code=EXIT_REFUSAL, retry_safe=True, data=report["data"])
    return report


def alerts_status(repo: Path, *, error: Error, success: Success, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    path = repo / "runtime" / "alerts" / "state.json"
    if not path.exists():
        return error(
            "alert-state-unavailable",
            "No alert state exists yet.",
            "Run this on the server after argus-alert.timer has run once.",
            exit_code=EXIT_UNAVAILABLE,
            retry_safe=True,
        )
    state = sources.read_dict(path)
    if state is None or not isinstance(state.get("alerts", []), list):
        return error(
            "alert-state-unreadable",
            "The alert state file exists but cannot be read or is not a valid alert state.",
            "Check runtime/alerts/state.json permissions on the server; argus-alert rewrites it on its next run.",
            exit_code=EXIT_UNAVAILABLE,
            retry_safe=True,
        )
    alerts = [item for item in state.get("alerts", []) if isinstance(item, dict)]
    age = sources.age_seconds(state.get("generatedAt"), now)
    report = success(
        "alerts",
        alerts=alerts,
        open=len(alerts),
        page=sum(1 for item in alerts if item.get("severity") == PAGE),
        generatedAt=state.get("generatedAt"),
        ageSeconds=None if age is None else int(age),
        stale=age is None or age > ALERT_STATE_MAX_AGE,
    )
    if report["data"]["stale"]:
        return error("alert-state-stale", "The alert state is older than two argus-alert.timer periods, so open alerts may be out of date.", "Check argus-alert.timer on the server.", exit_code=EXIT_REFUSAL, retry_safe=True, data=report["data"])
    if report["data"]["page"]:
        return error("alerts-page-open", f"{report['data']['page']} page-severity alert(s) are open.", "Handle the listed page alerts; see docs/MONITORING.md.", exit_code=EXIT_REFUSAL, retry_safe=True, data=report["data"])
    return report


def dispatch(args: Any, repo: Path, *, error: Error, success: Success) -> dict[str, Any]:
    if args.command == "smoke":
        return smoke_status(repo, args.last, error=error, success=success)
    if args.command == "backup":
        return backup_list(error=error, success=success) if args.backup_command == "list" else backup_freshness(error=error, success=success)
    return alerts_status(repo, error=error, success=success)
