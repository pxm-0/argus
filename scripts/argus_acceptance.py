#!/usr/bin/env python3
"""Validate and render public-safe Argus acceptance summaries."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


PHASES = {"baseline", "pre", "post", "rollback"}
TARGETS = {"oreochiserver", "local-ci", "browser-private-origin"}
RESULTS = {"pass", "fail", "blocked"}
REASON_CODES = {
    "",
    "check-failed",
    "check-refused",
    "check-timeout",
    "evidence-incomplete",
    "rollback-failed",
    "server-access-unavailable",
    "unexpected-reachability",
}
RESULT_REASON_CODES = {
    "pass": {""},
    "fail": {"check-failed", "check-timeout", "rollback-failed", "unexpected-reachability"},
    "blocked": {"check-refused", "evidence-incomplete", "server-access-unavailable"},
}
TOP_LEVEL_KEYS = {
    "schemaVersion",
    "issueId",
    "phase",
    "target",
    "checkId",
    "expectedRuns",
    "sourceRevision",
    "capturedAt",
    "evidenceId",
    "runs",
}
RUN_KEYS = {"ordinal", "result", "durationMs", "reasonCode"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION = re.compile(r"^[0-9a-f]{7,40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class AcceptanceError(ValueError):
    """A stable validation error safe to show to an operator."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcceptanceError("acceptance-invalid", f"{field} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise AcceptanceError("acceptance-invalid", f"{field} must be an integer")
    return int(value)


def _exact_keys(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown:
        raise AcceptanceError("acceptance-field-forbidden", f"{path} contains {len(unknown)} forbidden field(s)")
    if missing:
        raise AcceptanceError("acceptance-field-missing", f"{path} is missing fields: {', '.join(missing)}")


def validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AcceptanceError("acceptance-invalid", "acceptance input must be a JSON object")
    _exact_keys(payload, TOP_LEVEL_KEYS, "summary")
    schema_version = _json_integer(payload["schemaVersion"], "schemaVersion")
    if schema_version != 1:
        raise AcceptanceError("acceptance-version-unsupported", "schemaVersion must be 1")
    issue_id = _json_integer(payload["issueId"], "issueId")
    if issue_id < 1:
        raise AcceptanceError("acceptance-invalid", "issueId must be a positive integer")
    if not isinstance(payload["phase"], str) or not isinstance(payload["target"], str) or payload["phase"] not in PHASES or payload["target"] not in TARGETS:
        raise AcceptanceError("acceptance-invalid", "phase or target is unsupported")
    if not isinstance(payload["checkId"], str) or not SLUG.fullmatch(payload["checkId"]):
        raise AcceptanceError("acceptance-invalid", "checkId must be a lowercase slug")
    expected_runs = _json_integer(payload["expectedRuns"], "expectedRuns")
    if expected_runs != 3:
        raise AcceptanceError("acceptance-invalid", "expectedRuns must be 3")
    if not isinstance(payload["sourceRevision"], str) or not REVISION.fullmatch(payload["sourceRevision"]):
        raise AcceptanceError("acceptance-invalid", "sourceRevision must be a Git hexadecimal revision")
    if not isinstance(payload["capturedAt"], str) or not TIMESTAMP.fullmatch(payload["capturedAt"]):
        raise AcceptanceError("acceptance-invalid", "capturedAt must be UTC RFC3339 without fractions")
    try:
        captured_at = datetime.strptime(payload["capturedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise AcceptanceError("acceptance-invalid", "capturedAt must be a real UTC timestamp") from None
    if captured_at.strftime("%Y-%m-%dT%H:%M:%SZ") != payload["capturedAt"]:
        raise AcceptanceError("acceptance-invalid", "capturedAt must use canonical UTC formatting")
    if not isinstance(payload["evidenceId"], str) or not DIGEST.fullmatch(payload["evidenceId"]):
        raise AcceptanceError("acceptance-invalid", "evidenceId must be a sha256 digest")
    if not isinstance(payload["runs"], list) or len(payload["runs"]) != expected_runs:
        raise AcceptanceError("acceptance-run-count", "runs must contain exactly expectedRuns entries")

    normalized_runs = []
    for index, run in enumerate(payload["runs"], start=1):
        if not isinstance(run, dict):
            raise AcceptanceError("acceptance-invalid", f"runs[{index}] must be an object")
        _exact_keys(run, RUN_KEYS, f"runs[{index}]")
        ordinal = _json_integer(run["ordinal"], f"runs[{index}].ordinal")
        if ordinal != index:
            raise AcceptanceError("acceptance-run-order", "run ordinals must be contiguous and start at 1")
        if not isinstance(run["result"], str) or run["result"] not in RESULTS:
            raise AcceptanceError("acceptance-invalid", f"runs[{index}].result is unsupported")
        duration_ms = _json_integer(run["durationMs"], f"runs[{index}].durationMs")
        if duration_ms < 0:
            raise AcceptanceError("acceptance-invalid", f"runs[{index}].durationMs must be a non-negative integer")
        if not isinstance(run["reasonCode"], str) or run["reasonCode"] not in REASON_CODES:
            raise AcceptanceError("acceptance-invalid", f"runs[{index}].reasonCode is unsupported")
        if run["reasonCode"] not in RESULT_REASON_CODES[run["result"]]:
            raise AcceptanceError("acceptance-result-reason-conflict", f"runs[{index}] result and reasonCode conflict")
        normalized_runs.append(
            {
                "durationMs": duration_ms,
                "ordinal": ordinal,
                "reasonCode": run["reasonCode"],
                "result": run["result"],
            }
        )

    if any(run["result"] == "fail" for run in normalized_runs):
        result = "fail"
    elif any(run["result"] == "blocked" for run in normalized_runs):
        result = "blocked"
    else:
        result = "pass"
    summary = {key: payload[key] for key in sorted(TOP_LEVEL_KEYS - {"runs"})}
    summary["schemaVersion"] = schema_version
    summary["issueId"] = issue_id
    summary["expectedRuns"] = expected_runs
    summary["result"] = result
    summary["runs"] = normalized_runs
    canonical = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
    summary["summaryDigest"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    return (
        f"| {summary['checkId']} | {summary['phase']} | {summary['target']} | "
        f"{len(summary['runs'])}/{summary['expectedRuns']} | {summary['result']} | "
        f"`{summary['evidenceId']}` | `{summary['summaryDigest']}` |\n"
    )
