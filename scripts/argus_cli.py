#!/usr/bin/env python3
"""Stable deterministic Argus operator command dispatcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.parse import urlparse

from argus_observations import ObservationError, ObservationRepository, digest, load_registry
from argus_reconciliation import reconcile


TAILSCALE_HTTPS_URL = re.compile(
    r"^https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.ts\.net(?::[1-9][0-9]{0,4})?/?$"
)
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
OPERATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_JSON_BYTES = 65536
MAX_JSON_DEPTH = 128
OPERATIONS_SCHEMA_VERSION = 1
REQUIRED_ESTATE_SOURCES = (
    "rootful-docker",
    "rootless-docker",
    "system-systemd",
    "user-systemd",
    "cron",
    "process-listeners",
    "proxy-overlay",
    "configured-roots",
)
EXIT_INTERNAL = 1
EXIT_INVOCATION = 2
EXIT_REFUSAL = 3
EXIT_UNAVAILABLE = 4
EXIT_INDETERMINATE = 5
Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


class CliInvocationError(ValueError):
    pass


class DuplicateJsonKey(ValueError):
    pass


class ArgusArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliInvocationError(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey
        result[key] = value
    return result


def reject_excessive_json_depth(content: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in content:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds the deterministic depth limit")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("JSON delimiters are unbalanced")
    if in_string or depth != 0:
        raise ValueError("JSON structure is incomplete")


def load_json(repo: Path, relative: str) -> Any:
    path = repo / relative
    content = path.read_bytes()
    if len(content) > MAX_JSON_BYTES:
        raise ValueError(f"{relative} exceeds the bounded input limit")
    decoded = content.decode("utf-8")
    reject_excessive_json_depth(decoded)
    return json.loads(decoded, object_pairs_hook=reject_duplicate_keys)


def safe_text(value: Any, *, default: str = "", maximum: int = 128) -> str:
    if value is None and default:
        return default
    if not isinstance(value, str) or len(value) > maximum or any(ord(character) < 32 for character in value):
        raise ValueError("unsafe text field")
    return value


def object_at(value: Any, key: str) -> dict[str, Any]:
    child = value.get(key, {}) if isinstance(value, dict) else None
    if not isinstance(child, dict):
        raise ValueError(f"{key} must be an object")
    return child


def _error(
    code: str,
    problem: str,
    next_action: str,
    *,
    exit_code: int,
    authority: str = "none",
    retry_safe: bool = False,
    evidence_id: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "authority": authority,
        "code": code,
        "message": problem,
        "nextAction": next_action,
        "retrySafe": retry_safe,
    }
    if evidence_id:
        error["evidenceId"] = evidence_id
    result = {
        "error": error,
        "exitCode": exit_code,
        "ok": False,
        "schemaVersion": 1,
    }
    if data is not None:
        result["data"] = data
    return result


def _success(command: str, **data: Any) -> dict[str, Any]:
    return {"data": {"command": command, **data}, "ok": True, "schemaVersion": 1}


def config_error(name: str, exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, FileNotFoundError):
        return _error(
            f"{name}-missing",
            f"The required {name} configuration is unavailable.",
            "Run from a reviewed Argus checkout or set ARGUS_ROOT.",
            exit_code=EXIT_UNAVAILABLE,
        )
    if isinstance(exc, (PermissionError, UnicodeError, OSError)):
        return _error(
            f"{name}-unreadable",
            f"The required {name} configuration cannot be read safely.",
            "Check the Argus root and file permissions without printing its contents.",
            exit_code=EXIT_UNAVAILABLE,
        )
    return _error(
        f"{name}-invalid",
        f"The required {name} configuration is invalid bounded JSON.",
        "Validate the reviewed JSON configuration and retry.",
        exit_code=EXIT_REFUSAL,
    )


def dashboard_url(repo: Path) -> dict[str, Any]:
    try:
        routes = load_json(repo, "config/routes.json")
    except (FileNotFoundError, PermissionError, UnicodeError, OSError, DuplicateJsonKey, json.JSONDecodeError, RecursionError, ValueError) as exc:
        result = config_error("dashboard-routes", exc)
        if isinstance(exc, DuplicateJsonKey):
            result["error"]["message"] = "The dashboard route configuration contains duplicate JSON fields."
        return result
    if not isinstance(routes, dict):
        return _error(
            "dashboard-routes-invalid",
            "The dashboard route configuration must be a JSON object.",
            "Validate config/routes.json against the reviewed route contract.",
            exit_code=EXIT_REFUSAL,
        )
    dashboard = routes.get("dashboard")
    if not isinstance(dashboard, dict):
        return _error(
            "dashboard-route-unconfigured",
            "No dashboard route is configured.",
            "Review the private Tailscale Serve route on oreochiserver.",
            exit_code=EXIT_REFUSAL,
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
            "Confirm Funnel is disabled on oreochiserver and record the reviewed observation.",
            exit_code=EXIT_REFUSAL,
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
            "Inspect Tailscale Serve on oreochiserver and update routes through a reviewed PR.",
            exit_code=EXIT_REFUSAL,
        )
    return _success(
        "dashboard.url",
        access="configured-tailnet",
        effectiveState="unverified",
        source="config/routes.json",
        url=url,
    )


def workload_records(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]] | dict[str, Any]:
    try:
        workload_config = load_json(repo, "config/workloads.json")
        privacy = load_json(repo, "config/privacy.json")
        access = load_json(repo, "config/access.json")
        classification = load_json(repo, "config/argus/workload-classification.json")
    except (FileNotFoundError, PermissionError, UnicodeError, OSError, DuplicateJsonKey, json.JSONDecodeError, RecursionError, ValueError) as exc:
        return config_error("workload-registry", exc)
    workloads = workload_config.get("workloads") if isinstance(workload_config, dict) else None
    if (
        not isinstance(workloads, list)
        or not all(isinstance(item, dict) for item in workloads)
        or not all(isinstance(item.get("id"), str) and SAFE_ID.fullmatch(item["id"]) for item in workloads)
        or len({item["id"] for item in workloads}) != len(workloads)
        or not all(isinstance(value, dict) for value in (privacy, access, classification))
    ):
        return _error(
            "workload-registry-invalid",
            "The workload registry does not contain a valid workload list.",
            "Validate config/workloads.json and retry.",
            exit_code=EXIT_REFUSAL,
        )
    return workloads, privacy, access, classification


def estate_command(repo: Path, action: str) -> dict[str, Any]:
    records = workload_records(repo)
    if isinstance(records, dict):
        return records
    workloads, _, _, _ = records
    workload_ids = sorted(item["id"] for item in workloads)
    coverage = {
        "actionBlockers": ["configured-source-coverage-incomplete"],
        "complete": False,
        "configuredWorkloadCount": len(workload_ids),
        "configuredWorkloadIds": workload_ids,
        "freshSources": [],
        "legacyRefreshScope": "rootful-compose-containers-only",
        "requiredSources": list(REQUIRED_ESTATE_SOURCES),
    }
    reconciliation: dict[str, Any] | None = None
    registry_path = repo / "config" / "argus" / "observation-sources.json"
    database = Path(os.environ.get("ARGUS_OBSERVATIONS_DB", repo / "runtime" / "argus" / "observations.sqlite3"))
    if registry_path.is_file() and database.is_file():
        try:
            registry = load_registry(registry_path, repo)
            with ObservationRepository(database, read_only=True) as repository:
                reconciliation = reconcile(
                    repo,
                    repository,
                    registry,
                    explicit_clock=os.environ.get("ARGUS_OBSERVATIONS_CLOCK"),
                )
        except (ObservationError, OSError, ValueError, sqlite3.Error):
            reconciliation = {
                "schemaVersion": 1,
                "status": "unavailable",
                "observationState": "incomplete",
                "blockers": [{"code": "observation-repository-unavailable"}],
                "safeToMoveWorkloads": False,
                "mutationAuthority": "none",
            }
            reconciliation["evidenceDigest"] = digest(reconciliation)
    if reconciliation is not None and reconciliation.get("status") != "unavailable":
        source_rows = reconciliation.get("coverage", {}).get("sources", [])
        coverage["complete"] = reconciliation.get("coverage", {}).get("status") == "complete"
        coverage["freshSources"] = [
            row["sourceId"] for row in source_rows if row.get("state") == "fresh"
        ]
        coverage["actionBlockers"] = [
            code for code in sorted({
                entry["code"] for entry in reconciliation.get("blockers", [])
                if isinstance(entry, dict) and isinstance(entry.get("code"), str)
            })
        ]
    if action == "refresh":
        return _error(
            "estate-refresh-contract-incomplete",
            "The legacy refresh only scans rootful Compose containers and cannot claim whole-estate completeness.",
            "Use argus estate coverage; implement the approved D1-D5 collectors before enabling refresh.",
            exit_code=EXIT_REFUSAL,
            authority="repository-read-only",
        )
    return _success(
        f"estate.{action}",
        coverage=coverage,
        observationState=(reconciliation or {}).get("observationState", "incomplete"),
        safeToMoveWorkloads=(reconciliation or {}).get("safeToMoveWorkloads", False),
        **({"reconciliation": reconciliation} if reconciliation is not None else {}),
    )


def workload_list(repo: Path) -> dict[str, Any]:
    records = workload_records(repo)
    if isinstance(records, dict):
        return records
    workloads, privacy, access, classification = records
    rows: list[dict[str, Any]] = []
    try:
        privacy_rows = object_at(privacy, "workloads")
        access_rows = object_at(access, "workloads")
        classification_rows = object_at(classification, "workloads")
        for item in workloads:
            workload_id = item["id"]
            privacy_row = privacy_rows.get(workload_id, {})
            access_row = access_rows.get(workload_id, {})
            classification_row = classification_rows.get(workload_id, {})
            migration = item.get("migration", {})
            if not all(isinstance(value, dict) for value in (privacy_row, access_row, classification_row, migration)):
                raise ValueError("workload policy row must be an object")
            rows.append(
                {
                    "desiredAccess": safe_text(access_row.get("desired", "")),
                    "effectiveAccess": safe_text(access_row.get("effective", "")),
                    "id": workload_id,
                    "kind": safe_text(item.get("kind", "")),
                    "lifecycle": safe_text(item.get("lifecycle", "")),
                    "migrationStatus": safe_text(migration.get("status", "")),
                    "name": safe_text(item.get("name"), default=workload_id),
                    "privacy": safe_text(privacy_row.get("privacy", "")),
                    "trustDomain": safe_text(classification_row.get("trustDomain", "")),
                }
            )
    except (KeyError, ValueError):
        return _error(
            "workload-registry-invalid",
            "A workload or policy field violates the stable CLI contract.",
            "Validate the canonical workload, privacy, access, and classification records.",
            exit_code=EXIT_REFUSAL,
        )
    return _success("workload.list", workloads=sorted(rows, key=lambda item: item["id"]))


def workload_show(repo: Path, workload_id: str) -> dict[str, Any]:
    listing = workload_list(repo)
    if not listing["ok"]:
        return listing
    item = next((row for row in listing["data"]["workloads"] if row["id"] == workload_id), None)
    if item is None:
        return _error(
            "workload-not-found",
            "The requested workload is not in the canonical registry.",
            "Run argus workload list and retry with an exact workload ID.",
            exit_code=EXIT_REFUSAL,
        )
    try:
        manifest = load_json(repo, f"workloads/{workload_id}/manifest.json")
    except FileNotFoundError:
        manifest = {}
    except (PermissionError, UnicodeError, OSError, DuplicateJsonKey, json.JSONDecodeError, RecursionError, ValueError) as exc:
        return config_error("workload-manifest", exc)
    operations = manifest.get("operations", {}) if isinstance(manifest, dict) else None
    if not isinstance(operations, dict):
        return _error(
            "workload-manifest-invalid",
            "The workload operations manifest has the wrong shape.",
            "Validate the reviewed workload manifest and retry.",
            exit_code=EXIT_REFUSAL,
        )
    capabilities = {
        key: bool(value.get("allowed"))
        for key, value in operations.items()
        if isinstance(key, str) and isinstance(value, dict) and isinstance(value.get("allowed"), bool)
    }
    return _success("workload.show", workload={**item, "capabilities": capabilities})


def move_preview(repo: Path, workload_id: str) -> dict[str, Any]:
    shown = workload_show(repo, workload_id)
    if not shown["ok"]:
        return shown
    workload = shown["data"]["workload"]
    return _success(
        "workload.move.preview",
        workloadId=workload_id,
        migrationId=None,
        phase="not-started",
        currentAuthority=workload.get("trustDomain") or "unknown",
        eligibleTargets=[],
        eligible=False,
        blockers=["configured-source-coverage-incomplete", "migration-kernel-unavailable"],
        retrySafe=True,
        statusCommand=f"argus workload move status {workload_id} --json",
        recoveryCommand=f"argus workload move preview {workload_id} --json",
        nextAction="Run argus estate coverage and wait for the approved D5/M2 gates.",
    )


def migration_context(action: str, workload_id: str, preview: dict[str, Any], *, retry_safe: bool) -> dict[str, Any]:
    return {
        "blockers": list(preview["data"]["blockers"]),
        "command": f"workload.move.{action}",
        "currentAuthority": preview["data"]["currentAuthority"],
        "eligibleTargets": list(preview["data"]["eligibleTargets"]),
        "migrationId": None,
        "phase": "not-started",
        "recoveryCommand": f"argus workload move preview {workload_id} --json",
        "retrySafe": retry_safe,
        "statusCommand": f"argus workload move status {workload_id} --json",
        "workloadId": workload_id,
    }


def move_command(repo: Path, action: str, workload_id: str, confirmation: str = "") -> dict[str, Any]:
    preview = move_preview(repo, workload_id)
    if not preview["ok"]:
        return preview
    if action == "preview":
        return preview
    if action == "status":
        return {"data": migration_context(action, workload_id, preview, retry_safe=True), "ok": True, "schemaVersion": 1}
    if action == "preflight":
        return _error(
            "workload-move-preflight-blocked",
            "Fresh configured-source coverage and the migration eligibility contract are unavailable.",
            "Run argus workload move preview and argus estate coverage.",
            exit_code=EXIT_REFUSAL,
            authority=str(preview["data"]["currentAuthority"]),
            retry_safe=True,
            data=migration_context(action, workload_id, preview, retry_safe=True),
        )
    if confirmation != workload_id:
        return _error(
            "workload-move-confirmation-required",
            "The authority-changing operation lacks the exact workload confirmation.",
            f"Review the preview, then pass --confirm {workload_id} only when an approved kernel is available.",
            exit_code=EXIT_REFUSAL,
            authority=str(preview["data"]["currentAuthority"]),
            data=migration_context(action, workload_id, preview, retry_safe=False),
        )
    return _error(
        "workload-move-kernel-unavailable",
        "No approved parent/child migration kernel is installed; no authority was changed.",
        "Do not use milestone migration scripts; complete the approved M1-M3 gates.",
        exit_code=EXIT_UNAVAILABLE,
        authority=str(preview["data"]["currentAuthority"]),
        retry_safe=False,
        data=migration_context(action, workload_id, preview, retry_safe=False),
    )


def operation_show(repo: Path, operation_id: str) -> dict[str, Any]:
    ledger = Path(os.environ.get("ARGUS_OPERATIONS_DB", repo / "runtime" / "argus" / "m5" / "operations.sqlite3"))
    if not ledger.is_file():
        return _error(
            "operation-ledger-unavailable",
            "The durable operation ledger is not available in this environment.",
            "Run this read-only command on oreochiserver or set ARGUS_OPERATIONS_DB.",
            exit_code=EXIT_UNAVAILABLE,
            retry_safe=True,
        )
    try:
        connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version != OPERATIONS_SCHEMA_VERSION:
                return _error(
                    "operation-ledger-version-unsupported",
                    "The operation ledger schema is incompatible with this CLI.",
                    "Run argus doctor --json and reconcile deployed/repository revisions.",
                    exit_code=EXIT_REFUSAL,
                )
            row = connection.execute(
                """
                SELECT operation_id, workload_id, trust_domain, operation_type,
                       state, created_at, started_at, finished_at, error_class,
                       redacted_summary
                FROM operations WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return _error(
            "operation-ledger-unavailable",
            "The durable operation ledger could not be read safely.",
            "Check the read-only ledger path and run argus doctor --json.",
            exit_code=EXIT_UNAVAILABLE,
        )
    if row is None:
        return _error(
            "operation-not-found",
            "The requested operation is not present in the durable ledger.",
            "Verify the operation ID with the initiating workflow.",
            exit_code=EXIT_REFUSAL,
        )
    return _success("operation.show", operation={key: row[key] for key in row.keys()})


