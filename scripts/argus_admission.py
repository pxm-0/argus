from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus_state import Classification, StateError


CANONICAL_RECORD_ORDER = (
    "workload",
    "policy",
    "access",
    "privacy",
    "classification",
    "route",
    "manifest",
)

DECISION_CODES = {
    "allowed",
    "unknown-workload",
    "manifest-invalid",
    "operation-not-capable",
    "classification-incomplete",
    "admission-denied",
    "legacy-domain-denied",
    "target-mismatch",
    "revision-stale",
    "policy-version-stale",
    "evidence-missing",
    "evidence-stale",
    "dependency-unavailable",
}

MUTATING_OPERATIONS = {
    "workload.restart",
    "workload.deploy",
    "workload.start",
    "workload.stop",
    "backup.create",
    "backup.restore",
    "access.apply",
    "migration.cutover",
    "migration.rollback",
    "production.promote",
    "production.rollback",
    "access.cloudflare-protected.apply",
    "access.cloudflare-protected.rollback",
}

OBSERVATION_OPERATIONS = {
    "health.refresh",
    "logs.preview",
    "migration.preflight",
    "access.cloudflare-protected.plan",
}

CAPABILITY_KEYS = {
    "health.refresh": "health",
    "logs.preview": "logs",
    "migration.preflight": "migrationPreflight",
    "workload.restart": "restart",
    "workload.deploy": "deploy",
    "workload.start": "start",
    "workload.stop": "stop",
    "backup.create": "backup",
    "backup.restore": "restore",
    "access.apply": "access",
    "migration.cutover": "migrationCutover",
    "migration.rollback": "migrationRollback",
    "production.promote": "productionPromote",
    "production.rollback": "productionRollback",
    "access.cloudflare-protected.plan": "cloudflareProtectedPlan",
    "access.cloudflare-protected.apply": "cloudflareProtectedApply",
    "access.cloudflare-protected.rollback": "cloudflareProtectedRollback",
}

COMPATIBILITY_CAPABILITY_KEYS = {
    "health.refresh": "healthAllowed",
    "logs.preview": "logsAllowed",
    "migration.preflight": "migrationPreflightAllowed",
    "workload.restart": "restartAllowed",
    "workload.deploy": "deployAllowed",
    "workload.start": "startAllowed",
    "workload.stop": "stopAllowed",
    "backup.create": "backupAllowed",
    "backup.restore": "restoreAllowed",
    "access.apply": "accessAllowed",
    "migration.cutover": "migrationCutoverAllowed",
    "migration.rollback": "migrationRollbackAllowed",
    "production.promote": "productionPromoteAllowed",
    "production.rollback": "productionRollbackAllowed",
}


@dataclass(frozen=True)
class AdmissionRequest:
    workload_id: str
    operation_type: str
    expected_revision: str
    policy_version: str
    target: Classification


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    decision_code: str
    reasons: tuple[str, ...]
    required_evidence: tuple[str, ...]
    policy_version: str
    revision: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decisionCode": self.decision_code,
            "reasons": list(self.reasons),
            "requiredEvidence": list(self.required_evidence),
            "policyVersion": self.policy_version,
            "revision": self.revision,
        }


class AdmissionDataError(ValueError):
    """Raised when a canonical admission dependency cannot be decoded."""


