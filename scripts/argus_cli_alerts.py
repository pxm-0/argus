"""Read-only `argus smoke status`, `argus backup list|freshness` and `argus alerts` leaves."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import argus_alert_sources as sources
from argus_alerting import DB_BACKUP_MAX_AGE, PAGE, SMOKE_MAX_AGE, SNAPSHOT_MAX_AGE, iso

Error = Callable[..., dict[str, Any]]
Success = Callable[..., dict[str, Any]]
EXIT_UNAVAILABLE = 4
EXIT_INVOCATION = 2
MAX_LAST = 200
PULL_MAX_AGE = 36 * 3600  # the Mac pull runs twice a day; the poller warns at 7d, the pull itself at 36h


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
            "latest result, age, staleness against 26h, and the last N history rows with failed check names",
            "argus smoke status --last 5 --json",
            "run sudo systemctl start argus-smoke.service on the server to create evidence",
        ),
    )
    status.add_argument("--last", type=int, default=10, help=f"history rows to show (1-{MAX_LAST}, default 10)")

    backup = commands.add_parser("backup", help="off-host backup evidence")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True, parser_class=parser_class)
    for verb, purpose, output in (
        ("list", "List archives in the snapshot pull directory.", "archive names, sizes and ages, newest first"),
        ("freshness", "Report whether each backup source is inside its freshness limit.", "per-source age, limit and verdict"),
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
            "open alerts with severity, since, detail, ack state and the state file age",
            "argus alerts --json",
            "sudo systemctl enable --now argus-alert.timer, then re-run",
        ),
    )


def smoke_status(repo: Path, last: int, *, error: Error, success: Success, current: float | None = None) -> dict[str, Any]:
    if not 1 <= last <= MAX_LAST:
        return error("last-invalid", f"--last must be between 1 and {MAX_LAST}.", "Pass a smaller --last.", exit_code=EXIT_INVOCATION)
    now = time.time() if current is None else current
    latest = sources.smoke_latest(repo)
    history = sources.smoke_history(repo, last)
    if latest is None and not history:
        return error(
            "smoke-evidence-unavailable",
            "No scheduled smoke evidence exists under runtime/smoke.",
            "Run this on the server, or start argus-smoke.service there to create evidence.",
            exit_code=EXIT_UNAVAILABLE,
        )
    age = sources.age_seconds((latest or {}).get("timestamp"), now)
    return success(
        "smoke.status",
        latest=None if latest is None else {key: latest.get(key) for key in ("ok", "timestamp", "failures", "warnings", "exitCode")},
        ageSeconds=None if age is None else int(age),
        stale=age is None or age > SMOKE_MAX_AGE,
        history=history,
        historyShown=len(history),
    )


def _freshness_row(name: str, stamp: Any, limit: int, now: float) -> dict[str, Any]:
    age = sources.age_seconds(stamp, now)
    if age is None:
        return {"source": name, "state": "unavailable", "limitSeconds": limit}
    return {"source": name, "state": "stale" if age > limit else "fresh", "ageSeconds": int(age), "limitSeconds": limit}


def backup_list(*, success: Success, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    directory = sources.pull_dir()
    archives = [
        {"name": row["name"], "size": row["size"], "ageSeconds": int(max(0, now - row["mtime"]))}
        for row in sources.pull_archives(directory)
    ]
    return success("backup.list", directory=str(directory), archives=archives, count=len(archives))


def backup_freshness(*, success: Success, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    snapshot = sources.read_dict(sources.snapshot_last_path())
    pulled = sources.pull_archives(sources.pull_dir())
    rows = [
        _freshness_row("snapshot-last", (snapshot or {}).get("timestamp"), SNAPSHOT_MAX_AGE, now),
        _freshness_row("pull-dir-newest", pulled[0]["mtime"] if pulled else None, PULL_MAX_AGE, now),
    ]
    status = sources.scalar_fields(sources.read_dict(sources.backup_status_path()))
    return success(
        "backup.freshness",
        ok=all(row["state"] == "fresh" for row in rows),
        sources=rows,
        backupStatus=status,
        dbBackupLimitSeconds=DB_BACKUP_MAX_AGE,
        checkedAt=iso(now),
    )


def alerts_status(repo: Path, *, error: Error, success: Success, current: float | None = None) -> dict[str, Any]:
    now = time.time() if current is None else current
    path = repo / "runtime" / "alerts" / "state.json"
    state = sources.read_dict(path)
    if state is None:
        return error(
            "alert-state-unavailable",
            "No alert state exists yet.",
            "Run this on the server after argus-alert.timer has run once.",
            exit_code=EXIT_UNAVAILABLE,
        )
    alerts = [item for item in state.get("alerts", []) if isinstance(item, dict)]
    return success(
        "alerts",
        alerts=alerts,
        open=len(alerts),
        page=sum(1 for item in alerts if item.get("severity") == PAGE),
        generatedAt=state.get("generatedAt"),
        ageSeconds=None if sources.age_seconds(state.get("generatedAt"), now) is None else int(sources.age_seconds(state.get("generatedAt"), now)),
    )


def dispatch(args: Any, repo: Path, *, error: Error, success: Success) -> dict[str, Any]:
    if args.command == "smoke":
        return smoke_status(repo, args.last, error=error, success=success)
    if args.command == "backup":
        return backup_list(success=success) if args.backup_command == "list" else backup_freshness(success=success)
    return alerts_status(repo, error=error, success=success)
