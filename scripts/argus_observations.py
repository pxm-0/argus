"""Deterministic, vendor-neutral configured-estate observation repository.

This module deliberately has no collector execution, reconciliation admission, policy,
authorization, or mutation surface.  It accepts only bounded normalized observations
from separately reviewed adapters and keeps failed evidence separate from the last
known-good snapshot.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPOSITORY_VERSION = 2
PREVIOUS_REPOSITORY_VERSION = 1
REGISTRY_VERSION = 1
NORMALIZED_RECORD_VERSION = 2
PREVIOUS_NORMALIZED_RECORD_VERSION = 1
DEFAULT_DATABASE_CEILING_BYTES = 8 * 1024 * 1024
DEFAULT_KEEP_COMPLETED_RUNS = 20
DEFAULT_KEEP_FAILED_RUNS = 20
SOURCE_STATES = {"never_observed", "fresh", "stale", "failed", "excluded"}
TERMINAL_RUN_STATES = {"completed", "partial", "failed"}
FORBIDDEN_ATTRIBUTE_KEYS = {
    "command",
    "commandline",
    "command_line",
    "credential",
    "credentials",
    "env",
    "environment",
    "filecontent",
    "file_content",
    "gitremote",
    "git_remote",
    "password",
    "secret",
    "token",
}
FORBIDDEN_VALUE_MARKERS = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "password=",
    "token=",
    "secret=",
)


class ObservationError(ValueError):
    """Raised when observation state cannot be accepted safely."""


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _nfc(str(key))
            if normalized_key in normalized:
                raise ObservationError(f"duplicate normalized key: {normalized_key}")
            normalized[normalized_key] = canonical_value(item)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, list):
        return [canonical_value(item) for item in value]
    if isinstance(value, str):
        return _nfc(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    raise ObservationError(f"unsupported normalized value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _required_text(record: dict[str, Any], key: str, *, maximum: int = 512) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise ObservationError(f"{key} must be non-empty bounded text")
    return _nfc(value)


def _required_positive_int(record: dict[str, Any], key: str, *, maximum: int) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
        raise ObservationError(f"{key} must be between 1 and {maximum}")
    return value


def _utc_timestamp(record: dict[str, Any], key: str) -> tuple[str, int]:
    value = _required_text(record, key)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ObservationError(f"{key} must be canonical UTC time") from exc
    return value, int(parsed.replace(tzinfo=timezone.utc).timestamp())


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    host_id: str
    owner: str
    trust_domain: str
    scope: str
    privilege: str
    freshness_slo_seconds: int
    schema_version: int
    protocol_version: int
    execution_identity: dict[str, Any]
    allowlist: dict[str, Any]
    bounds: dict[str, int]
    minimization: dict[str, Any]
    bootstrap: str
    removal: str
    exclusion: dict[str, str] | None

    def as_registry_record(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "hostId": self.host_id,
            "owner": self.owner,
            "trustDomain": self.trust_domain,
            "scope": self.scope,
            "privilege": self.privilege,
            "freshnessSloSeconds": self.freshness_slo_seconds,
            "schemaVersion": self.schema_version,
            "protocolVersion": self.protocol_version,
            "executionIdentity": self.execution_identity,
            "allowlist": self.allowlist,
            "bounds": self.bounds,
            "minimization": self.minimization,
            "bootstrap": self.bootstrap,
            "removal": self.removal,
            "exclusion": self.exclusion,
        }

    def as_repository_record(self) -> dict[str, Any]:
        """Return source metadata safe to persist centrally (no command/API surface)."""
        return {
            "sourceId": self.source_id,
            "hostId": self.host_id,
            "owner": self.owner,
            "trustDomain": self.trust_domain,
            "scope": self.scope,
            "privilege": self.privilege,
            "freshnessSloSeconds": self.freshness_slo_seconds,
            "schemaVersion": self.schema_version,
            "protocolVersion": self.protocol_version,
            "executionIdentity": self.execution_identity,
            "allowlistDigest": digest(self.allowlist),
            "bounds": self.bounds,
            "minimization": self.minimization,
            "bootstrapDigest": digest(self.bootstrap),
            "removalDigest": digest(self.removal),
            "exclusion": self.exclusion,
        }


class SourceRegistry:
    """Validated configured sources plus canonical-domain denominator."""

    def __init__(self, payload: dict[str, Any], canonical_domains: Iterable[str]):
        if not isinstance(payload, dict) or payload.get("schemaVersion") != REGISTRY_VERSION:
            raise ObservationError("unsupported source registry version")
        if set(payload) != {"schemaVersion", "hostSources", "sources"}:
            raise ObservationError("source registry has unknown or missing fields")
        if not isinstance(payload["hostSources"], list) or not all(
            isinstance(item, str) and item for item in payload["hostSources"]
        ):
            raise ObservationError("hostSources must be a list of stable source IDs")
        normalized_hosts = [_nfc(item) for item in payload["hostSources"]]
        if len(normalized_hosts) != len(set(normalized_hosts)):
            raise ObservationError("hostSources cannot contain duplicates")
        raw_domains = list(canonical_domains)
        if not all(isinstance(item, str) and item for item in raw_domains):
            raise ObservationError("canonical trust domains must be non-empty text")
        domains = sorted({_nfc(item) for item in raw_domains})
        self.canonical_domains = tuple(domains)
        self.host_sources = tuple(sorted(normalized_hosts))
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            raise ObservationError("sources must be a list")
        parsed: dict[str, SourceSpec] = {}
        for raw in raw_sources:
            source = self._parse_source(raw)
            if source.source_id in parsed:
                raise ObservationError(f"duplicate source: {source.source_id}")
            parsed[source.source_id] = source
        self.sources = parsed

    @staticmethod
    def _parse_source(raw: Any) -> SourceSpec:
        required = {
            "sourceId", "hostId", "owner", "trustDomain", "scope", "privilege",
            "freshnessSloSeconds", "schemaVersion", "protocolVersion", "executionIdentity",
            "allowlist", "bounds", "minimization", "bootstrap", "removal", "exclusion",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ObservationError("source has unknown or missing fields")
        identity = raw["executionIdentity"]
        if not isinstance(identity, dict) or set(identity) != {"uid", "gid"} or not all(
            isinstance(identity[key], int) and identity[key] >= 0 for key in identity
        ):
            raise ObservationError("executionIdentity requires numeric uid and gid")
        allowlist = raw["allowlist"]
        if not isinstance(allowlist, dict) or set(allowlist) != {"commands", "apis"}:
            raise ObservationError("allowlist requires exact commands and APIs")
        commands = allowlist["commands"]
        apis = allowlist["apis"]
        if not isinstance(commands, list) or not all(
            isinstance(command, list) and command and all(isinstance(arg, str) and arg for arg in command)
            for command in commands
        ):
            raise ObservationError("commands must be exact non-empty argv lists")
        if not isinstance(apis, list) or not all(isinstance(api, str) and api for api in apis):
            raise ObservationError("apis must be exact non-empty identifiers")
        if not commands and not apis:
            raise ObservationError("source requires at least one exact command or API")
        bounds = raw["bounds"]
        if not isinstance(bounds, dict) or set(bounds) != {
            "timeoutMilliseconds", "maxOutputBytes", "maxRecords", "maxRecordBytes"
        }:
            raise ObservationError("source bounds are incomplete")
        validated_bounds = {
            "timeoutMilliseconds": _required_positive_int(bounds, "timeoutMilliseconds", maximum=600_000),
            "maxOutputBytes": _required_positive_int(bounds, "maxOutputBytes", maximum=64 * 1024 * 1024),
            "maxRecords": _required_positive_int(bounds, "maxRecords", maximum=1_000_000),
            "maxRecordBytes": _required_positive_int(bounds, "maxRecordBytes", maximum=1024 * 1024),
        }
        minimization = raw["minimization"]
        if not isinstance(minimization, dict) or set(minimization) != {"resourceKinds", "attributeAllowlist"}:
            raise ObservationError("minimization requires resourceKinds and attributeAllowlist")
        kinds = minimization["resourceKinds"]
        attributes = minimization["attributeAllowlist"]
        if not isinstance(kinds, list) or not kinds or not all(isinstance(item, str) and item for item in kinds):
            raise ObservationError("resourceKinds must be a non-empty list")
        if not isinstance(attributes, dict) or set(attributes) != set(kinds):
            raise ObservationError("every resource kind requires an attribute allowlist")
        for kind, fields in attributes.items():
            if not isinstance(fields, list) or not all(isinstance(field, str) and field for field in fields):
                raise ObservationError(f"invalid attribute allowlist for {kind}")
            forbidden = FORBIDDEN_ATTRIBUTE_KEYS & {field.casefold() for field in fields}
            if forbidden:
                raise ObservationError(f"forbidden attributes in allowlist: {', '.join(sorted(forbidden))}")
        exclusion = raw["exclusion"]
        if exclusion is not None:
            if not isinstance(exclusion, dict) or set(exclusion) != {"owner", "reason", "expiresAt"}:
                raise ObservationError("exclusion requires owner, reason, and expiresAt")
            exclusion = {key: _required_text(exclusion, key) for key in sorted(exclusion)}
            _utc_timestamp(exclusion, "expiresAt")
        privilege = _required_text(raw, "privilege")
        if privilege not in {"unprivileged", "domain-read-only", "host-read-only"}:
            raise ObservationError("source privilege is unsupported")
        return SourceSpec(
            source_id=_required_text(raw, "sourceId"),
            host_id=_required_text(raw, "hostId"),
            owner=_required_text(raw, "owner"),
            trust_domain=_required_text(raw, "trustDomain"),
            scope=_required_text(raw, "scope"),
            privilege=privilege,
            freshness_slo_seconds=_required_positive_int(raw, "freshnessSloSeconds", maximum=31_536_000),
            schema_version=_required_positive_int(raw, "schemaVersion", maximum=REPOSITORY_VERSION),
            protocol_version=_required_positive_int(raw, "protocolVersion", maximum=2),
            execution_identity=canonical_value(identity),
            allowlist=canonical_value(allowlist),
            bounds=validated_bounds,
            minimization=canonical_value(minimization),
            bootstrap=_required_text(raw, "bootstrap", maximum=2048),
            removal=_required_text(raw, "removal", maximum=2048),
            exclusion=exclusion,
        )

    def configuration_gaps(self) -> list[dict[str, str]]:
        represented = {source.trust_domain for source in self.sources.values()}
        gaps = [
            {"kind": "configuration-gap", "trustDomain": domain}
            for domain in self.canonical_domains
            if domain not in represented
        ]
        gaps.extend(
            {"kind": "configuration-gap", "sourceId": source_id}
            for source_id in self.host_sources
            if source_id not in self.sources
        )
        return gaps

    @property
    def registry_digest(self) -> str:
        return digest({
            "schemaVersion": REGISTRY_VERSION,
            "canonicalDomains": list(self.canonical_domains),
            "hostSources": list(self.host_sources),
            "sources": [self.sources[key].as_registry_record() for key in sorted(self.sources)],
        })


def canonical_trust_domains(root: Path) -> list[str]:
    """Derive the required denominator from reviewed canonical classifications."""
    paths = [
        root / "config" / "argus" / "workload-classification.json",
        root / "config" / "argus" / "legacy-classification.json",
    ]
    domains: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise ObservationError(f"canonical trust-domain source is missing: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        records: list[Any] = []
        if "workloads" in payload and not isinstance(payload["workloads"], dict):
            raise ObservationError(f"canonical trust-domain source is malformed: {path.name}")
        if isinstance(payload.get("workloads"), dict):
            records.extend(payload["workloads"].values())
        if isinstance(payload.get("trustDomain"), str):
            records.append(payload)
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("trustDomain"), str) or not record["trustDomain"]:
                raise ObservationError(f"canonical trust-domain record is malformed: {path.name}")
            domains.add(_nfc(record["trustDomain"]))
    if not domains:
        raise ObservationError("canonical trust-domain denominator is empty")
    return sorted(domains)


def load_registry(path: Path, root: Path) -> SourceRegistry:
    return SourceRegistry(json.loads(path.read_text(encoding="utf-8")), canonical_trust_domains(root))


def normalize_records(source: SourceSpec, records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, str]:
    normalized: list[dict[str, Any]] = []
    total_bytes = 0
    seen: set[tuple[str, str]] = set()
    allowed_kinds = set(source.minimization["resourceKinds"])
    allowed_fields = source.minimization["attributeAllowlist"]
    for raw in records:
        if len(normalized) >= source.bounds["maxRecords"]:
            raise ObservationError("normalized observations exceed maxRecords")
        if not isinstance(raw, dict) or set(raw) != {
            "schemaVersion", "resourceKind", "nativeId", "observedAt", "attributes", "provenance"
        }:
            raise ObservationError("normalized observation has unknown or missing fields")
        if raw["schemaVersion"] not in {PREVIOUS_NORMALIZED_RECORD_VERSION, NORMALIZED_RECORD_VERSION}:
            raise ObservationError("unsupported normalized observation version")
        kind = _required_text(raw, "resourceKind")
        native_id = _required_text(raw, "nativeId")
        observed_at, _observed_epoch = _utc_timestamp(raw, "observedAt")
        if kind not in allowed_kinds:
            raise ObservationError(f"resource kind is not allowlisted: {kind}")
        identity = (kind, native_id)
        if identity in seen:
            raise ObservationError(f"duplicate native identity in run: {kind}/{native_id}")
        seen.add(identity)
        attributes = raw["attributes"]
        if not isinstance(attributes, dict):
            raise ObservationError("attributes must be an object")
        unknown = set(attributes) - set(allowed_fields[kind])
        forbidden = FORBIDDEN_ATTRIBUTE_KEYS & {str(key).casefold() for key in attributes}
        if unknown or forbidden:
            raise ObservationError("observation contains non-allowlisted attributes")
        _validate_safe_value(attributes)
        provenance = raw["provenance"]
        if not isinstance(provenance, dict) or set(provenance) != {"adapter", "adapterVersion", "ordinal"}:
            raise ObservationError("provenance must contain only adapter, adapterVersion, and ordinal")
        adapter = _required_text(provenance, "adapter")
        adapter_version = _required_text(provenance, "adapterVersion")
        if not isinstance(provenance["ordinal"], int) or provenance["ordinal"] < 0:
            raise ObservationError("provenance ordinal must be non-negative")
        _validate_safe_value({
            "resourceKind": kind,
            "nativeId": native_id,
            "adapter": adapter,
            "adapterVersion": adapter_version,
        })
        record = canonical_value({
            "schemaVersion": raw["schemaVersion"],
            "resourceKind": kind,
            "nativeId": native_id,
            "observedAt": observed_at,
            "attributes": attributes,
            "provenance": {
                "adapter": adapter,
                "adapterVersion": adapter_version,
                "ordinal": provenance["ordinal"],
            },
        })
        encoded = canonical_bytes(record)
        if len(encoded) > source.bounds["maxRecordBytes"]:
            raise ObservationError("normalized observation exceeds maxRecordBytes")
        total_bytes += len(encoded)
        if total_bytes > source.bounds["maxOutputBytes"]:
            raise ObservationError("normalized observations exceed maxOutputBytes")
        normalized.append(record)
    normalized.sort(key=lambda item: (item["resourceKind"], item["nativeId"], canonical_bytes(item)))
    return normalized, total_bytes, digest({"sourceId": source.source_id, "records": normalized})


def _validate_safe_value(value: Any, *, depth: int = 0) -> None:
    if depth > 8:
        raise ObservationError("observation attributes exceed nesting bound")
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_ATTRIBUTE_KEYS:
                raise ObservationError("observation contains a forbidden private field")
            _validate_safe_value(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 1000:
            raise ObservationError("observation attribute list exceeds bound")
        for item in value:
            _validate_safe_value(item, depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 16_384:
            raise ObservationError("observation attribute text exceeds bound")
        folded = value.casefold()
        if any(marker.casefold() in folded for marker in FORBIDDEN_VALUE_MARKERS):
            raise ObservationError("observation contains a secret marker")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    raise ObservationError("observation attribute has an unsupported value")


SCHEMA_V1 = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
  source_id TEXT PRIMARY KEY, registry_json TEXT NOT NULL, registry_digest TEXT NOT NULL,
  active INTEGER NOT NULL CHECK(active IN (0,1)), current_run_id TEXT
);
CREATE TABLE collection_runs (
  run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id), sequence INTEGER NOT NULL,
  repository_version INTEGER NOT NULL, source_schema_version INTEGER NOT NULL,
  protocol_version INTEGER NOT NULL, registry_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('collecting','completed','partial','failed')),
  started_at TEXT NOT NULL, terminal_at TEXT, record_count INTEGER NOT NULL DEFAULT 0,
  byte_count INTEGER NOT NULL DEFAULT 0, snapshot_digest TEXT, gap_code TEXT,
  UNIQUE(source_id, sequence)
);
CREATE TABLE observations (
  source_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
  record_version INTEGER NOT NULL,
  resource_kind TEXT NOT NULL, native_id TEXT NOT NULL, observed_at TEXT NOT NULL,
  attributes_json TEXT NOT NULL, provenance_json TEXT NOT NULL,
  PRIMARY KEY(source_id, resource_kind, native_id, run_id)
);
CREATE INDEX observations_identity ON observations(source_id, resource_kind, native_id);
CREATE INDEX collection_runs_source_state ON collection_runs(source_id, state, sequence);
"""


