"""Read-only admission and Docker Compose drift diagnostics."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from argus_legacy import CommandRunner, docker_containers
from argus_observations import (
    ObservationError,
    ObservationRepository,
    SourceRegistry,
    canonical_bytes,
    digest,
    load_registry,
)
from argus_state import Classification, StateError


DOCTOR_SCHEMA_VERSION = 1
FINDING_CODES = {
    "unknown-runtime",
    "missing-runtime",
    "project-name-drift",
    "revision-drift",
    "classification-drift",
    "observation-unavailable",
}
LEGACY_SOURCE_ID = "oreochiserver.legacy-rootful-docker"
LEGACY_TRUST_DOMAIN = "legacy-rootful"
LegacyCollector = Callable[[], tuple[list[dict[str, Any]], list[str]]]


class AdmissionDoctorError(ValueError):
    """Raised when canonical diagnostic inputs are malformed."""


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AdmissionDoctorError(f"canonical diagnostic input is unavailable: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionDoctorError(f"canonical diagnostic input is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise AdmissionDoctorError(f"canonical diagnostic input is not an object: {path.name}")
    return value


def _clock(clock: str | None) -> tuple[str, int]:
    if clock is None:
        clock = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        epoch = int(datetime.strptime(clock, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError as exc:
        raise AdmissionDoctorError("doctor clock must be canonical UTC time") from exc
    return clock, epoch


def _runtime_tuple(value: dict[str, Any], *, manifest: bool) -> tuple[str, str, str, str]:
    runtime = value.get("runtime")
    if not isinstance(runtime, dict):
        return "", "", "", ""
    if manifest:
        compose = runtime.get("compose")
        if not isinstance(compose, dict):
            return str(runtime.get("type", "")), "", "", ""
        return (
            str(runtime.get("type", "")),
            str(compose.get("path", "")),
            str(compose.get("project", "")),
            str(compose.get("service", "")),
        )
    return (
        str(runtime.get("type", "")),
        str(runtime.get("composePath", "")),
        str(runtime.get("composeProject", "")),
        str(runtime.get("service", "")),
    )


def _canonical(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    workload_payload = _load(root / "config" / "workloads.json")
    classification_payload = _load(root / "config" / "argus" / "workload-classification.json")
    workloads = workload_payload.get("workloads")
    classifications = classification_payload.get("workloads")
    if not isinstance(workloads, list) or not isinstance(classifications, dict):
        raise AdmissionDoctorError("canonical workload or classification registry is malformed")
    if not all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] for item in workloads):
        raise AdmissionDoctorError("canonical workload registry is malformed")
    ids = [item["id"] for item in workloads]
    if len(ids) != len(set(ids)) or not all(isinstance(classifications.get(item), dict) for item in ids):
        raise AdmissionDoctorError("canonical workload identities are incomplete or duplicated")
    return sorted(workloads, key=lambda item: item["id"]), classifications


def _runtime_quarantine(root: Path, canonical_ids: set[str]) -> set[str]:
    payload = _load(root / "config" / "argus" / "runtime-quarantine.json")
    records = payload.get("runtimes")
    if (
        payload.get("schemaVersion") != 1
        or payload.get("sourceKind") != "docker-compose"
        or payload.get("sourceTrustDomain") != LEGACY_TRUST_DOMAIN
        or payload.get("defaultDisposition") != "review-required"
        or not isinstance(records, dict)
    ):
        raise AdmissionDoctorError("runtime quarantine registry is malformed")
    expected = {
        "lifecycle": "observed",
        "admission": "denied",
        "access": "none",
        "publicExposure": False,
    }
    quarantined: set[str] = set()
    for project, record in records.items():
        if (
            not isinstance(project, str)
            or not project
            or not isinstance(record, dict)
            or any(record.get(key) != value for key, value in expected.items())
            or not isinstance(record.get("dispositionIssue"), int)
            or isinstance(record.get("dispositionIssue"), bool)
            or record["dispositionIssue"] < 1
            or set(record) != {*expected, "dispositionIssue"}
        ):
            raise AdmissionDoctorError("runtime quarantine registry is malformed")
        if project not in canonical_ids:
            quarantined.add(project)
    return quarantined


def _canonical_findings(
    root: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], set[str]]:
    workloads, classifications = _canonical(root)
    quarantined_projects = _runtime_quarantine(root, {item["id"] for item in workloads})
    findings: list[dict[str, Any]] = []
    projects: dict[str, dict[str, str]] = {}
    for workload in workloads:
        workload_id = workload["id"]
        registry_runtime = _runtime_tuple(workload, manifest=False)
        classification = classifications[workload_id]
        expected_domain = str(classification.get("trustDomain", ""))
        try:
            Classification(
                classification.get("realm"),
                classification.get("zone"),
                classification.get("stage"),
                expected_domain,
                "workload",
            ).validate()
        except StateError:
            findings.append({"code": "classification-drift", "workloadId": workload_id, "fields": ["canonicalClassification"]})
        if expected_domain != f"{classification.get('realm', '')}-{classification.get('zone', '')}":
            findings.append({"code": "classification-drift", "workloadId": workload_id, "fields": ["trustDomainBinding"]})
        if classification.get("status") != "classified" or classification.get("admission") not in {"allowed", "denied"}:
            findings.append({"code": "classification-drift", "workloadId": workload_id, "fields": ["classificationState"]})
        manifest_path = root / "workloads" / workload_id / "manifest.json"
        try:
            manifest = _load(manifest_path)
        except AdmissionDoctorError:
            findings.append({"code": "revision-drift", "workloadId": workload_id, "fields": ["manifest"]})
            project = registry_runtime[2]
            if project:
                if project in projects:
                    findings.append({"code": "project-name-drift", "workloadId": workload_id, "registryProject": project, "manifestProject": ""})
                else:
                    projects[project] = {"workloadId": workload_id, "trustDomain": expected_domain}
            continue
        identity_drift = [
            field
            for field, actual, expected in (
                ("manifestId", manifest.get("id"), workload_id),
                ("schemaVersion", manifest.get("schemaVersion"), 1),
                ("canonicalRoot", manifest.get("canonicalRoot"), f"/srv/argus/workloads/{workload_id}"),
                ("sourcePath", manifest.get("sourcePath"), f"/srv/argus/workloads/{workload_id}/source"),
            )
            if actual != expected
        ]
        if identity_drift:
            findings.append({"code": "revision-drift", "workloadId": workload_id, "fields": identity_drift})
        manifest_runtime = _runtime_tuple(manifest, manifest=True)
        if registry_runtime[2] != manifest_runtime[2]:
            findings.append({
                "code": "project-name-drift",
                "workloadId": workload_id,
                "registryProject": registry_runtime[2],
                "manifestProject": manifest_runtime[2],
            })
        differing = [
            field
            for field, left, right in zip(
                ("runtimeType", "composePath", "composeProject", "service"),
                registry_runtime,
                manifest_runtime,
            )
            if left != right
        ]
        if differing:
            findings.append({"code": "revision-drift", "workloadId": workload_id, "fields": differing})
        migration = manifest.get("migration", {})
        manifest_domain = str(migration.get("targetTrustDomain", "")) if isinstance(migration, dict) else ""
        if registry_runtime[0] == "docker-compose" and manifest_domain != expected_domain:
            findings.append({
                "code": "classification-drift",
                "workloadId": workload_id,
                "expectedTrustDomain": expected_domain,
                "manifestTrustDomain": manifest_domain,
            })
        workload_migration = workload.get("migration", {})
        workload_domain = str(workload_migration.get("targetTrustDomain", "")) if isinstance(workload_migration, dict) else ""
        if registry_runtime[0] == "docker-compose" and workload_domain != expected_domain:
            findings.append({
                "code": "classification-drift",
                "workloadId": workload_id,
                "expectedTrustDomain": expected_domain,
                "workloadTrustDomain": workload_domain,
            })
        project = registry_runtime[2]
        if project:
            if project in projects:
                findings.append({"code": "project-name-drift", "workloadId": workload_id, "registryProject": project, "manifestProject": project})
            projects[project] = {"workloadId": workload_id, "trustDomain": expected_domain}
    return findings, projects, quarantined_projects


def _observation_findings(
    repository: ObservationRepository,
    registry: SourceRegistry,
    projects: dict[str, dict[str, str]],
    quarantined_projects: set[str],
    *,
    clock_epoch: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    coverage = repository.coverage(registry, explicit_clock_epoch=clock_epoch)
    source_states: dict[str, str] = {}
    observed: dict[str, set[str]] = {}
    fresh_container_domains: set[str] = set()
    configured_container_sources = 0
    fresh_container_sources = 0
    container_domains: set[str] = set()
    observed_quarantined: set[str] = set()
    for source_row in coverage.get("sources", []):
        if not isinstance(source_row, dict):
            continue
        source_id = source_row.get("sourceId")
        state = source_row.get("state")
        if not isinstance(source_id, str) or source_id not in registry.sources or not isinstance(state, str):
            continue
        source = registry.sources[source_id]
        domain = source.trust_domain
        supports_containers = "container" in source.minimization.get("resourceKinds", [])
        if not supports_containers:
            continue
        configured_container_sources += 1
        source_states[source_id] = state
        container_domains.add(domain)
        if state == "fresh" and supports_containers:
            fresh_container_domains.add(domain)
            fresh_container_sources += 1
        if state != "fresh" or not supports_containers or not source_row.get("currentRunId"):
            continue
        for record in repository.current_snapshot(source_id):
            if record.get("resourceKind") != "container":
                continue
            attributes = record.get("attributes")
            project = attributes.get("project") if isinstance(attributes, dict) else None
            if isinstance(project, str) and project:
                observed.setdefault(project, set()).add(domain)

    findings: list[dict[str, Any]] = []
    for project, domains in sorted(observed.items()):
        canonical = projects.get(project)
        if canonical is None:
            if project in quarantined_projects and domains == {LEGACY_TRUST_DOMAIN}:
                observed_quarantined.add(project)
                continue
            findings.append({"code": "unknown-runtime", "runtimeProject": project, "observedTrustDomains": sorted(domains)})
            continue
        expected = canonical["trustDomain"]
        if any(domain != expected for domain in domains):
            findings.append({
                "code": "classification-drift",
                "workloadId": canonical["workloadId"],
                "expectedTrustDomain": expected,
                "observedTrustDomains": sorted(domains),
            })
    for project, canonical in sorted(projects.items()):
        expected = canonical["trustDomain"]
        if expected in fresh_container_domains and expected not in observed.get(project, set()):
            findings.append({"code": "missing-runtime", "workloadId": canonical["workloadId"], "runtimeProject": project})

    required_domains = {item["trustDomain"] for item in projects.values() if item["trustDomain"]}
    docker_complete = (
        configured_container_sources > 0
        and configured_container_sources == fresh_container_sources
        and required_domains.issubset(container_domains)
    )
    observation = {
        "status": "complete" if docker_complete else ("not-configured" if configured_container_sources == 0 else "incomplete"),
        "configuredSources": configured_container_sources,
        "freshSources": fresh_container_sources,
        "knownQuarantinedRuntimeCount": len(observed_quarantined),
        "registryDigest": coverage.get("registryDigest"),
        "sourceStates": [
            {"sourceId": source_id, "state": source_states[source_id]}
            for source_id in sorted(source_states)
        ],
    }
    return findings, observation


def _legacy_observation_findings(
    projects: dict[str, dict[str, str]],
    quarantined_projects: set[str],
    collector: LegacyCollector | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect the current rootful Compose view without persisting inventory.

    This is the issue-#326 server default: reuse the existing minimized legacy
    Docker inventory helper synchronously and keep its runtime socket read-only.
    The normalized repository remains available through explicit CLI paths for
    cross-domain diagnostics, but no collector daemon is required by the doctor.
    """

    containers, gaps = (collector or (lambda: docker_containers(CommandRunner())))()
    observed_projects = sorted({
        str(item.get("composeProject", ""))
        for item in containers
        if isinstance(item, dict) and str(item.get("composeProject", ""))
    })
    findings: list[dict[str, Any]] = []
    for project in observed_projects:
        canonical = projects.get(project)
        if canonical is None:
            if project in quarantined_projects:
                continue
            findings.append({
                "code": "unknown-runtime",
                "runtimeProject": project,
                "observedTrustDomains": [LEGACY_TRUST_DOMAIN],
            })
        elif canonical["trustDomain"] != LEGACY_TRUST_DOMAIN:
            findings.append({
                "code": "classification-drift",
                "workloadId": canonical["workloadId"],
                "expectedTrustDomain": canonical["trustDomain"],
                "observedTrustDomains": [LEGACY_TRUST_DOMAIN],
            })

    for project, canonical in sorted(projects.items()):
        if canonical["trustDomain"] == LEGACY_TRUST_DOMAIN and project not in observed_projects:
            findings.append({
                "code": "missing-runtime",
                "workloadId": canonical["workloadId"],
                "runtimeProject": project,
            })

    available = not gaps
    observation = {
        "status": "complete" if available else "incomplete",
        "configuredSources": 1,
        "freshSources": 1 if available else 0,
        "knownQuarantinedRuntimeCount": len(set(observed_projects) & quarantined_projects),
        "registryDigest": digest({
            "sourceId": LEGACY_SOURCE_ID,
            "trustDomain": LEGACY_TRUST_DOMAIN,
            "resourceKind": "container",
            "mode": "synchronous-read-only",
        }),
        "sourceStates": [{
            "sourceId": LEGACY_SOURCE_ID,
            "state": "fresh" if available else "failed",
        }],
    }
    return findings, observation


