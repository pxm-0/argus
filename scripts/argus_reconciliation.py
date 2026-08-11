"""Read-only reconciliation of normalized observations to canonical workloads."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argus_observations import ObservationError, ObservationRepository, SourceRegistry, canonical_bytes, digest


RECONCILIATION_SCHEMA_VERSION = 1
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
WORKLOAD_STATES = {"known", "unknown", "stale", "conflicting", "failed", "incomplete"}
SOURCE_STATES = {"never_observed", "fresh", "stale", "failed", "excluded"}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ObservationError(f"{path.name} must contain an object")
    return payload


def _workloads(root: Path) -> list[dict[str, str]]:
    workload_payload = _load_json(root / "config" / "workloads.json")
    classification_payload = _load_json(root / "config" / "argus" / "workload-classification.json")
    raw_workloads = workload_payload.get("workloads")
    classifications = classification_payload.get("workloads")
    if not isinstance(raw_workloads, list) or not isinstance(classifications, dict):
        raise ObservationError("canonical workload registry is malformed")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_workloads:
        if not isinstance(item, dict):
            raise ObservationError("canonical workload registry contains a non-object")
        workload_id = item.get("id")
        runtime = item.get("runtime", {})
        classification = classifications.get(workload_id)
        if (
            not isinstance(workload_id, str)
            or SAFE_ID.fullmatch(workload_id) is None
            or workload_id in seen
            or not isinstance(runtime, dict)
            or not isinstance(classification, dict)
        ):
            raise ObservationError("canonical workload identity is malformed")
        project = runtime.get("composeProject", "")
        trust_domain = classification.get("trustDomain")
        if not isinstance(project, str) or (project and PROJECT_ID.fullmatch(project) is None):
            raise ObservationError("canonical compose project identity is malformed")
        if not isinstance(trust_domain, str) or not trust_domain:
            raise ObservationError("canonical workload trust domain is malformed")
        seen.add(workload_id)
        result.append({"id": workload_id, "project": project, "trustDomain": trust_domain})
    return sorted(result, key=lambda item: item["id"])


def _clock_epoch(explicit_clock: str | None) -> int:
    if explicit_clock is None:
        explicit_clock = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        return int(datetime.strptime(explicit_clock, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError as exc:
        raise ObservationError("reconciliation clock must be canonical UTC time") from exc


def _gap_rows(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = coverage.get("gaps", [])
    if not isinstance(rows, list):
        raise ObservationError("observation coverage gaps are malformed")
    return [row for row in rows if isinstance(row, dict)]


def _source_evidence(
    repository: ObservationRepository,
    registry: SourceRegistry,
    coverage: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    gaps = _gap_rows(coverage)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for gap in gaps:
        source_id = gap.get("sourceId")
        if isinstance(source_id, str):
            by_source.setdefault(source_id, []).append(gap)
    rows: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    for source_row in coverage.get("sources", []):
        source_id = source_row.get("sourceId")
        state = source_row.get("state")
        if not isinstance(source_id, str) or state not in SOURCE_STATES or source_id not in registry.sources:
            raise ObservationError("observation source coverage is malformed")
        run_id = source_row.get("currentRunId") or source_row.get("latestRunId")
        run = repository.run_result(run_id) if isinstance(run_id, str) else None
        evidence_digest = run.get("snapshotDigest") if run else None
        source_gaps = sorted(by_source.get(source_id, []), key=canonical_bytes)
        row = {
            "sourceId": source_id,
            "trustDomain": registry.sources[source_id].trust_domain,
            "state": state,
            "currentRunId": source_row.get("currentRunId"),
            "latestRunId": source_row.get("latestRunId"),
            "evidenceDigest": evidence_digest,
            "gapDigest": digest(source_gaps),
        }
        rows[source_id] = row
        if state in {"stale", "failed", "never_observed", "excluded"}:
            blockers.append({"code": f"source-{state.replace('_', '-')}", "sourceId": source_id})
        for gap in source_gaps:
            code = gap.get("kind")
            if isinstance(code, str):
                blockers.append({"code": code, "sourceId": source_id})
    for gap in gaps:
        if gap.get("kind") == "configuration-gap" and not isinstance(gap.get("sourceId"), str):
            blockers.append({"code": "configuration-gap", "trustDomain": gap.get("trustDomain", "")})
    return rows, blockers


def _candidate_records(
    repository: ObservationRepository,
    source_id: str,
    source_state: str,
) -> list[dict[str, str]]:
    if source_state not in {"fresh", "stale", "failed"}:
        return []
    try:
        records = repository.current_snapshot(source_id)
    except ObservationError:
        return []
    candidates: list[dict[str, str]] = []
    for record in records:
        if record.get("resourceKind") != "container":
            continue
        attributes = record.get("attributes")
        if not isinstance(attributes, dict):
            continue
        project = attributes.get("project")
        if isinstance(project, str) and PROJECT_ID.fullmatch(project):
            candidates.append({"project": project, "sourceId": source_id})
    return candidates


def reconcile(
    root: Path,
    repository: ObservationRepository,
    registry: SourceRegistry,
    *,
    explicit_clock: str | None = None,
) -> dict[str, Any]:
    """Return sanitized evidence state; this function has no mutation authority."""
    coverage = repository.coverage(registry, explicit_clock_epoch=_clock_epoch(explicit_clock))
    source_rows, blockers = _source_evidence(repository, registry, coverage)
    canonical = _workloads(root)
    candidates: list[dict[str, str]] = []
    for source_id in sorted(source_rows):
        candidates.extend(_candidate_records(repository, source_id, source_rows[source_id]["state"]))

    workload_rows: list[dict[str, Any]] = []
    for item in canonical:
        matches = [candidate for candidate in candidates if candidate["project"] == item["project"]]
        source_ids = sorted({candidate["sourceId"] for candidate in matches})
        domains = sorted({source_rows[source_id]["trustDomain"] for source_id in source_ids})
        states = sorted({source_rows[source_id]["state"] for source_id in source_ids})
        relevant_states = sorted({
            row["state"]
            for row in source_rows.values()
            if row["trustDomain"] == item["trustDomain"]
        })
        row_blockers: list[dict[str, Any]] = []
        if len(domains) > 1 or any(domain != item["trustDomain"] for domain in domains):
            state = "conflicting"
            row_blockers.append({"code": "identity-conflict"})
        elif "failed" in states:
            state = "failed"
            row_blockers.append({"code": "source-collection-failed"})
        elif "stale" in states:
            state = "stale"
            row_blockers.append({"code": "source-stale"})
        elif "failed" in relevant_states:
            state = "failed"
            row_blockers.append({"code": "source-collection-failed"})
        elif "stale" in relevant_states:
            state = "stale"
            row_blockers.append({"code": "source-stale"})
        elif matches:
            state = "known"
        elif coverage["status"] != "complete":
            state = "incomplete"
            row_blockers.append({"code": "configured-source-coverage-incomplete"})
        else:
            state = "unknown"
            row_blockers.append({"code": "workload-identity-unknown"})
        if state != "known":
            blockers.extend({"code": entry["code"], "workloadId": item["id"]} for entry in row_blockers)
        evidence_digests = sorted({source_rows[source_id]["evidenceDigest"] for source_id in source_ids if source_rows[source_id]["evidenceDigest"]})
        workload_rows.append({
            "id": item["id"],
            "trustDomain": item["trustDomain"],
            "state": state,
            "matchedSourceIds": source_ids,
            "evidenceDigests": evidence_digests,
            "blockers": row_blockers,
        })

    blockers = sorted({json.dumps(item, sort_keys=True): item for item in blockers}.values(), key=canonical_bytes)
    safe = coverage["status"] == "complete" and all(row["state"] == "known" for row in workload_rows) and not blockers
    summary = {
        "schemaVersion": RECONCILIATION_SCHEMA_VERSION,
        "status": "complete" if safe else "incomplete",
        "observationState": "complete" if safe else "incomplete",
        "coverage": {
            "status": coverage["status"],
            "configuredSources": coverage["configuredSources"],
            "freshSources": coverage["freshSources"],
            "registryDigest": coverage["registryDigest"],
            "sources": [source_rows[key] for key in sorted(source_rows)],
            "gapDigest": digest(_gap_rows(coverage)),
        },
        "workloads": workload_rows,
        "blockers": blockers,
        "safeToMoveWorkloads": safe,
        "mutationAuthority": "none",
    }
    summary["evidenceDigest"] = digest(summary)
    return summary