SCHEMA_V2_STATEMENTS = (
    "ALTER TABLE sources ADD COLUMN removed_at TEXT",
    "ALTER TABLE collection_runs ADD COLUMN superseded_by TEXT",
    """CREATE TABLE reconciliation_links (
  link_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, resource_kind TEXT NOT NULL, native_id TEXT NOT NULL,
  run_id TEXT NOT NULL, canonical_ref TEXT NOT NULL, link_state TEXT NOT NULL,
  evidence_digest TEXT NOT NULL,
  FOREIGN KEY(source_id, resource_kind, native_id, run_id)
    REFERENCES observations(source_id, resource_kind, native_id, run_id)
)""",
    "CREATE INDEX reconciliation_observation ON reconciliation_links(source_id, resource_kind, native_id, run_id)",
)


class ObservationRepository:
    """SQLite repository with explicit, atomic last-known-good pointers."""

    def __init__(self, path: Path, *, max_database_bytes: int = DEFAULT_DATABASE_CEILING_BYTES, read_only: bool = False):
        self.path = path
        self.max_database_bytes = max_database_bytes
        self.read_only = read_only
        if max_database_bytes <= 0:
            raise ObservationError("max_database_bytes must be positive")
        existed = path.exists()
        if read_only:
            if not path.is_file():
                raise ObservationError("observation repository does not exist")
            self.connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, timeout=30.0)
            if not existed:
                path.chmod(0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        version = self._detect_version()
        if version is None:
            if read_only:
                raise ObservationError("observation repository is uninitialized")
            self._create(PREVIOUS_REPOSITORY_VERSION)
            self.migrate()
            version = REPOSITORY_VERSION
        if version not in {PREVIOUS_REPOSITORY_VERSION, REPOSITORY_VERSION}:
            self.connection.close()
            raise ObservationError(f"unsupported observation repository version: {version}")
        self.version = version
        self._enforce_size()

    def __enter__(self) -> "ObservationRepository":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _detect_version(self) -> int | None:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchone()
        if table is None:
            return None
        row = self.connection.execute("SELECT value FROM metadata WHERE key='repository_version'").fetchone()
        if row is None:
            raise ObservationError("observation repository version is missing")
        try:
            return int(row[0])
        except ValueError as exc:
            raise ObservationError("observation repository version is invalid") from exc

    def _create(self, version: int) -> None:
        if version not in {PREVIOUS_REPOSITORY_VERSION, REPOSITORY_VERSION}:
            raise ObservationError("cannot create unsupported repository version")
        with self.connection:
            self.connection.executescript(SCHEMA_V1)
            self.connection.execute(
                "INSERT INTO metadata(key,value) VALUES('repository_version',?)", (str(PREVIOUS_REPOSITORY_VERSION),)
            )
        self.version = PREVIOUS_REPOSITORY_VERSION
        if version == REPOSITORY_VERSION:
            self.migrate()

    @classmethod
    def create_version(cls, path: Path, version: int) -> None:
        if version not in {PREVIOUS_REPOSITORY_VERSION, REPOSITORY_VERSION}:
            raise ObservationError("cannot create unsupported repository version")
        if path.exists():
            raise ObservationError("refusing to overwrite an observation repository")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        path.chmod(0o600)
        try:
            connection.executescript(SCHEMA_V1)
            connection.execute(
                "INSERT INTO metadata(key,value) VALUES('repository_version',?)",
                (str(PREVIOUS_REPOSITORY_VERSION),),
            )
            connection.commit()
        finally:
            connection.close()
        if version == REPOSITORY_VERSION:
            with cls(path) as repository:
                repository.migrate()

    def migrate(self) -> None:
        if self.read_only:
            raise ObservationError("read-only repository cannot migrate")
        version = self._detect_version()
        if version == REPOSITORY_VERSION:
            self.version = version
            return
        if version != PREVIOUS_REPOSITORY_VERSION:
            raise ObservationError("no safe migration path for repository version")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in SCHEMA_V2_STATEMENTS:
                self.connection.execute(statement)
            self.connection.execute(
                "UPDATE metadata SET value=? WHERE key='repository_version'", (str(REPOSITORY_VERSION),)
            )
            self.connection.commit()
        except (sqlite3.DatabaseError, OSError) as exc:
            self.connection.rollback()
            raise ObservationError("observation repository migration failed") from exc
        self.version = REPOSITORY_VERSION
        self._enforce_size()

    def backup(self, destination: Path) -> str:
        if destination.exists():
            raise ObservationError("refusing to overwrite repository backup")
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup_connection = sqlite3.connect(destination)
        try:
            self.connection.backup(backup_connection)
        finally:
            backup_connection.close()
        destination.chmod(0o600)
        with destination.open("rb") as handle:
            os.fsync(handle.fileno())
        _sync_directory(destination.parent)
        with destination.open("rb") as handle:
            return "sha256:" + hashlib.sha256(handle.read()).hexdigest()

    @staticmethod
    def restore_backup(
        backup: Path,
        destination: Path,
        *,
        max_database_bytes: int = DEFAULT_DATABASE_CEILING_BYTES,
    ) -> None:
        if not backup.is_file() or backup.is_symlink():
            raise ObservationError("repository backup does not exist")
        if max_database_bytes <= 0 or backup.stat().st_size > max_database_bytes:
            raise ObservationError("repository backup exceeds database-size ceiling")
        probe = sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if probe.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ObservationError("repository backup integrity check failed")
            version_row = probe.execute(
                "SELECT value FROM metadata WHERE key='repository_version'"
            ).fetchone()
            if version_row is None or int(version_row[0]) not in {
                PREVIOUS_REPOSITORY_VERSION,
                REPOSITORY_VERSION,
            }:
                raise ObservationError("repository backup version is unsupported")
        except (sqlite3.DatabaseError, ValueError) as exc:
            raise ObservationError("repository backup schema is invalid") from exc
        finally:
            probe.close()
        temporary = destination.with_name(f".{destination.name}.restore")
        if temporary.exists():
            raise ObservationError("repository restore temporary path already exists")
        shutil.copyfile(backup, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        _sync_directory(destination.parent)

    def _enforce_size(self) -> None:
        page_count = int(self.connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(self.connection.execute("PRAGMA page_size").fetchone()[0])
        if page_count * page_size > self.max_database_bytes:
            raise ObservationError("observation repository exceeds database-size ceiling")

    def sync_registry(self, registry: SourceRegistry, *, explicit_clock: str) -> None:
        if self.read_only or self.version != REPOSITORY_VERSION:
            raise ObservationError("current writable repository required")
        explicit_clock, _clock_epoch = _utc_timestamp({"explicitClock": explicit_clock}, "explicitClock")
        with self.connection:
            active_ids = set(registry.sources)
            existing = {
                row["source_id"] for row in self.connection.execute("SELECT source_id FROM sources")
            }
            for source_id in sorted(active_ids):
                source = registry.sources[source_id]
                persisted = source.as_repository_record()
                record_json = canonical_bytes(persisted).decode("utf-8").strip()
                self.connection.execute(
                    """INSERT INTO sources(source_id,registry_json,registry_digest,active,current_run_id,removed_at)
                       VALUES(?,?,?,?,NULL,NULL)
                       ON CONFLICT(source_id) DO UPDATE SET registry_json=excluded.registry_json,
                         registry_digest=excluded.registry_digest,active=1,removed_at=NULL""",
                    (source_id, record_json, digest(persisted), 1),
                )
            for removed in sorted(existing - active_ids):
                self.connection.execute(
                    "UPDATE sources SET active=0, removed_at=? WHERE source_id=? AND active=1",
                    (explicit_clock, removed),
                )
        self._enforce_size()

    def ingest(
        self,
        registry: SourceRegistry,
        *,
        run_id: str,
        source_id: str,
        sequence: int,
        state: str,
        started_at: str,
        terminal_at: str,
        records: Iterable[dict[str, Any]],
        gap_code: str | None = None,
    ) -> dict[str, Any]:
        if self.read_only or self.version != REPOSITORY_VERSION:
            raise ObservationError("current writable repository required")
        if state not in TERMINAL_RUN_STATES:
            raise ObservationError("run state must be completed, partial, or failed")
        if source_id not in registry.sources:
            raise ObservationError("source is not in the active registry")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ObservationError("sequence must be a positive integer")
        run_id = _required_text({"runId": run_id}, "runId")
        started_at, started_epoch = _utc_timestamp({"startedAt": started_at}, "startedAt")
        terminal_at, terminal_epoch = _utc_timestamp({"terminalAt": terminal_at}, "terminalAt")
        if terminal_epoch < started_epoch:
            raise ObservationError("terminalAt cannot precede startedAt")
        if state == "completed" and gap_code is not None:
            raise ObservationError("completed runs cannot carry a gap")
        if state != "completed" and not gap_code:
            raise ObservationError("partial and failed runs require a gap code")
        normalized, byte_count, snapshot_digest = normalize_records(registry.sources[source_id], records)
        if state == "failed" and normalized:
            raise ObservationError("failed runs cannot contain observations")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            duplicate = self.connection.execute(
                "SELECT 1 FROM collection_runs WHERE run_id=? OR (source_id=? AND sequence=?)",
                (run_id, source_id, sequence),
            ).fetchone()
            if duplicate is not None:
                raise ObservationError("run ID and source sequence must be unique")
            source_row = self.connection.execute(
                "SELECT active,current_run_id FROM sources WHERE source_id=?", (source_id,)
            ).fetchone()
            if source_row is None or not source_row["active"]:
                raise ObservationError("source registry has not been synchronized")
            self.connection.execute(
                """INSERT INTO collection_runs(
                       run_id,source_id,sequence,repository_version,source_schema_version,protocol_version,
                       registry_digest,state,started_at,terminal_at,record_count,byte_count,
                       snapshot_digest,gap_code,superseded_by)
                   VALUES(?,?,?,?,?,?,?,'collecting',?,NULL,0,0,NULL,NULL,NULL)""",
                (
                    run_id, source_id, sequence, REPOSITORY_VERSION,
                    registry.sources[source_id].schema_version,
                    registry.sources[source_id].protocol_version,
                    digest(registry.sources[source_id].as_registry_record()),
                    started_at,
                ),
            )
            for record in normalized:
                self.connection.execute(
                    """INSERT INTO observations(
                           source_id,run_id,record_version,resource_kind,native_id,observed_at,attributes_json,provenance_json)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        source_id, run_id, record["schemaVersion"], record["resourceKind"], record["nativeId"], record["observedAt"],
                        canonical_bytes(record["attributes"]).decode().strip(),
                        canonical_bytes(record["provenance"]).decode().strip(),
                    ),
                )
            self.connection.execute(
                """UPDATE collection_runs SET state=?,terminal_at=?,record_count=?,byte_count=?,
                     snapshot_digest=?,gap_code=? WHERE run_id=?""",
                (state, terminal_at, len(normalized), byte_count, snapshot_digest, gap_code, run_id),
            )
            became_current = False
            if state == "completed":
                current = self.connection.execute(
                    """SELECT r.run_id,r.sequence FROM sources s LEFT JOIN collection_runs r
                       ON r.run_id=s.current_run_id WHERE s.source_id=?""", (source_id,)
                ).fetchone()
                if current is None or current["run_id"] is None or sequence > current["sequence"]:
                    if current is not None and current["run_id"] is not None:
                        self.connection.execute(
                            "UPDATE collection_runs SET superseded_by=? WHERE run_id=?",
                            (run_id, current["run_id"]),
                        )
                    self.connection.execute(
                        "UPDATE sources SET current_run_id=? WHERE source_id=?", (run_id, source_id)
                    )
                    became_current = True
                else:
                    self.connection.execute(
                        "UPDATE collection_runs SET superseded_by=? WHERE run_id=?",
                        (current["run_id"], run_id),
                    )
            self._enforce_size()
            self.connection.commit()
        except ObservationError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise ObservationError("observation run transaction failed") from exc
        return {
            "runId": run_id,
            "sourceId": source_id,
            "state": state,
            "recordCount": len(normalized),
            "byteCount": byte_count,
            "snapshotDigest": snapshot_digest,
            "becameCurrent": became_current,
        }

    def recover_interrupted(self, *, terminal_at: str) -> int:
        if self.read_only or self.version != REPOSITORY_VERSION:
            raise ObservationError("current writable repository required")
        terminal_at, _terminal_epoch = _utc_timestamp({"terminalAt": terminal_at}, "terminalAt")
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE collection_runs SET state='failed',terminal_at=?,gap_code='restart-interrupted'
                   WHERE state='collecting'""",
                (terminal_at,),
            )
        return cursor.rowcount

    def coverage(self, registry: SourceRegistry, *, explicit_clock_epoch: int) -> dict[str, Any]:
        if not isinstance(explicit_clock_epoch, int) or isinstance(explicit_clock_epoch, bool) or explicit_clock_epoch < 0:
            raise ObservationError("explicit clock epoch must be non-negative")
        gaps = registry.configuration_gaps()
        sources: list[dict[str, Any]] = []
        for source_id in sorted(registry.sources):
            source = registry.sources[source_id]
            exclusion = source.exclusion
            current = self.connection.execute(
                """SELECT r.run_id,r.sequence,r.state,r.terminal_at,r.registry_digest FROM sources s
                   LEFT JOIN collection_runs r ON r.run_id=s.current_run_id WHERE s.source_id=?""",
                (source_id,),
            ).fetchone()
            latest = self.connection.execute(
                """SELECT run_id,sequence,state,terminal_at,gap_code,registry_digest
                   FROM collection_runs WHERE source_id=? ORDER BY sequence DESC LIMIT 1""",
                (source_id,),
            ).fetchone()
            current_run_id = current["run_id"] if current is not None else None
            latest_run_id = latest["run_id"] if latest is not None else None
            if exclusion is not None:
                try:
                    expiry = int(datetime.fromisoformat(exclusion["expiresAt"].replace("Z", "+00:00")).timestamp())
                except ValueError as exc:
                    raise ObservationError("exclusion expiry is invalid") from exc
                if expiry <= explicit_clock_epoch:
                    state = "never_observed"
                    gaps.append({"kind": "expired-exclusion", "sourceId": source_id})
                else:
                    state = "excluded"
                sources.append({
                    "sourceId": source_id,
                    "state": state,
                    "currentRunId": current_run_id,
                    "latestRunId": latest_run_id,
                    "exclusion": exclusion,
                })
                continue
            if latest is not None and latest["state"] in {"partial", "failed"}:
                state = "failed"
                gaps.append({
                    "kind": "collection-gap",
                    "sourceId": source_id,
                    "runId": latest_run_id,
                    "runState": latest["state"],
                    "gapCode": latest["gap_code"],
                })
            elif current is None or current_run_id is None:
                state = "never_observed"
                gaps.append({"kind": "never-observed", "sourceId": source_id})
            elif current["registry_digest"] != digest(source.as_registry_record()):
                state = "failed"
                gaps.append({
                    "kind": "source-contract-changed",
                    "sourceId": source_id,
                    "runId": current_run_id,
                })
            else:
                try:
                    terminal_epoch = int(datetime.fromisoformat(current["terminal_at"].replace("Z", "+00:00")).timestamp())
                except (TypeError, ValueError) as exc:
                    raise ObservationError("stored terminal timestamp is invalid") from exc
                state = "fresh" if explicit_clock_epoch - terminal_epoch <= source.freshness_slo_seconds else "stale"
                if state == "stale":
                    gaps.append({"kind": "source-stale", "sourceId": source_id, "runId": current_run_id})
            sources.append({
                "sourceId": source_id,
                "state": state,
                "currentRunId": current_run_id,
                "latestRunId": latest_run_id,
                "exclusion": None,
            })
        fresh = sum(item["state"] == "fresh" for item in sources)
        configured = len(sources)
        status = "not-configured" if configured == 0 else ("complete" if fresh == configured and not gaps else "incomplete")
        return {
            "schemaVersion": 1,
            "status": status,
            "configuredSources": configured,
            "freshSources": fresh,
            "sources": sources,
            "gaps": sorted(gaps, key=canonical_bytes),
            "registryDigest": registry.registry_digest,
        }

    def current_snapshot(self, source_id: str) -> list[dict[str, Any]]:
        source = self.connection.execute(
            "SELECT 1 FROM sources WHERE source_id=?", (source_id,)
        ).fetchone()
        if source is None:
            raise ObservationError("observation source is unknown")
        rows = self.connection.execute(
            """SELECT o.record_version,o.resource_kind,o.native_id,o.observed_at,o.attributes_json,o.provenance_json
               FROM sources s JOIN observations o ON o.run_id=s.current_run_id
               WHERE s.source_id=? ORDER BY o.resource_kind,o.native_id""",
            (source_id,),
        ).fetchall()
        return [
            {
                "schemaVersion": row["record_version"],
                "resourceKind": row["resource_kind"],
                "nativeId": row["native_id"],
                "observedAt": row["observed_at"],
                "attributes": json.loads(row["attributes_json"]),
                "provenance": json.loads(row["provenance_json"]),
            }
            for row in rows
        ]

    def prune(
        self,
        *,
        keep_completed: int = DEFAULT_KEEP_COMPLETED_RUNS,
        keep_failed: int = DEFAULT_KEEP_FAILED_RUNS,
    ) -> int:
        if self.read_only or self.version != REPOSITORY_VERSION:
            raise ObservationError("current writable repository required")
        if keep_completed < 2 or keep_failed < 1:
            raise ObservationError("retention must keep current plus rollback and one failed run")
        delete_ids: list[str] = []
        for source_id, in self.connection.execute("SELECT source_id FROM sources"):
            current = self.connection.execute(
                "SELECT current_run_id FROM sources WHERE source_id=?", (source_id,)
            ).fetchone()[0]
            completed = [row[0] for row in self.connection.execute(
                "SELECT run_id FROM collection_runs WHERE source_id=? AND state='completed' ORDER BY sequence DESC",
                (source_id,),
            )]
            failed = [row[0] for row in self.connection.execute(
                "SELECT run_id FROM collection_runs WHERE source_id=? AND state IN ('partial','failed') ORDER BY sequence DESC",
                (source_id,),
            )]
            delete_ids.extend(run_id for run_id in completed[keep_completed:] if run_id != current)
            delete_ids.extend(failed[keep_failed:])
        linked = {
            row[0] for row in self.connection.execute("SELECT DISTINCT run_id FROM reconciliation_links")
        }
        delete_ids = [run_id for run_id in delete_ids if run_id not in linked]
        with self.connection:
            for run_id in sorted(set(delete_ids)):
                self.connection.execute("DELETE FROM collection_runs WHERE run_id=?", (run_id,))
        self.connection.execute("PRAGMA incremental_vacuum")
        self._enforce_size()
        return len(set(delete_ids))


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