class ManifestDataError(AdmissionDataError):
    """Raised when a workload manifest cannot be decoded as an object."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionDataError(f"canonical dependency is invalid: {path.name}") from exc


def _list_record(items: Any, workload_id: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("id") == workload_id:
            return item
    return None


def _map_record(items: Any, workload_id: str) -> Any:
    return items.get(workload_id) if isinstance(items, dict) else None


def canonical_records(root: Path, workload_id: str) -> dict[str, Any]:
    config = root / "config"
    workloads = _load(config / "workloads.json")
    policy = _load(config / "policy.json")
    access = _load(config / "access.json")
    privacy = _load(config / "privacy.json")
    classification = _load(config / "argus" / "workload-classification.json")
    routes = _load(config / "routes.json")
    manifest_path = root / "workloads" / workload_id / "manifest.json"
    try:
        manifest = _load(manifest_path)
    except AdmissionDataError as exc:
        raise ManifestDataError("workload manifest is invalid") from exc
    if manifest is not None and not isinstance(manifest, dict):
        raise ManifestDataError("workload manifest is invalid")
    return {
        "workload": _list_record(
            workloads.get("workloads") if isinstance(workloads, dict) else None,
            workload_id,
        ),
        "policy": policy if isinstance(policy, dict) else None,
        "access": _map_record(
            access.get("workloads") if isinstance(access, dict) else None,
            workload_id,
        ),
        "privacy": _map_record(
            privacy.get("workloads") if isinstance(privacy, dict) else None,
            workload_id,
        ),
        "classification": _map_record(
            classification.get("workloads")
            if isinstance(classification, dict)
            else None,
            workload_id,
        ),
        "route": _map_record(
            routes.get("workloadRoutes") if isinstance(routes, dict) else None,
            workload_id,
        ),
        "manifest": manifest if isinstance(manifest, dict) else None,
    }


def canonical_revision(root: Path, workload_id: str) -> str:
    records = canonical_records(root, workload_id)
    return _records_revision(records)


def _records_revision(records: dict[str, Any]) -> str:
    ordered = [records[name] for name in CANONICAL_RECORD_ORDER]
    return hashlib.sha256(canonical_json(ordered).encode("utf-8")).hexdigest()


def policy_version(root: Path) -> str:
    policy = _load(root / "config" / "policy.json")
    return _policy_version_from_record(policy)


def _policy_version_from_record(policy: Any) -> str:
    if not isinstance(policy, dict):
        return ""
    value = policy.get("version")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ""
    return str(value)


def _target_from_record(record: Any) -> Classification:
    if not isinstance(record, dict):
        return Classification(
            "unclassified",
            "legacy",
            "none",
            "legacy-rootful",
            "legacy",
        )
    realm = record.get("realm")
    zone = record.get("zone")
    stage = record.get("stage")
    trust_domain = str(record.get("trustDomain", ""))
    domain_kind = (
        "legacy"
        if realm == "unclassified"
        or zone == "legacy"
        or trust_domain == "legacy-rootful"
        else "workload"
    )
    return Classification(realm, zone, stage, trust_domain, domain_kind)


def canonical_target(root: Path, workload_id: str) -> Classification:
    return _target_from_record(
        canonical_records(root, workload_id).get("classification")
    )


def current_request(
    root: Path,
    workload_id: str,
    operation_type: str,
    *,
    expected_revision: str | None = None,
    expected_policy_version: str | None = None,
) -> AdmissionRequest:
    records = canonical_records(root, workload_id)
    revision = _records_revision(records)
    current_policy = _policy_version_from_record(records.get("policy"))
    return AdmissionRequest(
        workload_id=workload_id,
        operation_type=operation_type,
        expected_revision=revision if expected_revision is None else expected_revision,
        policy_version=(
            current_policy
            if expected_policy_version is None
            else expected_policy_version
        ),
        target=_target_from_record(records.get("classification")),
    )


def evaluate_current(
    root: Path,
    workload_id: str,
    operation_type: str,
    *,
    expected_revision: str | None = None,
    expected_policy_version: str | None = None,
) -> AdmissionDecision:
    try:
        request = current_request(
            root,
            workload_id,
            operation_type,
            expected_revision=expected_revision,
            expected_policy_version=expected_policy_version,
        )
    except ManifestDataError:
        try:
            current_policy = policy_version(root)
        except AdmissionDataError:
            current_policy = ""
        return _decision(
            "manifest-invalid",
            current_policy_version=current_policy,
            revision="",
            required_evidence=("manifest",),
        )
    except AdmissionDataError:
        return _decision(
            "dependency-unavailable",
            current_policy_version="",
            revision="",
            required_evidence=("canonical-config",),
        )
    return evaluate(root, request)


def _decision(
    code: str,
    *,
    current_policy_version: str,
    revision: str,
    reasons: tuple[str, ...] | None = None,
    required_evidence: tuple[str, ...] = (),
) -> AdmissionDecision:
    if code not in DECISION_CODES:
        raise ValueError("unknown admission decision code")
    return AdmissionDecision(
        allowed=code == "allowed",
        decision_code=code,
        reasons=reasons or (code,),
        required_evidence=required_evidence,
        policy_version=current_policy_version,
        revision=revision,
    )


def _manifest_valid(manifest: dict[str, Any], workload_id: str) -> bool:
    required = {
        "id",
        "name",
        "schemaVersion",
        "canonicalRoot",
        "sourcePath",
        "runtime",
        "health",
        "migration",
        "operations",
        "backup",
        "security",
    }
    if not required.issubset(manifest):
        return False
    if (
        manifest.get("id") != workload_id
        or manifest.get("schemaVersion") != 1
        or manifest.get("canonicalRoot") != f"/srv/argus/workloads/{workload_id}"
        or manifest.get("sourcePath")
        != f"/srv/argus/workloads/{workload_id}/source"
    ):
        return False
    if not isinstance(manifest.get("name"), str) or not manifest["name"]:
        return False
    if not all(
        isinstance(manifest.get(name), dict)
        for name in ("runtime", "health", "migration", "operations", "backup", "security")
    ):
        return False
    runtime = manifest["runtime"]
    compose = runtime.get("compose")
    if runtime.get("type") == "docker-compose":
        if not isinstance(compose, dict):
            return False
        compose_path = compose.get("path")
        if (
            not isinstance(compose_path, str)
            or (
                compose_path
                and not compose_path.startswith(
                    f"/srv/argus/workloads/{workload_id}/source/"
                )
            )
            or not isinstance(compose.get("project"), str)
            or not compose.get("project")
            or not isinstance(compose.get("service"), str)
        ):
            return False
    if not isinstance(manifest["backup"].get("backupAllowed"), bool):
        return False
    if not isinstance(manifest["backup"].get("restoreAllowed"), bool):
        return False
    if not isinstance(manifest["security"].get("publicAllowed"), bool):
        return False
    return True


def _capability_permission(
    manifest: dict[str, Any], operation_type: str
) -> dict[str, Any] | None:
    key = CAPABILITY_KEYS.get(operation_type)
    if key is None:
        return None
    operations = manifest.get("operations")
    if not isinstance(operations, dict):
        return None
    permission = operations.get(key)
    if isinstance(permission, dict) and isinstance(permission.get("allowed"), bool):
        return permission
    compatibility = COMPATIBILITY_CAPABILITY_KEYS.get(operation_type)
    if compatibility and isinstance(operations.get(compatibility), bool):
        return {"allowed": operations[compatibility]}
    if operation_type == "backup.create" and isinstance(
        manifest.get("backup", {}).get("backupAllowed"), bool
    ):
        return {"allowed": manifest["backup"]["backupAllowed"]}
    if operation_type == "backup.restore" and isinstance(
        manifest.get("backup", {}).get("restoreAllowed"), bool
    ):
        return {"allowed": manifest["backup"]["restoreAllowed"]}
    return None


def _runtime_evidence_missing(
    manifest: dict[str, Any], workload_id: str
) -> tuple[str, ...]:
    runtime = manifest.get("runtime", {})
    if runtime.get("type") != "docker-compose":
        return ("docker-compose-runtime",)
    compose = runtime.get("compose", {})
    missing: list[str] = []
    if not str(compose.get("path", "")).startswith(
        f"/srv/argus/workloads/{workload_id}/source/"
    ):
        missing.append("canonical-compose-path")
    if not str(compose.get("project", "")):
        missing.append("compose-project")
    return tuple(missing)


def _operation_evidence_missing(
    manifest: dict[str, Any], operation_type: str, workload_id: str
) -> tuple[str, ...]:
    missing: list[str] = []
    if operation_type.startswith("workload.") or operation_type in {
        "health.refresh",
        "logs.preview",
        "migration.cutover",
        "migration.rollback",
        "production.promote",
        "production.rollback",
    }:
        missing.extend(_runtime_evidence_missing(manifest, workload_id))

    backup = manifest.get("backup", {})
    migration = manifest.get("migration", {})
    if operation_type == "backup.create":
        destination = str(backup.get("destination", ""))
        if not backup.get("backupAllowed"):
            missing.append("backup-approval")
        if not destination.startswith(f"/srv/argus/runtime/backups/{workload_id}"):
            missing.append("backup-destination")
    if operation_type in {
        "backup.restore",
        "migration.cutover",
        "production.promote",
    }:
        if not backup.get("restoreAllowed"):
            missing.append("restore-approval")
        if not backup.get("restoreTested"):
            missing.append("restore-test")
    if operation_type in {
        "migration.cutover",
        "migration.rollback",
        "production.promote",
        "production.rollback",
    } and not str(migration.get("rollback", "")).strip():
        missing.append("rollback-contract")
    return tuple(dict.fromkeys(missing))


def evaluate(root: Path, request: AdmissionRequest) -> AdmissionDecision:
    """Return one read-only deterministic admission decision for a typed operation."""
    try:
        records = canonical_records(root, request.workload_id)
        revision = _records_revision(records)
        current_policy = _policy_version_from_record(records.get("policy"))
    except ManifestDataError:
        try:
            current_policy = policy_version(root)
        except AdmissionDataError:
            current_policy = ""
        return _decision(
            "manifest-invalid",
            current_policy_version=current_policy,
            revision="",
            required_evidence=("manifest",),
        )
    except AdmissionDataError:
        return _decision(
            "dependency-unavailable",
            current_policy_version="",
            revision="",
            required_evidence=("canonical-config",),
        )

    if records["workload"] is None:
        return _decision(
            "unknown-workload",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("workload",),
        )
    if not current_policy:
        return _decision(
            "dependency-unavailable",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("policy-version",),
        )
    if request.policy_version != current_policy:
        return _decision(
            "policy-version-stale",
            current_policy_version=current_policy,
            revision=revision,
        )
    if request.expected_revision != revision:
        return _decision(
            "revision-stale",
            current_policy_version=current_policy,
            revision=revision,
        )

    manifest = records["manifest"]
    if manifest is not None and not _manifest_valid(manifest, request.workload_id):
        return _decision(
            "manifest-invalid",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("manifest",),
        )

    missing_records = tuple(
        name for name in CANONICAL_RECORD_ORDER if records.get(name) is None
    )
    if missing_records:
        return _decision(
            "evidence-missing",
            current_policy_version=current_policy,
            revision=revision,
            reasons=tuple(f"missing-{name}-record" for name in missing_records),
            required_evidence=missing_records,
        )
    assert isinstance(manifest, dict)

    permission = _capability_permission(manifest, request.operation_type)
    if permission is None or permission.get("allowed") is not True:
        return _decision(
            "operation-not-capable",
            current_policy_version=current_policy,
            revision=revision,
            reasons=(f"capability-denied-{request.operation_type}",),
            required_evidence=(
                f"manifest.operations.{CAPABILITY_KEYS.get(request.operation_type, 'unknown')}",
            ),
        )
    classification = records["classification"]
    assert isinstance(classification, dict)
    if classification.get("status") != "classified":
        return _decision(
            "classification-incomplete",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("classification",),
        )
    canonical_classification = _target_from_record(classification)
    canonical_is_legacy = (
        canonical_classification.domain_kind == "legacy"
        or canonical_classification.realm == "unclassified"
        or canonical_classification.zone == "legacy"
        or canonical_classification.trust_domain == "legacy-rootful"
    )
    request_is_legacy = (
        request.target.domain_kind == "legacy"
        or request.target.realm == "unclassified"
        or request.target.zone == "legacy"
        or request.target.trust_domain == "legacy-rootful"
    )
    if request.operation_type in MUTATING_OPERATIONS and (
        canonical_is_legacy or request_is_legacy
    ):
        return _decision(
            "legacy-domain-denied",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("non-legacy-target",),
        )
    try:
        canonical_classification.validate()
        request.target.validate()
    except StateError:
        return _decision(
            "classification-incomplete",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("classification",),
        )
    if request.target != canonical_classification:
        return _decision(
            "target-mismatch",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("canonical-target",),
        )
    if (
        request.operation_type in MUTATING_OPERATIONS
        and classification.get("admission") != "allowed"
    ):
        return _decision(
            "admission-denied",
            current_policy_version=current_policy,
            revision=revision,
            required_evidence=("reviewed-admission",),
        )

    missing_operation_evidence = _operation_evidence_missing(
        manifest,
        request.operation_type,
        request.workload_id,
    )
    if missing_operation_evidence:
        return _decision(
            "evidence-missing",
            current_policy_version=current_policy,
            revision=revision,
            reasons=tuple(
                f"missing-{name}" for name in missing_operation_evidence
            ),
            required_evidence=missing_operation_evidence,
        )

    return _decision(
        "allowed",
        current_policy_version=current_policy,
        revision=revision,
        reasons=("admission-allowed",),
    )
