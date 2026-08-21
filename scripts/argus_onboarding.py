"""Default-deny, digest-bound workload onboarding.

Preview writes only an ignored plan. Apply replaces the six reviewed canonical
JSON documents with durable per-file writes, retaining exact backups and a
recovery journal outside Git. Discovery is never adopted or started here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from argus_admission import AdmissionDataError, canonical_revision
from argus_state import Classification, StateError


PLAN_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SAFE_KIND = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
SAFE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
PLAN_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_REALMS = {"personal", "work"}
ALLOWED_ZONES = {"sandbox", "managed"}
ALLOWED_STAGES = {"none", "dev", "staging", "production"}

CONFIG_FILES = (
    ("workload", "config/workloads.json"),
    ("privacy", "config/privacy.json"),
    ("access", "config/access.json"),
    ("route", "config/routes.json"),
    ("classification", "config/argus/workload-classification.json"),
)


class OnboardingError(ValueError):
    """Raised when onboarding cannot safely produce or apply a plan."""


class OnboardingRecoveryRequired(OnboardingError):
    """Raised when a transaction outcome needs explicit recovery."""

    def __init__(self, message: str, *, canonical_state: str) -> None:
        super().__init__(message)
        self.canonical_state = canonical_state


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_value(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, value: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_descriptor = os.open(path.parent, parent_flags)
    temporary = f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    try:
        try:
            existing = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        selected_mode = mode
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                raise OnboardingError("canonical file cannot be a symbolic link")
            if not stat.S_ISREG(existing.st_mode):
                raise OnboardingError("canonical path is not a regular file")
            selected_mode = stat.S_IMODE(existing.st_mode)
            owner_uid, owner_gid = existing.st_uid, existing.st_gid
        else:
            parent = os.fstat(parent_descriptor)
            owner_uid, owner_gid = parent.st_uid, parent.st_gid
        create_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            create_flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, create_flags, 0o600, dir_fd=parent_descriptor)
        try:
            os.fchown(descriptor, owner_uid, owner_gid)
        except PermissionError:
            pass
        os.fchmod(descriptor, 0o644 if selected_mode is None else selected_mode)
        opened_descriptor = descriptor
        descriptor = -1
        with os.fdopen(opened_descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        os.close(parent_descriptor)


def _ensure_directory_like(path: Path, template: Path) -> None:
    if path.is_symlink():
        raise OnboardingError("canonical directory cannot be a symbolic link")
    if path.exists():
        if not path.is_dir():
            raise OnboardingError("canonical directory path is invalid")
        return
    template_stat = template.stat()
    if not stat.S_ISDIR(template_stat.st_mode):
        raise OnboardingError("canonical directory template is invalid")
    path.mkdir(mode=stat.S_IMODE(template_stat.st_mode))
    try:
        os.chown(path, template_stat.st_uid, template_stat.st_gid)
    except PermissionError:
        pass
    _sync_directory(path.parent)


def _load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OnboardingError(f"required canonical file is unavailable: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OnboardingError(f"required canonical file is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise OnboardingError(f"required canonical file is not an object: {path.name}")
    return value


def _file_digest(path: Path) -> str:
    if path.is_symlink():
        raise OnboardingError("canonical file cannot be a symbolic link")
    if not path.exists():
        return "absent"
    if not path.is_file():
        raise OnboardingError("canonical path is not a regular file")
    return digest_bytes(path.read_bytes())


def _safe_text(value: str, field: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise OnboardingError(f"{field} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(character) < 32 for character in normalized):
        raise OnboardingError(f"{field} is invalid")
    return normalized


def _record_map(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OnboardingError(f"{field} must be an object")
    return value


def _record_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise OnboardingError(f"{field} must be a list")
    return value


def _manifest_runtime(manifest: dict[str, Any]) -> tuple[str, str, str, str]:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        return "", "", "", ""
    compose = runtime.get("compose")
    if not isinstance(compose, dict):
        return str(runtime.get("type", "")), "", "", ""
    return (
        str(runtime.get("type", "")),
        str(compose.get("path", "")),
        str(compose.get("project", "")),
        str(compose.get("service", "")),
    )


class OnboardingManager:
    def __init__(
        self,
        root: Path,
        runtime_root: Path | None = None,
        *,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.runtime_root = (
            runtime_root.expanduser().resolve()
            if runtime_root is not None
            else self.root / "runtime" / "argus" / "onboarding"
        )
        try:
            relative_runtime = self.runtime_root.relative_to(self.root)
        except ValueError:
            relative_runtime = None
        if relative_runtime is not None and (
            not relative_runtime.parts or relative_runtime.parts[0] != "runtime"
        ):
            raise OnboardingError("onboarding runtime state must remain outside tracked repository paths")
        self.lock_root = self.root / "runtime" / "argus" / "onboarding"
        self._validate_repository_layout()
        self.fault_hook = fault_hook

    def _validate_repository_layout(self) -> None:
        for relative in ("config", "config/argus", "workloads"):
            path = self.root / relative
            if path.is_symlink() or not path.is_dir() or path.resolve() != path:
                raise OnboardingError("repository canonical directories must be real directories")

    @staticmethod
    def _prepare_private_directory(path: Path, *, private: bool = True) -> None:
        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            if cursor.is_symlink():
                raise OnboardingError("onboarding runtime directory cannot be a symbolic link")
            missing.append(cursor)
            if cursor == cursor.parent:
                raise OnboardingError("onboarding runtime directory has no existing parent")
            cursor = cursor.parent
        if cursor.is_symlink() or not cursor.is_dir() or cursor.resolve() != cursor:
            raise OnboardingError("onboarding runtime directory ancestor is invalid")
        for directory in reversed(missing):
            selected_mode = 0o700 if private else 0o2770
            directory.mkdir(mode=selected_mode)
            directory.chmod(selected_mode)
            _sync_directory(directory.parent)
        if path.is_symlink() or not path.is_dir() or path.resolve() != path:
            raise OnboardingError("onboarding runtime directory is invalid")
        if private:
            try:
                path.chmod(0o700)
            except PermissionError:
                pass

    def _fault(self, boundary: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(boundary)

    def _runtime_directory(self, name: str) -> Path:
        path = self.runtime_root / name
        self._prepare_private_directory(self.runtime_root)
        self._prepare_private_directory(path)
        return path

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._validate_repository_layout()
        self._prepare_private_directory(self.root / "runtime", private=False)
        self._prepare_private_directory(self.root / "runtime" / "argus", private=False)
        self._prepare_private_directory(self.lock_root)
        lock_path = self.lock_root / "apply.lock"
        if lock_path.is_symlink():
            raise OnboardingError("onboarding lock cannot be a symbolic link")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OnboardingError("onboarding lock is not a regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._validate_repository_layout()
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _paths(self, workload_id: str) -> list[tuple[str, str]]:
        return [
            *CONFIG_FILES,
            ("manifest", f"workloads/{workload_id}/manifest.json"),
        ]

    def _validate_inputs(
        self,
        *,
        workload_id: str,
        name: str,
        kind: str,
        runtime: str,
        compose_project: str,
        realm: str,
        zone: str,
        stage: str,
        trust_domain: str,
    ) -> dict[str, str]:
        if SAFE_ID.fullmatch(workload_id) is None:
            raise OnboardingError("workload id is invalid")
        name = _safe_text(name, "name", maximum=120)
        if SAFE_KIND.fullmatch(kind) is None:
            raise OnboardingError("kind is invalid")
        if runtime != "docker-compose":
            raise OnboardingError("only docker-compose onboarding is supported")
        if SAFE_PROJECT.fullmatch(compose_project) is None:
            raise OnboardingError("Compose project is invalid")
        if realm not in ALLOWED_REALMS or zone not in ALLOWED_ZONES or stage not in ALLOWED_STAGES:
            raise OnboardingError("target classification is invalid")
        if trust_domain != f"{realm}-{zone}":
            raise OnboardingError("trust domain must exactly match realm and zone")
        target = Classification(realm, zone, stage, trust_domain, "workload")
        try:
            target.validate()
        except StateError as exc:
            raise OnboardingError("target classification is invalid") from exc
        return {
            "id": workload_id,
            "name": name,
            "kind": kind,
            "runtime": runtime,
            "composeProject": compose_project,
            "realm": realm,
            "zone": zone,
            "stage": stage,
            "trustDomain": trust_domain,
        }

    def _canonical_before(self, workload_id: str) -> dict[str, dict[str, Any] | None]:
        values: dict[str, dict[str, Any] | None] = {}
        for key, relative in self._paths(workload_id):
            path = self.root / relative
            values[key] = None if key == "manifest" and not path.exists() else _load_object(path)
        return values

    def _validate_no_collision(
        self,
        before: dict[str, dict[str, Any] | None],
        workload_id: str,
        compose_project: str,
    ) -> None:
        workloads = _record_list(before["workload"].get("workloads"), "workloads")  # type: ignore[union-attr]
        ids: set[str] = set()
        projects: set[str] = set()
        for item in workloads:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise OnboardingError("canonical workload registry is malformed")
            if item["id"] in ids:
                raise OnboardingError("canonical workload ids are not unique")
            ids.add(item["id"])
            runtime = item.get("runtime", {})
            if isinstance(runtime, dict) and isinstance(runtime.get("composeProject"), str) and runtime["composeProject"]:
                if runtime["composeProject"] in projects:
                    raise OnboardingError("canonical Compose projects are not unique")
                projects.add(runtime["composeProject"])
        if workload_id in ids:
            raise OnboardingError("workload id already exists")
        if compose_project in projects:
            raise OnboardingError("Compose project already exists")

        for key in ("privacy", "access"):
            records = _record_map(before[key].get("workloads"), f"{key}.workloads")  # type: ignore[union-attr]
            if workload_id in records:
                raise OnboardingError(f"workload id collides with {key} state")
        routes = _record_map(before["route"].get("workloadRoutes"), "routes.workloadRoutes")  # type: ignore[union-attr]
        classifications = _record_map(before["classification"].get("workloads"), "classification.workloads")  # type: ignore[union-attr]
        if workload_id in routes or workload_id in classifications or before["manifest"] is not None:
            raise OnboardingError("workload id collides with canonical state")

        legacy_path = self.root / "config" / "argus" / "legacy-classification.json"
        legacy = _load_object(legacy_path)
        legacy_records = legacy.get("workloads", {})
        if isinstance(legacy_records, dict) and workload_id in legacy_records:
            raise OnboardingError("workload id collides with legacy quarantine")

        workload_directory = self.root / "workloads" / workload_id
        if workload_directory.is_symlink():
            raise OnboardingError("workload directory cannot be a symbolic link")
        if workload_directory.exists():
            if not workload_directory.is_dir() or any(workload_directory.iterdir()):
                raise OnboardingError("refusing to adopt an existing workload directory")

        for manifest_path in sorted((self.root / "workloads").glob("*/manifest.json")):
            manifest = _load_object(manifest_path)
            _runtime_type, _path, project, _service = _manifest_runtime(manifest)
            if project == compose_project:
                raise OnboardingError("Compose project collides with a workload manifest")

    def _after_records(
        self,
        before: dict[str, dict[str, Any] | None],
        values: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        workload_id = values["id"]
        canonical_root = f"/srv/argus/workloads/{workload_id}"
        source_path = f"{canonical_root}/source"
        compose_path = f"{source_path}/compose.yml"
        trust_domain = values["trustDomain"]

        after = {
            key: json.loads(json.dumps(value))
            for key, value in before.items()
            if value is not None
        }
        workload = {
            "id": workload_id,
            "name": values["name"],
            "description": "Reviewed onboarding candidate; runtime discovery is not adopted or started.",
            "lifecycle": "discovered",
            "kind": values["kind"],
            "paths": {
                "root": canonical_root,
                "source": source_path,
                "manifest": f"{canonical_root}/manifest.json",
                "legacy": "",
            },
            "runtime": {
                "type": "docker-compose",
                "composePath": compose_path,
                "legacyComposePaths": [],
                "composeProject": values["composeProject"],
                "service": "",
            },
            "network": {"localUrl": "", "internalPort": 0, "observedBindings": []},
            "health": {"enabled": False, "url": "", "expectedStatus": 200, "timeoutSeconds": 3},
            "actions": {
                "open": False,
                "health": False,
                "logs": False,
                "restart": False,
                "deploy": False,
                "accessToggle": False,
                "sandboxReconcileOnly": False,
                "privacyToggle": False,
            },
            "migration": {
                "status": "planned",
                "targetTrustDomain": trust_domain,
                "originalPath": "",
                "compatibilitySymlink": False,
                "bindMountRisks": [],
                "namedVolumeRisks": [],
                "notes": ["Admission and every mutation capability remain denied pending reviewed evidence."],
            },
        }
        _record_list(after["workload"].get("workloads"), "workloads").append(workload)
        _record_map(after["privacy"].get("workloads"), "privacy.workloads")[workload_id] = {
            "privacy": "unclassified",
            "reason": "Reviewed onboarding candidate pending privacy review.",
            "updatedAt": "",
            "updatedBy": "argus-workload-onboard",
        }
        _record_map(after["access"].get("workloads"), "access.workloads")[workload_id] = {
            "desired": "none",
            "effective": "none",
            "urls": {"local": "", "tailnet": "", "cloudflare": ""},
            "lastAppliedAt": "",
            "lastError": "",
        }
        _record_map(after["route"].get("workloadRoutes"), "routes.workloadRoutes")[workload_id] = {
            "tailnet": {"enabled": False, "mode": "blocked", "url": ""},
            "cloudflare": {"enabled": False, "hostname": "", "mode": "disabled", "requiresAuth": True},
        }
        _record_map(after["classification"].get("workloads"), "classification.workloads")[workload_id] = {
            "realm": values["realm"],
            "zone": values["zone"],
            "stage": values["stage"],
            "trustDomain": trust_domain,
            "status": "classified",
            "admission": "denied",
        }

        operation_names = (
            "health",
            "logs",
            "restart",
            "deploy",
            "start",
            "stop",
            "backup",
            "restore",
            "access",
            "migrationPreflight",
            "migrationCutover",
            "migrationRollback",
            "productionPromote",
            "productionRollback",
            "cloudflareProtectedPlan",
            "cloudflareProtectedApply",
            "cloudflareProtectedRollback",
        )
        manifest = {
            "id": workload_id,
            "name": values["name"],
            "description": "Default-deny reviewed onboarding candidate.",
            "schemaVersion": 1,
            "canonicalRoot": canonical_root,
            "sourcePath": source_path,
            "privacyCompatibility": "unclassified",
            "accessCompatibility": "none",
            "runtime": {
                "type": "docker-compose",
                "compose": {"path": compose_path, "project": values["composeProject"], "service": "", "legacyPaths": []},
                "composePath": compose_path,
                "composeProject": values["composeProject"],
                "service": "",
                "legacyComposePaths": [],
            },
            "migration": {
                "status": "planned",
                "targetTrustDomain": trust_domain,
                "originalPath": "",
                "compatibilitySymlink": False,
                "rollback": "No runtime is adopted; remove only the reviewed candidate records before admission.",
                "notes": ["Onboarding does not start, stop, migrate, or adopt a discovered runtime."],
            },
            "health": {"url": "", "expectedStatus": 200, "timeoutSeconds": 3},
            "operations": {name: {"allowed": False} for name in operation_names},
            "backup": {
                "backupAllowed": False,
                "restoreAllowed": False,
                "status": "planned",
                "source": False,
                "env": False,
                "namedVolumes": [],
                "bindMounts": [],
                "database": {"type": "none", "dumpCommand": "", "restoreCommand": ""},
                "destination": f"/srv/argus/runtime/backups/{workload_id}",
                "retention": {"keepLast": 5},
                "restoreTested": False,
                "lastBackupAt": "",
                "lastRestoreTestAt": "",
            },
            "security": {
                "publicAllowed": False,
                "trackedByArgusGit": False,
                "classification": "unclassified",
                "publicExposureAllowed": False,
                "forbiddenTargets": ["legacy-rootful", "public"],
                "notes": ["Public exposure and runtime mutation are denied by default."],
            },
        }
        after["manifest"] = manifest
        self._validate_after(after, workload_id)
        return after

    def _validate_after(self, after: dict[str, dict[str, Any]], workload_id: str) -> None:
        workloads = _record_list(after["workload"].get("workloads"), "workloads")
        workload_ids = [item.get("id") for item in workloads if isinstance(item, dict)]
        if (
            len(workload_ids) != len(workloads)
            or any(not isinstance(item, str) or SAFE_ID.fullmatch(item) is None for item in workload_ids)
            or len(workload_ids) != len(set(workload_ids))
            or workload_ids.count(workload_id) != 1
        ):
            raise OnboardingError("prospective workload record is not unique")
        privacy_records = _record_map(after["privacy"].get("workloads"), "privacy.workloads")
        access_records = _record_map(after["access"].get("workloads"), "access.workloads")
        route_records = _record_map(after["route"].get("workloadRoutes"), "routes.workloadRoutes")
        classification_records = _record_map(after["classification"].get("workloads"), "classification.workloads")
        expected_ids = set(workload_ids)
        if any(set(records) != expected_ids for records in (privacy_records, access_records, route_records, classification_records)):
            raise OnboardingError("prospective canonical registries do not cover the same workload ids")
        privacy = privacy_records.get(workload_id)
        access = access_records.get(workload_id)
        route = route_records.get(workload_id)
        classification = classification_records.get(workload_id)
        manifest = after.get("manifest")
        if not all(isinstance(item, dict) for item in (privacy, access, route, classification, manifest)):
            raise OnboardingError("prospective canonical records are incomplete")
        assert isinstance(access, dict) and isinstance(route, dict) and isinstance(classification, dict) and isinstance(manifest, dict)
        if access.get("desired") != "none" or access.get("effective") != "none":
            raise OnboardingError("new workload access must remain none")
        if route.get("tailnet", {}).get("enabled") is not False or route.get("cloudflare", {}).get("enabled") is not False:
            raise OnboardingError("new workload routes must remain disabled")
        if classification.get("admission") != "denied" or classification.get("status") != "classified":
            raise OnboardingError("new workload admission must remain denied")
        target = Classification(
            classification.get("realm"),
            classification.get("zone"),
            classification.get("stage"),
            str(classification.get("trustDomain", "")),
            "workload",
        )
        try:
            target.validate()
        except StateError as exc:
            raise OnboardingError("prospective classification is invalid") from exc
        for existing_id, existing in classification_records.items():
            if not isinstance(existing, dict):
                raise OnboardingError("prospective classification registry is malformed")
            existing_target = Classification(
                existing.get("realm"),
                existing.get("zone"),
                existing.get("stage"),
                str(existing.get("trustDomain", "")),
                "workload",
            )
            try:
                existing_target.validate()
            except StateError as exc:
                raise OnboardingError(f"prospective classification is invalid for {existing_id}") from exc
            if existing.get("status") != "classified" or existing.get("admission") not in {"allowed", "denied"}:
                raise OnboardingError(f"prospective classification state is invalid for {existing_id}")
        privacy_states = set(after["privacy"].get("states", []))
        access_states = set(after["access"].get("states", []))
        for existing_id in workload_ids:
            privacy_record = privacy_records[existing_id]
            access_record = access_records[existing_id]
            route_record = route_records[existing_id]
            if not isinstance(privacy_record, dict) or privacy_record.get("privacy") not in privacy_states:
                raise OnboardingError(f"prospective privacy state is invalid for {existing_id}")
            if (
                not isinstance(access_record, dict)
                or access_record.get("desired") not in access_states
                or access_record.get("effective") not in access_states
            ):
                raise OnboardingError(f"prospective access state is invalid for {existing_id}")
            if (
                not isinstance(route_record, dict)
                or not isinstance(route_record.get("tailnet"), dict)
                or not isinstance(route_record.get("cloudflare"), dict)
                or not isinstance(route_record["tailnet"].get("enabled"), bool)
                or not isinstance(route_record["cloudflare"].get("enabled"), bool)
            ):
                raise OnboardingError(f"prospective route state is invalid for {existing_id}")
        operations = manifest.get("operations")
        if not isinstance(operations, dict) or not operations or any(
            not isinstance(value, dict) or value.get("allowed") is not False
            for value in operations.values()
        ):
            raise OnboardingError("new workload mutation capabilities must remain denied")
        if manifest.get("id") != workload_id or manifest.get("schemaVersion") != 1:
            raise OnboardingError("prospective manifest identity is invalid")
        if manifest.get("security", {}).get("publicAllowed") is not False:
            raise OnboardingError("new workload public exposure must remain denied")
        if manifest.get("backup", {}).get("backupAllowed") is not False or manifest.get("backup", {}).get("restoreAllowed") is not False:
            raise OnboardingError("new workload backup capabilities must remain denied")
        registry_record = next(item for item in workloads if isinstance(item, dict) and item.get("id") == workload_id)
        registry_runtime = registry_record.get("runtime", {})
        manifest_runtime = _manifest_runtime(manifest)
        if (
            not isinstance(registry_runtime, dict)
            or registry_runtime.get("type") != manifest_runtime[0]
            or registry_runtime.get("composePath") != manifest_runtime[1]
            or registry_runtime.get("composeProject") != manifest_runtime[2]
            or registry_runtime.get("service") != manifest_runtime[3]
        ):
            raise OnboardingError("prospective runtime records disagree")

    def preview(
        self,
        *,
        workload_id: str,
        name: str,
        kind: str,
        runtime: str,
        compose_project: str,
        realm: str,
        zone: str,
        stage: str,
        trust_domain: str,
    ) -> dict[str, Any]:
        with self._lock():
            return self._preview_locked(
                workload_id=workload_id,
                name=name,
                kind=kind,
                runtime=runtime,
                compose_project=compose_project,
                realm=realm,
                zone=zone,
                stage=stage,
                trust_domain=trust_domain,
            )

    def _preview_locked(
        self,
        *,
        workload_id: str,
        name: str,
        kind: str,
        runtime: str,
        compose_project: str,
        realm: str,
        zone: str,
        stage: str,
        trust_domain: str,
    ) -> dict[str, Any]:
        values = self._validate_inputs(
            workload_id=workload_id,
            name=name,
            kind=kind,
            runtime=runtime,
            compose_project=compose_project,
            realm=realm,
            zone=zone,
            stage=stage,
            trust_domain=trust_domain,
        )
        before = self._canonical_before(workload_id)
        self._validate_no_collision(before, workload_id, compose_project)
        after = self._after_records(before, values)
        policy_path = self.root / "config" / "policy.json"
        policy = _load_object(policy_path)
        if "version" not in policy:
            raise OnboardingError("policy version is unavailable")
        files: list[dict[str, Any]] = []
        for key, relative in self._paths(workload_id):
            path = self.root / relative
            after_bytes = json_bytes(after[key])
            files.append({
                "key": key,
                "path": relative,
                "before": before[key],
                "beforeDigest": _file_digest(path),
                "after": after[key],
                "afterDigest": digest_bytes(after_bytes),
            })
        unsigned = {
            "schemaVersion": PLAN_SCHEMA_VERSION,
            "workloadId": workload_id,
            "inputs": values,
            "mutationAuthority": "reviewed-onboarding-only",
            "defaults": {"access": "none", "admission": "denied", "publicExposure": False},
            "dependencies": {
                "policyDigest": _file_digest(policy_path),
                "policyVersion": str(policy["version"]),
            },
            "files": files,
        }
        plan = {**unsigned, "planDigest": digest_value(unsigned)}
        plans = self._runtime_directory("plans")
        plan_path = plans / f"{plan['planDigest'].split(':', 1)[1]}.json"
        encoded = json_bytes(plan)
        if plan_path.exists() and plan_path.read_bytes() != encoded:
            raise OnboardingError("stored onboarding plan digest collision")
        if not plan_path.exists():
            _atomic_write(plan_path, encoded, mode=0o600)
        return plan

    def _plan_path(self, plan_digest: str) -> Path:
        if PLAN_DIGEST.fullmatch(plan_digest) is None:
            raise OnboardingError("plan digest is invalid")
        return self.runtime_root / "plans" / f"{plan_digest.split(':', 1)[1]}.json"

    def _load_plan(self, plan_digest: str) -> dict[str, Any]:
        path = self._plan_path(plan_digest)
        plan = _load_object(path)
        supplied = plan.get("planDigest")
        unsigned = {key: value for key, value in plan.items() if key != "planDigest"}
        if supplied != plan_digest or digest_value(unsigned) != plan_digest:
            raise OnboardingError("stored onboarding plan failed digest verification")
        workload_id = plan.get("workloadId")
        expected_paths = self._paths(str(workload_id)) if isinstance(workload_id, str) and SAFE_ID.fullmatch(workload_id) else []
        files = plan.get("files")
        if (
            plan.get("schemaVersion") != PLAN_SCHEMA_VERSION
            or not isinstance(files, list)
            or [(item.get("key"), item.get("path")) for item in files if isinstance(item, dict)] != expected_paths
            or len(files) != len(expected_paths)
        ):
            raise OnboardingError("stored onboarding plan has an invalid schema")
        dependencies = plan.get("dependencies")
        if (
            not isinstance(dependencies, dict)
            or set(dependencies) != {"policyDigest", "policyVersion"}
            or PLAN_DIGEST.fullmatch(str(dependencies.get("policyDigest", ""))) is None
            or not isinstance(dependencies.get("policyVersion"), str)
            or not dependencies["policyVersion"]
        ):
            raise OnboardingError("stored onboarding plan dependencies are invalid")
        for item in files:
            if not isinstance(item, dict) or item.get("afterDigest") != digest_bytes(json_bytes(item.get("after"))):
                raise OnboardingError("stored onboarding plan has invalid file evidence")
            before = item.get("before")
            if before is None:
                if item.get("beforeDigest") != "absent" or item.get("key") != "manifest":
                    raise OnboardingError("stored onboarding plan has invalid before evidence")
            elif not isinstance(before, dict):
                raise OnboardingError("stored onboarding plan before record is invalid")
        inputs = plan.get("inputs")
        expected_input_keys = {
            "id", "name", "kind", "runtime", "composeProject",
            "realm", "zone", "stage", "trustDomain",
        }
        if not isinstance(inputs, dict) or set(inputs) != expected_input_keys:
            raise OnboardingError("stored onboarding plan inputs are invalid")
        validated_inputs = self._validate_inputs(
            workload_id=inputs["id"],
            name=inputs["name"],
            kind=inputs["kind"],
            runtime=inputs["runtime"],
            compose_project=inputs["composeProject"],
            realm=inputs["realm"],
            zone=inputs["zone"],
            stage=inputs["stage"],
            trust_domain=inputs["trustDomain"],
        )
        if validated_inputs != inputs or inputs["id"] != workload_id:
            raise OnboardingError("stored onboarding plan inputs are not canonical")
        planned_before = {item["key"]: item["before"] for item in files}
        expected_after = self._after_records(planned_before, validated_inputs)
        if any(item["after"] != expected_after[item["key"]] for item in files):
            raise OnboardingError("stored onboarding plan is not a default-deny transformation")
        return plan

    def _journal_path(self) -> Path:
        self._runtime_directory("journal")
        return self.runtime_root / "journal" / "transactions.jsonl"

    def _append_journal(self, record: dict[str, Any]) -> None:
        path = self._journal_path()
        existing = path.read_bytes() if path.exists() else b""
        if existing and not existing.endswith(b"\n"):
            raise OnboardingError("onboarding recovery journal is invalid")
        _atomic_write(path, existing + canonical_bytes(record) + b"\n", mode=0o600)

    def _journal_records(self) -> list[dict[str, Any]]:
        path = self._journal_path()
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
                records.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise OnboardingError("onboarding recovery journal is invalid") from exc
        return records

    def _backup(self, plan: dict[str, Any]) -> Path:
        digest_suffix = plan["planDigest"].split(":", 1)[1]
        backup = self._runtime_directory("backups") / digest_suffix
        if backup.exists():
            if not backup.is_dir() or backup.is_symlink():
                raise OnboardingError("onboarding backup path is invalid")
        else:
            self._prepare_private_directory(backup)
        metadata: list[dict[str, Any]] = []
        for item in plan["files"]:
            name = f"{item['key']}.json"
            destination = backup / name
            source = self.root / item["path"]
            if item["beforeDigest"] == "absent":
                marker = backup / f"{item['key']}.absent"
                _atomic_write(marker, b"absent\n", mode=0o600)
                metadata.append({"key": item["key"], "digest": "absent", "file": marker.name})
                continue
            data = source.read_bytes()
            if digest_bytes(data) != item["beforeDigest"]:
                raise OnboardingError("canonical state changed before backup")
            _atomic_write(destination, data, mode=0o600)
            metadata.append({"key": item["key"], "digest": item["beforeDigest"], "file": name})
        _atomic_write(backup / "backup-index.json", json_bytes({"schemaVersion": 1, "files": metadata}), mode=0o600)
        _sync_directory(backup)
        return backup

    def _restore_before(self, prepared: dict[str, Any]) -> None:
        plan = self._load_plan(str(prepared.get("planDigest", "")))
        backup = self.runtime_root / "backups" / plan["planDigest"].split(":", 1)[1]
        if not backup.is_dir() or backup.is_symlink():
            raise OnboardingError("onboarding recovery backup is unavailable")
        for item in reversed(plan["files"]):
            destination = self.root / item["path"]
            if item["beforeDigest"] == "absent":
                marker = backup / f"{item['key']}.absent"
                if marker.read_bytes() != b"absent\n":
                    raise OnboardingError("onboarding recovery absence marker is invalid")
                if destination.exists():
                    if destination.is_symlink() or not destination.is_file():
                        raise OnboardingError("onboarding recovery destination is unsafe")
                    destination.unlink()
                    _sync_directory(destination.parent)
                continue
            data = (backup / f"{item['key']}.json").read_bytes()
            if digest_bytes(data) != item["beforeDigest"]:
                raise OnboardingError("onboarding recovery backup digest is invalid")
            _atomic_write(destination, data)
        for item in plan["files"]:
            if _file_digest(self.root / item["path"]) != item["beforeDigest"]:
                raise OnboardingError("onboarding recovery could not restore canonical state")

    def _recover_locked(self) -> list[dict[str, str]]:
        try:
            records = self._journal_records()
        except (OnboardingError, OSError) as exc:
            raise OnboardingRecoveryRequired(
                "onboarding recovery journal requires operator recovery",
                canonical_state="recovery-required",
            ) from exc
        phases: dict[str, set[str]] = {}
        prepared_records: dict[str, dict[str, Any]] = {}
        for record in records:
            transaction_id = record.get("transactionId")
            phase = record.get("phase")
            if not isinstance(transaction_id, str) or phase not in {"PREPARED", "COMMITTED", "ABORTED"}:
                raise OnboardingRecoveryRequired(
                    "onboarding recovery journal requires operator recovery",
                    canonical_state="recovery-required",
                )
            phases.setdefault(transaction_id, set()).add(phase)
            if phase == "PREPARED":
                prepared_records[transaction_id] = record
        outcomes: list[dict[str, str]] = []
        for transaction_id, transaction_phases in phases.items():
            if "PREPARED" not in transaction_phases or transaction_phases & {"COMMITTED", "ABORTED"}:
                continue
            prepared = prepared_records[transaction_id]
            try:
                plan = self._load_plan(str(prepared.get("planDigest", "")))
            except (OnboardingError, OSError) as exc:
                raise OnboardingRecoveryRequired(
                    "interrupted onboarding plan requires operator recovery",
                    canonical_state="recovery-required",
                ) from exc
            current = [_file_digest(self.root / item["path"]) for item in plan["files"]]
            before = [item["beforeDigest"] for item in plan["files"]]
            after = [item["afterDigest"] for item in plan["files"]]
            if current == after:
                try:
                    self._validate_applied(plan, require_dependencies=True)
                except OnboardingError:
                    applied_valid = False
                else:
                    applied_valid = True
                if applied_valid:
                    self._append_journal({"phase": "COMMITTED", "transactionId": transaction_id})
                    outcomes.append({"transactionId": transaction_id, "outcome": "committed"})
                else:
                    try:
                        self._restore_before(prepared)
                    except (OnboardingError, OSError) as exc:
                        raise OnboardingRecoveryRequired(
                            "interrupted onboarding rollback requires operator recovery",
                            canonical_state="recovery-required",
                        ) from exc
                    self._append_journal({"phase": "ABORTED", "transactionId": transaction_id})
                    outcomes.append({"transactionId": transaction_id, "outcome": "rolled-back"})
            elif all(value in {before[index], after[index]} for index, value in enumerate(current)):
                try:
                    self._restore_before(prepared)
                except (OnboardingError, OSError) as exc:
                    raise OnboardingRecoveryRequired(
                        "interrupted onboarding rollback requires operator recovery",
                        canonical_state="recovery-required",
                    ) from exc
                self._append_journal({"phase": "ABORTED", "transactionId": transaction_id})
                outcomes.append({"transactionId": transaction_id, "outcome": "rolled-back"})
            else:
                raise OnboardingRecoveryRequired(
                    "interrupted onboarding has divergent canonical state",
                    canonical_state="recovery-required",
                )
        return outcomes

    def recover(self) -> list[dict[str, str]]:
        with self._lock():
            try:
                return self._recover_locked()
            except OnboardingRecoveryRequired:
                raise
            except (OnboardingError, OSError) as exc:
                raise OnboardingRecoveryRequired(
                    "onboarding recovery evidence requires operator recovery",
                    canonical_state="recovery-required",
                ) from exc

    def _dependencies_current(self, plan: dict[str, Any]) -> bool:
        dependencies = plan["dependencies"]
        policy_path = self.root / "config" / "policy.json"
        if _file_digest(policy_path) != dependencies["policyDigest"]:
            return False
        try:
            policy = _load_object(policy_path)
        except OnboardingError:
            return False
        return str(policy.get("version", "")) == dependencies["policyVersion"]

    def _validate_current_before(self, plan: dict[str, Any]) -> None:
        for item in plan["files"]:
            path = self.root / item["path"]
            actual = None if item["beforeDigest"] == "absent" else _load_object(path)
            if actual != item["before"]:
                raise OnboardingError("canonical records do not match the reviewed before state")

    def _validate_applied(self, plan: dict[str, Any], *, require_dependencies: bool = False) -> None:
        after = {item["key"]: _load_object(self.root / item["path"]) for item in plan["files"]}
        self._validate_after(after, plan["workloadId"])
        if any(_file_digest(self.root / item["path"]) != item["afterDigest"] for item in plan["files"]):
            raise OnboardingError("applied canonical state does not match the reviewed plan")
        if require_dependencies and not self._dependencies_current(plan):
            raise OnboardingError("onboarding policy dependency changed")

    def _result(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "schemaVersion": RESULT_SCHEMA_VERSION,
            "status": "completed",
            "workloadId": plan["workloadId"],
            "planDigest": plan["planDigest"],
            "revision": canonical_revision(self.root, plan["workloadId"]),
            "defaults": {"access": "none", "admission": "denied", "publicExposure": False},
            "fileDigests": {item["key"]: item["afterDigest"] for item in plan["files"]},
        }

    def _completion_path(self, plan_digest: str) -> Path:
        return self._runtime_directory("completions") / f"{plan_digest.split(':', 1)[1]}.json"

    @staticmethod
    def _completion_valid(plan: dict[str, Any], completion: dict[str, Any]) -> bool:
        return (
            completion.get("schemaVersion") == RESULT_SCHEMA_VERSION
            and completion.get("status") == "completed"
            and completion.get("workloadId") == plan["workloadId"]
            and completion.get("planDigest") == plan["planDigest"]
            and isinstance(completion.get("revision"), str)
            and re.fullmatch(r"[0-9a-f]{64}", completion["revision"]) is not None
            and completion.get("defaults") == {"access": "none", "admission": "denied", "publicExposure": False}
            and completion.get("fileDigests") == {item["key"]: item["afterDigest"] for item in plan["files"]}
        )

    def apply(self, *, plan_digest: str, confirm: str) -> dict[str, Any]:
        with self._lock():
            try:
                self._recover_locked()
            except OnboardingRecoveryRequired:
                raise
            except (OnboardingError, OSError) as exc:
                raise OnboardingRecoveryRequired(
                    "onboarding recovery evidence requires operator recovery",
                    canonical_state="recovery-required",
                ) from exc
            plan = self._load_plan(plan_digest)
            if confirm != plan["workloadId"]:
                raise OnboardingError("typed confirmation does not match the workload id")
            completion_path = self._completion_path(plan_digest)
            if completion_path.exists():
                completion = _load_object(completion_path)
                self._validate_applied(plan)
                if not self._completion_valid(plan, completion):
                    raise OnboardingError("onboarding completion evidence is invalid")
                return completion

            current = [_file_digest(self.root / item["path"]) for item in plan["files"]]
            before = [item["beforeDigest"] for item in plan["files"]]
            after = [item["afterDigest"] for item in plan["files"]]
            if current == after:
                self._validate_applied(plan, require_dependencies=True)
                result = self._result(plan)
                _atomic_write(completion_path, json_bytes(result), mode=0o600)
                return result
            if current != before:
                raise OnboardingError("canonical state changed after preview")
            self._validate_current_before(plan)
            if not self._dependencies_current(plan):
                raise OnboardingError("onboarding policy dependency changed after preview")

            values = plan.get("inputs")
            if not isinstance(values, dict):
                raise OnboardingError("stored onboarding inputs are invalid")
            canonical_before = {item["key"]: item["before"] for item in plan["files"]}
            self._validate_no_collision(canonical_before, plan["workloadId"], str(values.get("composeProject", "")))
            self._backup(plan)
            transaction_id = str(uuid.uuid4())
            prepared = {
                "phase": "PREPARED",
                "transactionId": transaction_id,
                "planDigest": plan_digest,
                "workloadId": plan["workloadId"],
            }
            self._append_journal(prepared)
            self._fault("after-prepared")
            try:
                for item in plan["files"]:
                    if item["key"] == "manifest":
                        _ensure_directory_like(
                            (self.root / item["path"]).parent,
                            self.root / "workloads",
                        )
                    _atomic_write(self.root / item["path"], json_bytes(item["after"]))
                    self._fault(f"after-write:{item['key']}")
                self._validate_applied(plan, require_dependencies=True)
                self._fault("after-validation")
                result = self._result(plan)
                self._append_journal({"phase": "COMMITTED", "transactionId": transaction_id})
            except (OnboardingError, AdmissionDataError, OSError) as exc:
                try:
                    self._restore_before(prepared)
                    self._append_journal({"phase": "ABORTED", "transactionId": transaction_id})
                except (OnboardingError, OSError) as recovery_exc:
                    raise OnboardingRecoveryRequired(
                        "onboarding apply failed and canonical recovery is required",
                        canonical_state="recovery-required",
                    ) from recovery_exc
                raise OnboardingError("onboarding apply failed and was rolled back") from exc
            self._fault("after-committed")
            try:
                _atomic_write(completion_path, json_bytes(result), mode=0o600)
            except (OnboardingError, OSError) as exc:
                raise OnboardingRecoveryRequired(
                    "onboarding committed but completion evidence requires recovery",
                    canonical_state="committed-evidence-incomplete",
                ) from exc
            return result
