"""Durable, approval-gated migration planning and phase coordination.

This module deliberately owns no socket or subprocess transport.  A parent
migration only creates phase-specific child operations after its originating
dashboard session gives step-up approval; the existing operation worker then
dispatches those children through the capability-gated lifecycle broker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from argus_admission import canonical_records, evaluate_current
from argus_observations import (
    ObservationError,
    ObservationRepository,
    digest as observation_digest,
    load_registry,
)
from argus_operations import (
    MIGRATION_OPERATION_PHASES,
    OperationConflict,
    OperationLedger,
    OperationValidationError,
    digest,
    format_timestamp,
    parse_timestamp,
)
from argus_reconciliation import TERMINAL_CONTAINER_LIFECYCLES, reconcile


WORKLOAD_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
DRAFT_ID = re.compile(r"^draft-[0-9a-f-]{36}$")
DRAFT_SCHEMA_VERSION = 1
DRAFT_TTL_SECONDS = 15 * 60
MIGRATION_SCHEMA_VERSION = 1


class MigrationError(ValueError):
    """A stable, redacted migration planning refusal."""


def _now() -> int:
    return int(time.time())


def _clock() -> str | None:
    configured = os.environ.get("ARGUS_OBSERVATIONS_CLOCK", "").strip()
    return configured or None


def _regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_workload(root: Path, workload_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not WORKLOAD_ID.fullmatch(workload_id):
        raise MigrationError("workload ID is invalid")
    records = canonical_records(root, workload_id)
    workload = records.get("workload")
    classification = records.get("classification")
    manifest = records.get("manifest")
    if not isinstance(workload, dict) or not isinstance(classification, dict) or not isinstance(manifest, dict):
        raise MigrationError("canonical workload migration records are incomplete")
    return workload, classification, manifest


def _source_materialization(root: Path, workload_id: str) -> tuple[dict[str, Any], list[str]]:
    workload_root = root / "workloads" / workload_id
    template = workload_root / "compose.template.yml"
    target = workload_root / "source" / "docker-compose.yml"
    journal = (
        root
        / "runtime"
        / "argus"
        / "source-materialization"
        / workload_id
        / "latest.json"
    )
    blockers: list[str] = []
    if not _regular_file(template):
        blockers.append("source-template-unavailable")
    if not _regular_file(target):
        blockers.append("source-materialization-unverified")
    if not _regular_file(journal):
        blockers.append("source-materialization-journal-unavailable")
    if blockers:
        return {"state": "unverified"}, blockers
    try:
        template_digest = _file_digest(template)
        target_digest = _file_digest(target)
        record = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"state": "unverified"}, ["source-materialization-journal-invalid"]
    if (
        not isinstance(record, dict)
        or record.get("schemaVersion") != 1
        or record.get("state") != "materialized"
        or record.get("workloadId") != workload_id
        or record.get("targetPath") != str(target)
        or record.get("targetDigest") != target_digest
        or record.get("templateDigest") != template_digest
        or template_digest != target_digest
    ):
        return {"state": "unverified"}, ["source-materialization-unverified"]
    return {
        "state": "verified",
        "templateDigest": template_digest,
        "targetDigest": target_digest,
    }, []


def _stateless_contract(manifest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    backup = manifest.get("backup")
    if not isinstance(backup, dict):
        return {"state": "unknown"}, ["migration-backup-contract-invalid"]
    database = backup.get("database")
    named_volumes = backup.get("namedVolumes")
    bind_mounts = backup.get("bindMounts")
    blockers: list[str] = []
    if not isinstance(database, dict) or database.get("type") != "none":
        blockers.append("stateful-database-migration-not-eligible")
    if not isinstance(named_volumes, list) or named_volumes:
        blockers.append("named-volume-migration-not-eligible")
    if not isinstance(bind_mounts, list) or bind_mounts:
        blockers.append("bind-mount-migration-not-eligible")
    return {"state": "stateless" if not blockers else "stateful"}, blockers


def _container_records(repository: ObservationRepository, source_ids: list[str], project: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_id in source_ids:
        for record in repository.current_snapshot(source_id):
            if record.get("resourceKind") != "container":
                continue
            attributes = record.get("attributes")
            if (
                isinstance(attributes, dict)
                and attributes.get("project") == project
                and attributes.get("lifecycle") not in TERMINAL_CONTAINER_LIFECYCLES
            ):
                records.append(record)
    return records


def _observation_contract(
    root: Path,
    *,
    workload_id: str,
    project: str,
    source_domain: str,
    target_domain: str,
    observations_db: Path,
    explicit_clock: str | None,
) -> tuple[dict[str, Any], list[str]]:
    if not observations_db.is_file() or observations_db.is_symlink():
        return {"state": "unavailable", "evidenceDigest": ""}, ["observation-repository-unavailable"]
    try:
        registry = load_registry(root / "config" / "argus" / "observation-sources.json", root)
        with ObservationRepository(observations_db, read_only=True) as repository:
            reconciliation = reconcile(
                root,
                repository,
                registry,
                explicit_clock=explicit_clock,
            )
            coverage = reconciliation.get("coverage", {})
            source_states = {
                row.get("sourceId"): row.get("state")
                for row in coverage.get("sources", [])
                if isinstance(row, dict) and isinstance(row.get("sourceId"), str)
            }
            docker_sources = {
                domain: sorted(
                    source_id
                    for source_id, source in registry.sources.items()
                    if source.trust_domain == domain and "docker" in source.scope.lower()
                )
                for domain in {source_domain, target_domain}
            }
            source_ids = docker_sources[source_domain]
            target_ids = docker_sources[target_domain]
            blockers: list[str] = []
            if coverage.get("status") != "complete":
                blockers.append("configured-source-coverage-incomplete")
            if not source_ids or any(source_states.get(source_id) != "fresh" for source_id in source_ids):
                blockers.append("source-runtime-observation-unavailable")
            if not target_ids or any(source_states.get(source_id) != "fresh" for source_id in target_ids):
                blockers.append("target-runtime-observation-unavailable")
            source_records = _container_records(repository, source_ids, project) if not blockers else []
            target_records = _container_records(repository, target_ids, project) if not blockers else []
            foreign_records: list[dict[str, Any]] = []
            if not blockers:
                for source_id, source in registry.sources.items():
                    if source_id in {*source_ids, *target_ids} or "docker" not in source.scope.lower():
                        continue
                    if source_states.get(source_id) != "fresh":
                        continue
                    foreign_records.extend(_container_records(repository, [source_id], project))
            source_running = sum(
                isinstance(record.get("attributes"), dict)
                and record["attributes"].get("lifecycle") == "running"
                for record in source_records
            )
            if not blockers and (not source_records or source_running != len(source_records)):
                blockers.append("source-runtime-not-proven-healthy")
            if not blockers and target_records:
                blockers.append("target-runtime-not-empty")
            if not blockers and foreign_records:
                blockers.append("runtime-placement-conflict")
            evidence = {
                "coverageStatus": coverage.get("status", "unavailable"),
                "registryDigest": coverage.get("registryDigest", ""),
                "source": {"sourceIds": source_ids, "runningContainers": source_running},
                "target": {"sourceIds": target_ids, "containerCount": len(target_records)},
                "foreignContainerCount": len(foreign_records),
            }
            evidence["evidenceDigest"] = observation_digest(evidence)
            return evidence, sorted(set(blockers))
    except (ObservationError, OSError, ValueError, json.JSONDecodeError):
        return {"state": "unavailable", "evidenceDigest": ""}, ["observation-evidence-invalid"]


def migration_preview(
    root: Path,
    ledger: OperationLedger,
    workload_id: str,
    *,
    observations_db: Path | None = None,
    explicit_clock: str | None = None,
) -> dict[str, Any]:
    """Return a non-mutating, fully bound parent-migration preview."""
    root = root.resolve()
    blockers: list[str] = []
    try:
        workload, classification, manifest = _canonical_workload(root, workload_id)
        admission = evaluate_current(root, workload_id, "migration.preflight")
    except (MigrationError, ValueError):
        payload = {
            "schemaVersion": MIGRATION_SCHEMA_VERSION,
            "workloadId": workload_id,
            "eligible": False,
            "blockers": ["canonical-migration-records-unavailable"],
            "retrySafe": True,
            "phase": "not-started",
            "currentAuthority": "unknown",
            "eligibleTargets": [],
            "observationDigest": "",
        }
        return {**payload, "previewDigest": digest(payload)}

    target = classification.get("trustDomain")
    migration = manifest.get("migration", {})
    seeded_source = migration.get("runtimeTrustDomain") if isinstance(migration, dict) else None
    source = seeded_source if isinstance(seeded_source, str) and seeded_source else target
    if not isinstance(target, str) or not target:
        blockers.append("canonical-target-unavailable")
        target = ""
    if not isinstance(source, str) or not source:
        blockers.append("runtime-source-unavailable")
        source = ""
    if source and target:
        try:
            source = ledger.runtime_domain(workload_id, source)
        except (OperationValidationError, ValueError, OSError):
            blockers.append("runtime-authority-unavailable")
    if target and not target.endswith("-managed"):
        blockers.append("target-is-not-managed")
    if source == target:
        blockers.append("workload-already-in-target-domain")
    if not admission.allowed:
        blockers.append(f"admission-{admission.decision_code}")

    runtime = workload.get("runtime", {})
    project = runtime.get("composeProject") if isinstance(runtime, dict) else ""
    if not isinstance(project, str) or not project:
        blockers.append("compose-project-unavailable")
    materialization, materialization_blockers = _source_materialization(root, workload_id)
    blockers.extend(materialization_blockers)
    stateless, stateless_blockers = _stateless_contract(manifest)
    blockers.extend(stateless_blockers)
    database = observations_db or Path(
        os.environ.get("ARGUS_OBSERVATIONS_DB", root / "runtime" / "argus" / "observations.sqlite3")
    )
    observation: dict[str, Any] = {"state": "unavailable", "evidenceDigest": ""}
    if source and target and project:
        observation, observation_blockers = _observation_contract(
            root,
            workload_id=workload_id,
            project=project,
            source_domain=source,
            target_domain=target,
            observations_db=database,
            explicit_clock=explicit_clock if explicit_clock is not None else _clock(),
        )
        blockers.extend(observation_blockers)
    else:
        blockers.append("runtime-observation-unavailable")

    payload = {
        "schemaVersion": MIGRATION_SCHEMA_VERSION,
        "workloadId": workload_id,
        "sourceTrustDomain": source,
        "targetTrustDomain": target,
        "currentAuthority": source or "unknown",
        "eligibleTargets": [target] if target and not blockers else [],
        "eligible": not blockers,
        "blockers": sorted(set(blockers)),
        "expectedRevision": admission.revision,
        "policyVersion": admission.policy_version,
        "observationDigest": str(observation.get("evidenceDigest", "")),
        "sourceMaterialization": materialization,
        "statelessContract": stateless,
        "observation": observation,
        "retrySafe": True,
        "phase": "not-started",
        "confirmationPhrase": (
            f"migrate {workload_id} to {target}" if target else ""
        ),
        "rollbackConfirmationPhrase": f"rollback migration {workload_id}",
    }
    return {**payload, "previewDigest": digest(payload)}


def fresh_preview_matches(
    root: Path,
    ledger: OperationLedger,
    migration: dict[str, Any],
    *,
    observations_db: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    preview = migration_preview(
        root,
        ledger,
        str(migration["workload_id"]),
        observations_db=observations_db,
    )
    expected = {
        "previewDigest": migration.get("preview_digest"),
        "expectedRevision": migration.get("expected_revision"),
        "policyVersion": migration.get("policy_version"),
        "observationDigest": migration.get("observation_digest"),
        "sourceTrustDomain": migration.get("source_trust_domain"),
        "targetTrustDomain": migration.get("target_trust_domain"),
    }
    return (
        bool(preview.get("eligible"))
        and all(preview.get(key) == value for key, value in expected.items()),
        preview,
    )


def public_migration(migration: dict[str, Any]) -> dict[str, Any]:
    """Remove the session binding and return bounded parent/child state."""
    children = migration.get("children", [])
    safe_children = []
    for child in children if isinstance(children, list) else []:
        if not isinstance(child, dict):
            continue
        safe_children.append(
            {
                key: child.get(key)
                for key in (
                    "operation_id",
                    "operation_type",
                    "trust_domain",
                    "phase",
                    "state",
                    "created_at",
                    "started_at",
                    "finished_at",
                    "error_class",
                    "redacted_summary",
                )
            }
        )
    return {
        "migrationId": migration.get("migration_id"),
        "workloadId": migration.get("workload_id"),
        "sourceTrustDomain": migration.get("source_trust_domain"),
        "targetTrustDomain": migration.get("target_trust_domain"),
        "phase": migration.get("phase"),
        "createdAt": migration.get("created_at"),
        "approvedAt": migration.get("approved_at"),
        "updatedAt": migration.get("updated_at"),
        "finishedAt": migration.get("finished_at"),
        "errorClass": migration.get("error_class"),
        "summary": migration.get("redacted_summary"),
        "previewDigest": migration.get("preview_digest"),
        "expectedRevision": migration.get("expected_revision"),
        "policyVersion": migration.get("policy_version"),
        "observationDigest": migration.get("observation_digest"),
        "preview": migration.get("preview"),
        "children": safe_children,
    }


def _draft_directory(root: Path) -> Path:
    return root / "runtime" / "argus" / "migration-drafts"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_draft(
    root: Path,
    preview: dict[str, Any],
    *,
    action: str,
    migration_id: str | None = None,
    clock: int | None = None,
) -> dict[str, Any]:
    """Create a 15-minute inert CLI draft; this never grants authority."""
    if action not in {"apply", "rollback"}:
        raise MigrationError("migration draft action is invalid")
    if not preview.get("eligible"):
        raise MigrationError("migration preview is not eligible for a draft")
    workload_id = preview.get("workloadId")
    source = preview.get("sourceTrustDomain")
    target = preview.get("targetTrustDomain")
    if not all(isinstance(value, str) and value for value in (workload_id, source, target)):
        raise MigrationError("migration draft preview is incomplete")
    if action == "rollback" and (
        not isinstance(migration_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", migration_id)
    ):
        raise MigrationError("rollback draft requires an active migration")
    directory = _draft_directory(root.resolve())
    if directory.exists() or directory.is_symlink():
        if directory.is_symlink() or not directory.is_dir():
            raise MigrationError("migration draft directory is invalid")
    else:
        directory.mkdir(mode=0o700, parents=True)
    if directory.is_symlink() or not directory.is_dir():
        raise MigrationError("migration draft directory is invalid")
    current = _now() if clock is None else int(clock)
    draft_id = f"draft-{uuid.uuid4()}"
    payload = {
        "schemaVersion": DRAFT_SCHEMA_VERSION,
        "draftId": draft_id,
        "action": action,
        "workloadId": workload_id,
        "sourceTrustDomain": source,
        "targetTrustDomain": target,
        "previewDigest": preview.get("previewDigest"),
        "expectedRevision": preview.get("expectedRevision"),
        "policyVersion": preview.get("policyVersion"),
        "observationDigest": preview.get("observationDigest"),
        "migrationId": migration_id or "",
        "createdAt": format_timestamp(current),
        "expiresAt": format_timestamp(current + DRAFT_TTL_SECONDS),
        "authority": "none",
    }
    _atomic_json(directory / f"{draft_id}.json", payload)
    return payload


def read_draft(root: Path, draft_id: str, *, clock: int | None = None) -> dict[str, Any] | None:
    if not DRAFT_ID.fullmatch(draft_id):
        return None
    path = _draft_directory(root.resolve()) / f"{draft_id}.json"
    if not _regular_file(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    required = {
        "schemaVersion", "draftId", "action", "workloadId", "sourceTrustDomain",
        "targetTrustDomain", "previewDigest", "expectedRevision", "policyVersion",
        "observationDigest", "migrationId", "createdAt", "expiresAt", "authority",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or payload.get("schemaVersion") != DRAFT_SCHEMA_VERSION
        or payload.get("draftId") != draft_id
        or payload.get("action") not in {"apply", "rollback"}
        or payload.get("authority") != "none"
        or not all(isinstance(payload.get(name), str) for name in required - {"schemaVersion"})
    ):
        return None
    try:
        expired = parse_timestamp(str(payload["expiresAt"])) <= (_now() if clock is None else int(clock))
    except (TypeError, ValueError):
        return None
    return {**payload, "state": "expired" if expired else "drafted"}


class MigrationCoordinator:
    """Advance durable parents only from persisted child operation outcomes."""

    _automatic_transitions = {
        "source-fenced": "target-preparing",
        "target-verified": "route-switching",
        "authority-committed": "canonical-committed",
        "canonical-committed": "verifying",
    }
    _child_success_transitions = {
        "source-fencing": "source-fenced",
        "target-preparing": "target-starting",
        "target-starting": "target-verified",
        "route-switching": "authority-committed",
        "verifying": "succeeded",
        "rollback-target-stopping": "rollback-source-restoring",
        "rollback-source-restoring": "rollback-verifying",
        "rollback-verifying": "rolled-back",
    }

    def __init__(
        self,
        root: Path,
        ledger: OperationLedger,
        *,
        observations_db: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.ledger = ledger
        self.observations_db = observations_db

    def _transition(
        self,
        migration: dict[str, Any],
        phase: str,
        *,
        event_detail: str,
        **fields: Any,
    ) -> None:
        self.ledger.transition_migration(
            str(migration["migration_id"]),
            {str(migration["phase"])},
            phase,
            event_detail=event_detail,
            **fields,
        )

    def _child(self, migration: dict[str, Any]) -> dict[str, Any] | None:
        phase = str(migration["phase"])
        for child in migration.get("children", []):
            if isinstance(child, dict) and child.get("phase") == phase:
                return child
        return None

    def _start_phase(self, migration: dict[str, Any]) -> str:
        if str(migration["phase"]) == "source-fencing":
            fresh, preview = fresh_preview_matches(
                self.root,
                self.ledger,
                migration,
                observations_db=self.observations_db,
            )
            if not fresh:
                self._transition(
                    migration,
                    "failed",
                    event_detail="No child was queued because approval-bound migration evidence changed.",
                    error_class="preflight-stale",
                    redacted_summary="Migration evidence changed after approval; no source action was started.",
                )
                return "failed-preflight"
        self.ledger.ensure_migration_child(str(migration["migration_id"]))
        return "child-queued"

    def _handle_child(self, migration: dict[str, Any], child: dict[str, Any]) -> str:
        phase = str(migration["phase"])
        state = str(child.get("state", ""))
        if state in {"queued", "running"}:
            return "child-pending"
        if state == "succeeded":
            next_phase = self._child_success_transitions[phase]
            self._transition(
                migration,
                next_phase,
                event_detail="The phase-specific child completed with a durable result.",
            )
            return next_phase
        if state == "indeterminate":
            self._transition(
                migration,
                "indeterminate",
                event_detail="Child acknowledgement or outcome was not provable; no retry was scheduled.",
                error_class="child-indeterminate",
                redacted_summary="Migration outcome requires manual reconciliation; no automatic retry was attempted.",
            )
            return "indeterminate"
        if phase.startswith("rollback-"):
            self._transition(
                migration,
                "indeterminate",
                event_detail="Rollback child did not prove exactly one healthy placement.",
                error_class="rollback-child-failed",
                redacted_summary="Rollback could not prove a safe placement; manual reconciliation is required.",
            )
            return "indeterminate"
        if phase == "source-fencing":
            self._transition(
                migration,
                "failed",
                event_detail="Source fence failed while the source remained the authority.",
                error_class="source-fence-failed",
                redacted_summary="Source fence was not proven; no target action was scheduled.",
            )
            return "failed"
        self._transition(
            migration,
            "rollback-target-stopping",
            event_detail="A known child failure entered the fenced rollback sequence.",
            error_class="phase-child-failed",
            redacted_summary="A migration phase failed; fenced rollback is restoring the proven source.",
        )
        return "rollback-started"

    def advance(self, migration_id: str) -> str:
        migration = self.ledger.get_migration(migration_id)
        if migration is None:
            return "missing"
        phase = str(migration["phase"])
        if phase == "awaiting-approval":
            return "awaiting-approval"
        if phase in self._automatic_transitions:
            next_phase = self._automatic_transitions[phase]
            self._transition(
                migration,
                next_phase,
                event_detail="Durable parent advanced without a new authority grant.",
            )
            return next_phase
        if phase in MIGRATION_OPERATION_PHASES:
            child = self._child(migration)
            return self._start_phase(migration) if child is None else self._handle_child(migration, child)
        return phase

    def run_once(self) -> dict[str, int]:
        outcome = {"advanced": 0, "pending": 0, "indeterminate": 0}
        for migration in self.ledger.list_active_migrations():
            try:
                result = self.advance(str(migration["migration_id"]))
            except (OperationConflict, OSError, ValueError):
                # A competing transaction or temporary durable-store/evidence
                # problem must leave the parent untouched for the next pass.
                outcome["pending"] += 1
                continue
            if result == "indeterminate":
                outcome["indeterminate"] += 1
            elif result in {"awaiting-approval", "child-pending", "child-queued"}:
                outcome["pending"] += 1
            else:
                outcome["advanced"] += 1
        return outcome