def report(
    root: Path,
    database: Path | None = None,
    registry_path: Path | None = None,
    *,
    clock: str | None = None,
    legacy_collector: LegacyCollector | None = None,
) -> dict[str, Any]:
    """Build one deterministic report without modifying canonical or runtime state."""
    root = root.expanduser().resolve()
    evaluated_at, clock_epoch = _clock(clock)
    canonical_findings, projects, quarantined_projects = _canonical_findings(root)
    findings = list(canonical_findings)
    observation: dict[str, Any]
    if database is None:
        if registry_path is not None:
            raise AdmissionDoctorError("an observation registry requires an explicit database")
        try:
            observed_findings, observation = _legacy_observation_findings(
                projects,
                quarantined_projects,
                legacy_collector,
            )
            findings.extend(observed_findings)
            if observation.get("status") != "complete":
                findings.append({"code": "observation-unavailable"})
        except (OSError, ValueError):
            findings.append({"code": "observation-unavailable"})
            observation = {"status": "unavailable", "configuredSources": 1, "freshSources": 0, "knownQuarantinedRuntimeCount": 0, "registryDigest": None, "sourceStates": []}
    elif registry_path is None or not database.is_file() or not registry_path.is_file():
        findings.append({"code": "observation-unavailable"})
        observation = {"status": "unavailable", "configuredSources": 0, "freshSources": 0, "knownQuarantinedRuntimeCount": 0, "registryDigest": None, "sourceStates": []}
    else:
        try:
            registry = load_registry(registry_path, root)
            with ObservationRepository(database, read_only=True) as repository:
                repository.connection.execute("BEGIN")
                try:
                    observed_findings, observation = _observation_findings(
                        repository,
                        registry,
                        projects,
                        quarantined_projects,
                        clock_epoch=clock_epoch,
                    )
                finally:
                    repository.connection.rollback()
            findings.extend(observed_findings)
            if observation.get("status") != "complete":
                findings.append({"code": "observation-unavailable"})
        except (ObservationError, OSError, ValueError, sqlite3.Error):
            findings.append({"code": "observation-unavailable"})
            observation = {"status": "unavailable", "configuredSources": 0, "freshSources": 0, "knownQuarantinedRuntimeCount": 0, "registryDigest": None, "sourceStates": []}

    unique = {json.dumps(item, sort_keys=True): item for item in findings}
    findings = sorted(unique.values(), key=canonical_bytes)
    if any(item.get("code") not in FINDING_CODES for item in findings):
        raise AdmissionDoctorError("doctor emitted an unknown finding code")
    value = {
        "schemaVersion": DOCTOR_SCHEMA_VERSION,
        "ok": not findings,
        "evaluatedAt": evaluated_at,
        "observationState": observation,
        "findings": findings,
        "findingCounts": {code: sum(item.get("code") == code for item in findings) for code in sorted(FINDING_CODES)},
        "mutationAuthority": "none",
        "actionsTaken": [],
        "adoptionPerformed": False,
    }
    value["evidenceDigest"] = digest(value)
    return value


def default_database(root: Path) -> Path | None:
    configured = os.environ.get("ARGUS_OBSERVATIONS_DB")
    return Path(configured).expanduser().resolve() if configured else None
