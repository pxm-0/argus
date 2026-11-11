"""Compact human renderers for the most-read `argus` commands; --json output never passes through here."""

from __future__ import annotations

from typing import Any, Callable, TextIO


def age(seconds: Any) -> str:
    if not isinstance(seconds, int):
        return "-"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def clean(value: Any) -> str:
    """Printable text only, so evidence files cannot drive the operator's terminal."""
    if value is None or value == "":
        return "-"
    return "".join(character if character.isprintable() else repr(character)[1:-1] for character in str(value))


def yes_no(value: Any) -> str:
    return "yes" if value else "no"


def table(rows: list[list[Any]], stdout: TextIO) -> None:
    text = [[clean(cell) for cell in row] for row in rows]
    widths = [max(len(row[index]) for row in text) for index in range(len(text[0]))]
    for row in text:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip(), file=stdout)


def fields(record: dict[str, Any], keys: list[str], stdout: TextIO) -> None:
    for key in keys:
        print(f"{key:<18}{clean(record.get(key))}", file=stdout)


def _status(data: dict[str, Any], stdout: TextIO) -> None:
    print(f"STATUS {data['state']}  checked {data['checkedAt']}", file=stdout)
    table(
        [["SOURCE", "STATE", "AGE", "SUMMARY"]]
        + [[row["source"], row["state"], age(row["ageSeconds"]), row["summary"]] for row in data["sources"]],
        stdout,
    )


def _workload_list(data: dict[str, Any], stdout: TextIO) -> None:
    table(
        [["ID", "TRUST_DOMAIN", "MIGRATION", "LIFECYCLE", "ACCESS", "PRIVACY"]]
        + [
            [item["id"], item["trustDomain"], item["migrationStatus"], item["lifecycle"], item["effectiveAccess"], item["privacy"]]
            for item in data["workloads"]
        ],
        stdout,
    )


def _workload_show(data: dict[str, Any], stdout: TextIO) -> None:
    workload = data["workload"]
    capabilities = "; ".join(f"{name} {'allowed' if allowed else 'denied'}" for name, allowed in sorted(workload["capabilities"].items()))
    keys = ["id", "name", "kind", "lifecycle", "trustDomain", "privacy", "desiredAccess", "effectiveAccess", "migrationStatus"]
    fields({**workload, "capabilities": capabilities}, [*keys, "capabilities"], stdout)


def _estate(data: dict[str, Any], stdout: TextIO) -> None:
    coverage, refresh = data["coverage"], data["refresh"]
    print(f"ESTATE observation {clean(data['observationState'])}; safe to move: {yes_no(data['safeToMoveWorkloads'])}", file=stdout)
    print(
        f"COVERAGE {len(coverage['freshSources'])}/{len(coverage['requiredSources'])} sources fresh "
        f"({'complete' if coverage['complete'] else 'incomplete'})",
        file=stdout,
    )
    print(f"BLOCKERS {clean(', '.join(coverage['actionBlockers']) or 'none')}", file=stdout)
    print(f"REFRESH {clean(refresh.get('state'))}" + (f" {clean(refresh['finishedAt'])}" if refresh.get("finishedAt") else ""), file=stdout)
    rows = (data.get("reconciliation") or {}).get("coverage", {}).get("sources")
    if isinstance(rows, list) and rows:
        table([["SOURCE", "STATE"]] + [[row.get("sourceId"), row.get("state")] for row in rows if isinstance(row, dict)], stdout)
    print(f"NEXT {clean(data['nextAction'])}", file=stdout)


def _alerts(data: dict[str, Any], stdout: TextIO) -> None:
    stale = "; STALE" if data["stale"] else ""
    print(f"ALERTS {data['open']} open, {data['page']} page; state age {age(data['ageSeconds'])}{stale}", file=stdout)
    if data["alerts"]:
        table(
            [["ID", "SEVERITY", "SINCE", "ACKED", "DETAIL"]]
            + [[item.get("id"), item.get("severity"), item.get("since"), yes_no(item.get("acked")), item.get("detail")] for item in data["alerts"]],
            stdout,
        )


def _smoke(data: dict[str, Any], stdout: TextIO) -> None:
    latest = data["latest"]
    result = "none" if latest is None else "passed" if latest.get("ok") is True else "FAILED"
    stale = "; STALE" if data["stale"] else ""
    print(f"SMOKE latest {result}; age {age(data['ageSeconds'])}{stale}", file=stdout)
    if data["history"]:
        table(
            [["TIMESTAMP", "RESULT", "FAILED_CHECKS"]]
            + [
                [row.get("timestamp"), "passed" if row.get("ok") is True else "failed", "; ".join(map(str, row.get("failedChecks") or []))]
                for row in data["history"]
            ],
            stdout,
        )


def _backup(data: dict[str, Any], stdout: TextIO) -> None:
    print(f"BACKUP all fresh: {yes_no(data['allFresh'])}; checked {data['checkedAt']}", file=stdout)
    table(
        [["SOURCE", "STATE", "AGE", "LIMIT"]]
        + [[row["source"], row["state"], age(row.get("ageSeconds")), age(row["limitSeconds"])] for row in data["sources"]],
        stdout,
    )


def _operation_list(data: dict[str, Any], stdout: TextIO) -> None:
    table(
        [["ID", "WORKLOAD", "TYPE", "STATE", "CREATED", "FINISHED"]]
        + [
            [row["operation_id"], row["workload_id"], row["operation_type"], row["state"], row["created_at"], row["finished_at"]]
            for row in data["operations"]
        ],
        stdout,
    )


def _operation_show(data: dict[str, Any], stdout: TextIO) -> None:
    fields(data["operation"], list(data["operation"]), stdout)


RENDERERS: dict[str, Callable[[dict[str, Any], TextIO], None]] = {
    "status": _status,
    "workload.list": _workload_list,
    "workload.show": _workload_show,
    "estate.status": _estate,
    "estate.coverage": _estate,
    "alerts": _alerts,
    "smoke.status": _smoke,
    "backup.freshness": _backup,
    "operation.list": _operation_list,
    "operation.show": _operation_show,
}


def render(data: dict[str, Any], stdout: TextIO) -> bool:
    """Print `data` for a human and return True, or return False when there is no renderer."""
    renderer = RENDERERS.get(str(data.get("command", "")))
    if renderer is None:
        return False
    renderer(data, stdout)
    return True