def operation_recover(operation_id: str, confirmation: str) -> dict[str, Any]:
    if confirmation != operation_id:
        return _error(
            "operation-recovery-confirmation-required",
            "Recovery lacks the exact operation ID confirmation.",
            f"Inspect argus operation show {operation_id}, then pass --confirm {operation_id}.",
            exit_code=EXIT_REFUSAL,
        )
    return _error(
        "operation-recovery-unavailable",
        "No generic recovery mutation is approved for this operation.",
        f"Inspect argus operation show {operation_id} and use its typed recovery runbook.",
        exit_code=EXIT_UNAVAILABLE,
        authority="operation-ledger",
    )


def default_runner(command: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def repository_revision(repo: Path, runner: Runner) -> str:
    result = runner(["git", "rev-parse", "HEAD"], repo)
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else "unavailable"


def doctor_command(repo: Path, runner: Runner) -> dict[str, Any]:
    audit = runner([str(repo / "scripts" / "argus-doctor"), "--json"], repo)
    try:
        audit_payload = json.loads(audit.stdout)
    except (json.JSONDecodeError, TypeError):
        return _error(
            "doctor-audit-unavailable",
            "The deterministic security audit did not return valid JSON.",
            "Run ./scripts/argus-doctor --json from the reviewed checkout.",
            exit_code=EXIT_UNAVAILABLE,
        )
    if not isinstance(audit_payload, dict):
        return _error(
            "doctor-audit-unavailable",
            "The deterministic security audit returned the wrong JSON shape.",
            "Run ./scripts/argus-doctor --json from the reviewed checkout.",
            exit_code=EXIT_UNAVAILABLE,
        )
    if audit.returncode != 0 or audit_payload.get("ok") is not True:
        return _error(
            "doctor-audit-failed",
            "One or more deterministic security checks failed.",
            "Review ./scripts/argus-doctor --json and fix the named check before mutation.",
            exit_code=EXIT_REFUSAL,
        )
    try:
        boundary = load_json(repo, "config/core-boundary-policy.json")
    except (FileNotFoundError, PermissionError, UnicodeError, OSError, DuplicateJsonKey, json.JSONDecodeError, RecursionError, ValueError) as exc:
        return config_error("core-boundary-policy", exc)
    if not isinstance(boundary, dict):
        return _error(
            "core-boundary-policy-invalid",
            "The deterministic core boundary policy has the wrong shape.",
            "Validate config/core-boundary-policy.json and rerun argus doctor.",
            exit_code=EXIT_REFUSAL,
        )
    revision = repository_revision(repo, runner)
    return _success(
        "doctor",
        argusRevision=revision,
        deployedRevision=revision if repo == Path("/srv/argus") else "unavailable",
        operationLedgerSchema={"supported": OPERATIONS_SCHEMA_VERSION, "deployed": "unverified"},
        discoveryRepositorySchema={"supported": "not-installed", "deployed": "not-installed"},
        collectorProtocol={"supported": "not-installed", "deployed": "not-installed"},
        coreBoundary={
            "policyVersion": boundary.get("policyVersion"),
            "auditVersion": boundary.get("auditVersion"),
            "result": "pass",
        },
        lastCompletedCollection=None,
        lastSafeRollbackPoint=None,
        compatibility="partial-discovery-not-installed",
        nextAction="Use argus estate coverage; do not move workloads until D5/M2 gates pass.",
    )


def check_command(repo: Path, runner: Runner) -> dict[str, Any]:
    result = runner([str(repo / "scripts" / "argus-check")], repo)
    output = result.stdout or ""
    output_digest = "sha256:" + hashlib.sha256(output.encode()).hexdigest()
    if result.returncode in {-2, -15, 130, 143}:
        return _error(
            "repository-check-interrupted",
            "The canonical repository check was interrupted and its result is indeterminate.",
            "Rerun argus check from a clean checkout; do not treat partial output as evidence.",
            exit_code=EXIT_INDETERMINATE,
            evidence_id=output_digest,
        )
    if result.returncode != 0:
        return _error(
            "repository-check-failed",
            "The canonical repository check failed.",
            "Run ./scripts/argus-check, fix the first named failure, and retry.",
            exit_code=EXIT_INTERNAL,
            evidence_id=output_digest,
        )
    return _success(
        "check",
        result="pass",
        outputDigest=output_digest,
        argusRevision=repository_revision(repo, runner),
        nextAction="Review the sanitized diff before opening or updating the PR.",
    )


def description(
    purpose: str,
    privilege: str,
    prerequisites: str,
    side_effects: str,
    output: str,
    example: str,
    recovery: str,
) -> str:
    return (
        f"{purpose}\n\nPrivilege: {privilege}.\nPrerequisites: {prerequisites}.\n"
        f"Side effects: {side_effects}.\nSource: reviewed Argus configuration and local evidence only.\n"
        f"Output: {output}.\nExample: {example}\nRecovery: {recovery}."
    )


def leaf(parent: argparse._SubParsersAction[Any], name: str, *, help_text: str, contract: str) -> argparse.ArgumentParser:
    parser = parent.add_parser(
        name,
        help=help_text,
        description=contract,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", dest="command_json", help="emit canonical JSON")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = ArgusArgumentParser(prog="argus", description="Private deterministic Argus operator commands.")
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=ArgusArgumentParser)

    dashboard = commands.add_parser("dashboard", help="private dashboard information")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_command", required=True, parser_class=ArgusArgumentParser)
    leaf(
        dashboard_sub,
        "url",
        help_text="print the configured private dashboard URL",
        contract=description(
            "Print the reviewed configured tailnet dashboard URL; never infer live state.",
            "unprivileged, read-only",
            "reviewed config/routes.json with Funnel recorded disabled",
            "none",
            "configured URL and unverified effective-state label",
            "argus dashboard url --json",
            "verify Tailscale Serve and Funnel on oreochiserver, then update routes through a reviewed PR",
        ),
    )

    estate = commands.add_parser("estate", help="configured-estate status and coverage")
    estate_sub = estate.add_subparsers(dest="estate_command", required=True, parser_class=ArgusArgumentParser)
    for action in ("status", "coverage", "refresh"):
        privilege = "server read-only" if action == "refresh" else "unprivileged, read-only"
        leaf(
            estate_sub,
            action,
            help_text=f"{action} configured-estate evidence",
            contract=description(
                f"{action.title()} configured-estate evidence without claiming missing sources.",
                privilege,
                "reviewed workload registry",
                "none; refresh currently refuses until D1-D5 collectors exist",
                "coverage, blockers, and exact next action",
                f"argus estate {action} --json",
                "inspect argus estate coverage and complete the named collector gate",
            ),
        )

    workload = commands.add_parser("workload", help="canonical workload information and moves")
    workload_sub = workload.add_subparsers(dest="workload_command", required=True, parser_class=ArgusArgumentParser)
    leaf(
        workload_sub,
        "list",
        help_text="list canonical workloads",
        contract=description("List canonical workloads.", "unprivileged, read-only", "reviewed registry", "none", "sanitized workload summaries", "argus workload list --json", "validate the registry"),
    )
    show = leaf(
        workload_sub,
        "show",
        help_text="show one canonical workload",
        contract=description("Show one canonical workload.", "unprivileged, read-only", "exact workload ID", "none", "sanitized identity and capability summary", "argus workload show nodens --json", "run argus workload list"),
    )
    show.add_argument("workload_id")
    move = workload_sub.add_parser("move", help="preview and control reviewed workload moves")
    move_sub = move.add_subparsers(dest="move_command", required=True, parser_class=ArgusArgumentParser)
    for action in ("preview", "preflight", "status", "apply", "rollback"):
        privilege = "server mutation with exact confirmation" if action in {"apply", "rollback"} else "unprivileged, read-only"
        item = leaf(
            move_sub,
            action,
            help_text=f"{action} a reviewed workload move",
            contract=description(
                f"{action.title()} a typed workload move; unavailable kernels fail closed.",
                privilege,
                "exact workload ID, fresh coverage, and approved migration kernel",
                "none until the final reviewed apply or rollback boundary",
                "authority, phase, blockers, retry safety, and recovery",
                f"argus workload move {action} nodens"
                + (" --confirm nodens" if action in {"apply", "rollback"} else "")
                + " --json",
                "run the matching status and preview commands; never use milestone scripts as a substitute",
            ),
        )
        item.add_argument("workload_id")
        if action in {"apply", "rollback"}:
            item.add_argument("--confirm", default="", help="exact workload ID confirmation")

    operation = commands.add_parser("operation", help="durable operation status and recovery")
    operation_sub = operation.add_subparsers(dest="operation_command", required=True, parser_class=ArgusArgumentParser)
    for action in ("show", "recover"):
        item = leaf(
            operation_sub,
            action,
            help_text=f"{action} a durable operation",
            contract=description(
                f"{action.title()} a durable operation without guessing current authority.",
                "server mutation with exact confirmation" if action == "recover" else "server read-only",
                "exact operation ID and compatible durable ledger",
                "none for show; recovery requires the final reviewed confirmation",
                "state, authority, retry safety, and typed recovery",
                f"argus operation {action} 00000000-0000-0000-0000-000000000000 --json",
                "inspect operation state and follow only its typed runbook",
            ),
        )
        item.add_argument("operation_id")
        if action == "recover":
            item.add_argument("--confirm", default="", help="exact operation ID confirmation")

    leaf(
        commands,
        "doctor",
        help_text="report safe revision and protocol compatibility",
        contract=description("Report safe Argus compatibility state.", "unprivileged, read-only", "reviewed checkout", "none", "revision/schema/protocol summary without topology or credentials", "argus doctor --json", "follow the exact nextAction and reconcile versions before mutation"),
    )
    leaf(
        commands,
        "check",
        help_text="run the canonical repository validation",
        contract=description("Run the canonical deterministic repository validation.", "unprivileged, read-only", "supported Python and complete Git clone", "regenerates ignored local validation artifacts only", "pass/fail and sanitized output digest", "argus check --json", "run ./scripts/argus-check and fix its first named failure"),
    )

    legacy_workloads = commands.add_parser("workloads", help=argparse.SUPPRESS)
    legacy_workloads.add_argument("--json", action="store_true", dest="command_json")
    legacy_health = commands.add_parser("health", help=argparse.SUPPRESS)
    legacy_health.add_argument("--json", action="store_true", dest="command_json")
    legacy_plan = commands.add_parser("migration-plan", help=argparse.SUPPRESS)
    legacy_plan.add_argument("workload_id")
    legacy_plan.add_argument("--json", action="store_true", dest="command_json")
    return parser


def validate_id(value: str, *, operation: bool = False) -> bool:
    return bool((OPERATION_ID if operation else SAFE_ID).fullmatch(value))


def dispatch(args: argparse.Namespace, repo: Path, runner: Runner) -> tuple[dict[str, Any], str]:
    deprecation = ""
    command = args.command
    if command == "workloads":
        command = "workload"
        args.workload_command = "list"
        deprecation = "argus workloads is deprecated; use argus workload list"
    elif command == "health":
        command = "estate"
        args.estate_command = "status"
        deprecation = "argus health is deprecated; use argus estate status"
    elif command == "migration-plan":
        command = "workload"
        args.workload_command = "move"
        args.move_command = "preview"
        deprecation = "argus migration-plan is deprecated; use argus workload move preview"
    if command == "dashboard":
        result = dashboard_url(repo)
    elif command == "estate":
        result = estate_command(repo, args.estate_command)
    elif command == "workload" and args.workload_command == "list":
        result = workload_list(repo)
    elif command == "workload" and args.workload_command == "show":
        result = workload_show(repo, args.workload_id) if validate_id(args.workload_id) else _error("workload-id-invalid", "The workload ID is invalid.", "Run argus workload list.", exit_code=EXIT_INVOCATION)
    elif command == "workload" and args.workload_command == "move":
        result = move_command(repo, args.move_command, args.workload_id, getattr(args, "confirm", "")) if validate_id(args.workload_id) else _error("workload-id-invalid", "The workload ID is invalid.", "Run argus workload list.", exit_code=EXIT_INVOCATION)
    elif command == "operation" and args.operation_command == "show":
        result = operation_show(repo, args.operation_id) if validate_id(args.operation_id, operation=True) else _error("operation-id-invalid", "The operation ID is invalid.", "Use the exact UUID from the initiating command.", exit_code=EXIT_INVOCATION)
    elif command == "operation" and args.operation_command == "recover":
        result = operation_recover(args.operation_id, args.confirm) if validate_id(args.operation_id, operation=True) else _error("operation-id-invalid", "The operation ID is invalid.", "Use the exact UUID from the initiating command.", exit_code=EXIT_INVOCATION)
    elif command == "doctor":
        result = doctor_command(repo, runner)
    elif command == "check":
        result = check_command(repo, runner)
    else:  # pragma: no cover - argparse owns the grammar.
        result = _error("command-unsupported", "The command is unsupported.", "Run argus --help.", exit_code=EXIT_INVOCATION)
    if deprecation and result.get("ok"):
        result["data"]["deprecation"] = deprecation
    return result, deprecation


def render_human(result: dict[str, Any], stdout: TextIO, stderr: TextIO, deprecation: str) -> None:
    if deprecation:
        print(f"DEPRECATED {deprecation}", file=stderr)
    if not result["ok"]:
        error = result["error"]
        print(f"ERROR {error['code']}: {error['message']}", file=stderr)
        print(f"AUTHORITY {error['authority']} RETRY_SAFE {str(error['retrySafe']).lower()}", file=stderr)
        data = result.get("data")
        if isinstance(data, dict) and str(data.get("command", "")).startswith("workload.move."):
            print(
                f"MIGRATION_ID {data.get('migrationId') or 'none'} PHASE {data.get('phase', 'unknown')}",
                file=stderr,
            )
            print(f"STATUS {data.get('statusCommand', 'unavailable')}", file=stderr)
            print(f"RECOVERY {data.get('recoveryCommand', 'unavailable')}", file=stderr)
        print(f"NEXT {error['nextAction']}", file=stderr)
        return
    data = result["data"]
    command = data["command"]
    if command == "dashboard.url":
        print(f"CONFIGURED_URL {data['url']}", file=stdout)
        print(f"EFFECTIVE_STATE {data['effectiveState']}", file=stdout)
    elif command == "workload.list":
        for item in data["workloads"]:
            print(f"{item['id']}\t{item['trustDomain']}\t{item['migrationStatus']}", file=stdout)
    else:
        print(json.dumps(data, indent=2, sort_keys=True), file=stdout)


def run(
    argv: list[str],
    *,
    repo: Path,
    stdout: TextIO,
    stderr: TextIO,
    command_runner: Runner = default_runner,
) -> int:
    json_output = "--json" in argv
    try:
        args = build_parser().parse_args(argv)
    except CliInvocationError:
        result = _error(
            "invalid-invocation",
            "The command arguments are invalid.",
            "Run argus --help or the selected noun/verb --help.",
            exit_code=EXIT_INVOCATION,
        )
        if json_output:
            print(json.dumps({key: value for key, value in result.items() if key != "exitCode"}, sort_keys=True, separators=(",", ":")), file=stdout)
        else:
            render_human(result, stdout, stderr, "")
        return EXIT_INVOCATION
    json_output = args.json or getattr(args, "command_json", False)
    try:
        result, deprecation = dispatch(args, repo, command_runner)
    except Exception as exc:
        evidence_id = "sha256:" + hashlib.sha256(type(exc).__name__.encode("utf-8")).hexdigest()
        result = _error(
            "internal-error",
            "The command failed without a safe typed result.",
            "Run argus doctor --json and report the command plus repository revision; do not include private payloads.",
            exit_code=EXIT_INTERNAL,
            evidence_id=evidence_id,
        )
        deprecation = ""
    if json_output:
        print(json.dumps({key: value for key, value in result.items() if key != "exitCode"}, sort_keys=True, separators=(",", ":")), file=stdout)
    else:
        render_human(result, stdout, stderr, deprecation)
    return 0 if result["ok"] else int(result["exitCode"])


def main(argv: list[str] | None = None) -> int:
    override = os.environ.get("ARGUS_ROOT")
    repo = Path(override).expanduser().resolve() if override else Path(__file__).resolve().parents[1]
    return run(list(sys.argv[1:] if argv is None else argv), repo=repo, stdout=sys.stdout, stderr=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
