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


def table(rows: list[list[Any]], stdout: TextIO) -> None:
    text = [["-" if cell is None or cell == "" else str(cell) for cell in row] for row in rows]
    widths = [max(len(row[index]) for row in text) for index in range(len(text[0]))]
    for row in text:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip(), file=stdout)


def _status(data: dict[str, Any], stdout: TextIO) -> None:
    print(f"STATUS {data['state']}  checked {data['checkedAt']}", file=stdout)
    table(
        [["SOURCE", "STATE", "AGE", "SUMMARY"]]
        + [[row["source"], row["state"], age(row["ageSeconds"]), row["summary"]] for row in data["sources"]],
        stdout,
    )


RENDERERS: dict[str, Callable[[dict[str, Any], TextIO], None]] = {
    "status": _status,
}


def render(data: dict[str, Any], stdout: TextIO) -> bool:
    """Print `data` for a human and return True, or return False when there is no renderer."""
    renderer = RENDERERS.get(str(data.get("command", "")))
    if renderer is None:
        return False
    renderer(data, stdout)
    return True
