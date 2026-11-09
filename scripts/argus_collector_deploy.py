"""Install the reviewed D1–D5 collector estate with reversible host changes.

The module keeps deployment mechanics separate from collector execution.  It
only writes reviewed systemd units and one-source registry projections; the
central refresh service remains the sole reader of collector sockets.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from argus_estate_refresh import read_status
from argus_observations import ObservationError, SourceRegistry, SourceSpec, load_registry


CANONICAL_ROOT = Path("/srv/argus")
CONTROL_GROUP = "argus-control"
CONTROL_GID = 981
CLIENT_USER = "oreo"
CLIENT_UID = 1000
DOCKER_GROUP = "docker"
DOCKER_GID = 983
ROOTFUL_COLLECTOR_USER = "argus-collector-rootful"
ROOTFUL_COLLECTOR_UID = 950
APPLY_ACKNOWLEDGEMENT = "--acknowledge-estate-collectors"
ROLLBACK_ACKNOWLEDGEMENT = "--acknowledge-estate-collectors-rollback"

ROOTFUL_SOURCE = "oreochiserver.rootful-docker"
ROOTLESS_DOMAINS = ("personal-sandbox", "work-sandbox", "personal-managed")
SCHEDULE_USERS = (
    ("oreo", "oreo"),
    ("personal-sandbox", "argus-personal-sandbox"),
    ("work-sandbox", "argus-work-sandbox"),
)
OPTIONAL_SOURCES = ("configured-roots", "process-listeners", "proxy-overlay")

UNIT_NAMES = (
    "argus-rootful-docker-collector.service",
    "argus-rootless-docker-collector@.service",
    "argus-system-schedules-collector.service",
    "argus-user-schedules-collector-oreo.service",
    "argus-user-schedules-collector-personal-sandbox.service",
    "argus-user-schedules-collector-work-sandbox.service",
    "argus-optional-evidence-collector@.service",
    "argus-estate-refresh.service",
    "argus-estate-refresh.timer",
)

COLLECTOR_SERVICES = (
    "argus-rootful-docker-collector.service",
    *(f"argus-rootless-docker-collector@{domain}.service" for domain in ROOTLESS_DOMAINS),
    "argus-system-schedules-collector.service",
    *(f"argus-user-schedules-collector-{name}.service" for name, _user in SCHEDULE_USERS),
    *(f"argus-optional-evidence-collector@{name}.service" for name in OPTIONAL_SOURCES),
)
REFRESH_TIMER = "argus-estate-refresh.timer"
REFRESH_SERVICE = "argus-estate-refresh.service"


class CollectorDeploymentError(RuntimeError):
    """A stable, redacted deployment refusal."""


@dataclass(frozen=True)
class ManagedFile:
    path: Path
    content: bytes
    mode: int
    uid: int
    gid: int


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def deployment_paths() -> dict[str, Path]:
    return {
        "systemd": Path("/etc/systemd/system"),
        "collectorConfig": Path("/etc/argus/collectors"),
        "backupRoot": Path("/var/backups/argus-estate-collectors"),
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def expected_source_ids() -> set[str]:
    return {
        ROOTFUL_SOURCE,
        *(f"oreochiserver.{domain}.rootless-docker" for domain in ROOTLESS_DOMAINS),
        "oreochiserver.system-schedules",
        *(f"oreochiserver.user-schedules-{name}" for name, _user in SCHEDULE_USERS),
        *(f"oreochiserver.{name}" for name in OPTIONAL_SOURCES),
    }


def validate_registry(root: Path) -> SourceRegistry:
    try:
        registry = load_registry(root / "config" / "argus" / "observation-sources.json", root)
    except (ObservationError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise CollectorDeploymentError("reviewed observation source registry is unavailable or invalid") from exc
    expected = expected_source_ids()
    if set(registry.sources) != expected or set(registry.host_sources) != expected:
        raise CollectorDeploymentError("reviewed source registry does not contain the exact D1–D5 source set")
    for source_id in sorted(expected):
        source = registry.sources[source_id]
        transport = source.transport
        if (
            transport is None
            or source.execution_identity.get("gid") != CONTROL_GID
            or transport.get("parentGid") != CONTROL_GID
            or transport.get("socketGid") != CONTROL_GID
            or transport.get("peerGid") != CONTROL_GID
            or transport.get("parentMode") != "0750"
            or transport.get("socketMode") != "0660"
            or transport.get("socketUid") != source.execution_identity.get("uid")
            or transport.get("peerUid") != source.execution_identity.get("uid")
        ):
            raise CollectorDeploymentError("reviewed source registry has an incompatible collector binding")
    return registry


def source_projection(registry: SourceRegistry, source_id: str) -> dict[str, Any]:
    source = registry.sources.get(source_id)
    if source is None or source_id not in registry.host_sources:
        raise CollectorDeploymentError("reviewed source projection is unavailable")
    return {
        "schemaVersion": registry.schema_version,
        "hostSources": [source_id],
        "sources": [source.as_registry_record()],
    }


def projection_bytes(registry: SourceRegistry, source_id: str) -> bytes:
    return _json_bytes(source_projection(registry, source_id))


def _rootless_socket(source: SourceSpec) -> Path:
    domain = source.source_id.removeprefix("oreochiserver.").removesuffix(".rootless-docker")
    if domain not in ROOTLESS_DOMAINS:
        raise CollectorDeploymentError("rootless collector domain is not reviewed")
    return Path("/var/lib/argus") / domain / "docker.sock"


def _lstat_regular(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CollectorDeploymentError("managed deployment file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CollectorDeploymentError("managed deployment file is not a regular file")
    return metadata


def rootless_environment(source: SourceSpec, *, socket_gid: int, daemon_gid: int) -> bytes:
    uid = source.execution_identity.get("uid")
    if not isinstance(uid, int) or uid < 0 or not isinstance(socket_gid, int) or socket_gid < 0:
        raise CollectorDeploymentError("rootless Docker binding is invalid")
    if not isinstance(daemon_gid, int) or daemon_gid < 0:
        raise CollectorDeploymentError("rootless Docker daemon identity is invalid")
    return (
        f"ARGUS_DOCKER_SOCKET_UID={uid}\n"
        f"ARGUS_DOCKER_SOCKET_GID={socket_gid}\n"
        "ARGUS_DOCKER_SOCKET_MODE=0660\n"
        f"ARGUS_DOCKER_DAEMON_UID={uid}\n"
        f"ARGUS_DOCKER_DAEMON_GID={daemon_gid}\n"
    ).encode("ascii")


def _checked_rootless_environment(source: SourceSpec) -> bytes:
    socket_path = _rootless_socket(source)
    try:
        metadata = socket_path.lstat()
    except OSError as exc:
        raise CollectorDeploymentError("rootless Docker socket is unavailable") from exc
    expected_uid = source.execution_identity["uid"]
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) != 0o660
    ):
        raise CollectorDeploymentError("rootless Docker socket binding is incompatible")
    try:
        daemon_gid = pwd.getpwuid(expected_uid).pw_gid
    except KeyError as exc:
        raise CollectorDeploymentError("rootless Docker account is unavailable") from exc
    return rootless_environment(source, socket_gid=metadata.st_gid, daemon_gid=daemon_gid)


def expected_files(root: Path, registry: SourceRegistry, *, live_bindings: bool) -> list[ManagedFile]:
    paths = deployment_paths()
    try:
        control_gid = grp.getgrnam(CONTROL_GROUP).gr_gid
    except KeyError:
        control_gid = CONTROL_GID
    if control_gid != CONTROL_GID:
        raise CollectorDeploymentError("argus-control group identity is incompatible")
    files: list[ManagedFile] = []
    for name in UNIT_NAMES:
        source = root / "systemd" / name
        metadata = _lstat_regular(source)
        if metadata.st_size <= 0 or metadata.st_size > 128 * 1024:
            raise CollectorDeploymentError("reviewed systemd unit exceeds deployment bounds")
        files.append(
            ManagedFile(paths["systemd"] / name, source.read_bytes(), 0o644, 0, 0)
        )

    config_root = paths["collectorConfig"]
    source_paths: list[tuple[str, Path]] = [
        (ROOTFUL_SOURCE, config_root / "rootful-docker-source.json"),
        ("oreochiserver.system-schedules", config_root / "system-schedules-source.json"),
    ]
    source_paths.extend(
        (f"oreochiserver.{domain}.rootless-docker", config_root / f"{domain}-rootless-docker-source.json")
        for domain in ROOTLESS_DOMAINS
    )
    source_paths.extend(
        (f"oreochiserver.user-schedules-{name}", config_root / f"user-schedules-{name}-source.json")
        for name, _user in SCHEDULE_USERS
    )
    source_paths.extend(
        (f"oreochiserver.{name}", config_root / "optional" / f"{name}.json")
        for name in OPTIONAL_SOURCES
    )
    for source_id, target in source_paths:
        files.append(ManagedFile(target, projection_bytes(registry, source_id), 0o640, 0, control_gid))
    for domain in ROOTLESS_DOMAINS:
        source = registry.sources[f"oreochiserver.{domain}.rootless-docker"]
        environment = _checked_rootless_environment(source) if live_bindings else rootless_environment(
            source,
            socket_gid=source.execution_identity["gid"],
            daemon_gid=source.execution_identity["uid"],
        )
        files.append(
            ManagedFile(config_root / f"{domain}-rootless-docker.env", environment, 0o640, 0, control_gid)
        )
    return files


def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectorDeploymentError("required host command is unavailable") from exc
    if check and result.returncode != 0:
        raise CollectorDeploymentError("required host command rejected the reviewed deployment")
    return result


def _service_active(service: str) -> bool:
    return _run(["systemctl", "is-active", "--quiet", service], check=False).returncode == 0


def _service_enabled(service: str) -> bool:
    return _run(["systemctl", "is-enabled", "--quiet", service], check=False).returncode == 0


def _require_root() -> None:
    if os.geteuid() != 0:
        raise CollectorDeploymentError("run this deployment with sudo")


def _account(name: str, uid: int | None = None) -> pwd.struct_passwd:
    try:
        result = pwd.getpwnam(name)
    except KeyError as exc:
        raise CollectorDeploymentError("required collector account is unavailable") from exc
    if uid is not None and result.pw_uid != uid:
        raise CollectorDeploymentError("collector account identity is incompatible")
    return result


def _validate_live_identities(registry: SourceRegistry, *, permit_missing_rootful: bool) -> None:
    try:
        control = grp.getgrnam(CONTROL_GROUP)
        docker = grp.getgrnam(DOCKER_GROUP)
    except KeyError as exc:
        raise CollectorDeploymentError("required collector group is unavailable") from exc
    if control.gr_gid != CONTROL_GID or docker.gr_gid != DOCKER_GID:
        raise CollectorDeploymentError("collector group identity is incompatible")
    _account(CLIENT_USER, CLIENT_UID)
    for domain in ROOTLESS_DOMAINS:
        source = registry.sources[f"oreochiserver.{domain}.rootless-docker"]
        account = _account(f"argus-{domain}", source.execution_identity["uid"])
        if account.pw_gid != source.execution_identity["uid"]:
            raise CollectorDeploymentError("rootless collector account group is incompatible")
    try:
        rootful = pwd.getpwnam(ROOTFUL_COLLECTOR_USER)
    except KeyError:
        rootful = None
    if rootful is None:
        if not permit_missing_rootful:
            raise CollectorDeploymentError("rootful collector account is unavailable")
        try:
            occupied = pwd.getpwuid(ROOTFUL_COLLECTOR_UID)
        except KeyError:
            return
        raise CollectorDeploymentError("rootful collector UID is already occupied")
    if rootful.pw_uid != ROOTFUL_COLLECTOR_UID or rootful.pw_gid != CONTROL_GID:
        raise CollectorDeploymentError("rootful collector account identity is incompatible")
    members = set(os.getgrouplist(ROOTFUL_COLLECTOR_USER, rootful.pw_gid))
    if DOCKER_GID not in members:
        raise CollectorDeploymentError("rootful collector Docker group is unavailable")


def _validate_live_sockets(registry: SourceRegistry) -> None:
    try:
        docker_metadata = Path("/var/run/docker.sock").lstat()
    except OSError as exc:
        raise CollectorDeploymentError("rootful Docker socket is unavailable") from exc
    if (
        stat.S_ISLNK(docker_metadata.st_mode)
        or not stat.S_ISSOCK(docker_metadata.st_mode)
        or docker_metadata.st_uid != 0
        or docker_metadata.st_gid != DOCKER_GID
        or stat.S_IMODE(docker_metadata.st_mode) != 0o660
    ):
        raise CollectorDeploymentError("rootful Docker socket binding is incompatible")
    for domain in ROOTLESS_DOMAINS:
        _checked_rootless_environment(registry.sources[f"oreochiserver.{domain}.rootless-docker"])


def preflight(root: Path, *, permit_missing_rootful: bool = True) -> dict[str, Any]:
    _require_root()
    root = root.resolve()
    if root != CANONICAL_ROOT:
        raise CollectorDeploymentError("collector deployment only accepts the canonical /srv/argus checkout")
    for command in ("systemctl", "systemd-analyze", "useradd", "userdel", "pgrep"):
        if shutil.which(command) is None:
            raise CollectorDeploymentError("required deployment command is unavailable")
    registry = validate_registry(root)
    expected_files(root, registry, live_bindings=True)
    _validate_live_identities(registry, permit_missing_rootful=permit_missing_rootful)
    _validate_live_sockets(registry)
    for name in UNIT_NAMES:
        _run(["systemd-analyze", "verify", str(root / "systemd" / name)])
    return {
        "schemaVersion": 1,
        "ok": True,
        "sources": len(registry.sources),
        "services": len(COLLECTOR_SERVICES),
        "rootfulCollectorAccountPresent": not permit_missing_rootful,
    }


def _ensure_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    if os.path.lexists(path):
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CollectorDeploymentError("managed deployment directory is unavailable") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != uid
            or metadata.st_gid != gid
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise CollectorDeploymentError("managed deployment directory has an unsafe binding")
        return
    path.mkdir(mode=mode, parents=False)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def _prepare_directories(files: list[ManagedFile]) -> None:
    paths = deployment_paths()
    config_root = paths["collectorConfig"]
    parent = config_root.parent
    try:
        parent_metadata = parent.lstat()
    except OSError as exc:
        raise CollectorDeploymentError("Argus configuration parent is unavailable") from exc
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise CollectorDeploymentError("Argus configuration parent has an unsafe binding")
    _ensure_directory(config_root, uid=0, gid=CONTROL_GID, mode=0o750)
    _ensure_directory(config_root / "optional", uid=0, gid=CONTROL_GID, mode=0o750)
    systemd = paths["systemd"]
    try:
        metadata = systemd.lstat()
    except OSError as exc:
        raise CollectorDeploymentError("systemd unit directory is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CollectorDeploymentError("systemd unit directory has an unsafe binding")
    for item in files:
        if item.path.parent not in {systemd, config_root, config_root / "optional"}:
            raise CollectorDeploymentError("managed file target is outside the reviewed deployment roots")


def _atomic_install(item: ManagedFile) -> None:
    if os.path.lexists(item.path):
        _lstat_regular(item.path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{item.path.name}.", dir=item.path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(item.content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, item.uid, item.gid)
        os.chmod(temporary, item.mode)
        os.replace(temporary, item.path)
        os.chown(item.path, item.uid, item.gid)
        os.chmod(item.path, item.mode)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _backup(files: list[ManagedFile]) -> Path:
    backup_root = deployment_paths()["backupRoot"]
    if os.path.lexists(backup_root):
        metadata = backup_root.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise CollectorDeploymentError("collector backup root has an unsafe binding")
    else:
        backup_root.mkdir(mode=0o700, parents=True)
        os.chown(backup_root, 0, 0)
        os.chmod(backup_root, 0o700)
    backup = backup_root / utc_stamp()
    suffix = 0
    while os.path.lexists(backup):
        suffix += 1
        backup = backup_root / f"{utc_stamp()}-{suffix}"
    backup.mkdir(mode=0o700)
    records: list[dict[str, Any]] = []
    files_directory = backup / "files"
    files_directory.mkdir(mode=0o700)
    for index, item in enumerate(files):
        record: dict[str, Any] = {"path": str(item.path), "expected": item.content.decode("utf-8"), "mode": item.mode, "uid": item.uid, "gid": item.gid}
        if os.path.lexists(item.path):
            metadata = _lstat_regular(item.path)
            target = files_directory / f"{index:03d}"
            shutil.copyfile(item.path, target)
            os.chown(target, 0, 0)
            os.chmod(target, 0o600)
            record.update({
                "exists": True,
                "backup": str(target.relative_to(backup)),
                "priorMode": stat.S_IMODE(metadata.st_mode),
                "priorUid": metadata.st_uid,
                "priorGid": metadata.st_gid,
            })
        else:
            record["exists"] = False
        records.append(record)
    metadata = {
        "schemaVersion": 1,
        "createdAt": utc_stamp(),
        "files": records,
        "services": {
            service: {"active": _service_active(service), "enabled": _service_enabled(service)}
            for service in (*COLLECTOR_SERVICES, REFRESH_TIMER)
        },
        "rootfulCollectorCreated": False,
    }
    metadata_path = backup / "metadata.json"
    metadata_path.write_bytes(_json_bytes(metadata))
    os.chown(metadata_path, 0, 0)
    os.chmod(metadata_path, 0o600)
    return backup


def _update_backup(backup: Path, **updates: Any) -> None:
    metadata_path = backup / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(updates)
    descriptor, temporary = tempfile.mkstemp(prefix=".metadata.", dir=backup)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_json_bytes(metadata))
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, 0o600)
        os.replace(temporary, metadata_path)
        os.chown(metadata_path, 0, 0)
        os.chmod(metadata_path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_backup(backup: Path) -> dict[str, Any]:
    root = deployment_paths()["backupRoot"].resolve()
    try:
        resolved = backup.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as exc:
        raise CollectorDeploymentError("collector rollback backup is unavailable") from exc
    if (
        root not in (resolved, *resolved.parents)
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CollectorDeploymentError("collector rollback backup is unsafe")
    metadata_path = resolved / "metadata.json"
    file_metadata = _lstat_regular(metadata_path)
    if file_metadata.st_uid != 0 or file_metadata.st_gid != 0 or stat.S_IMODE(file_metadata.st_mode) != 0o600:
        raise CollectorDeploymentError("collector rollback metadata is unsafe")
    try:
        result = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorDeploymentError("collector rollback metadata is invalid") from exc
    if (
        not isinstance(result, dict)
        or result.get("schemaVersion") != 1
        or not isinstance(result.get("files"), list)
        or not isinstance(result.get("services"), dict)
    ):
        raise CollectorDeploymentError("collector rollback metadata has an invalid shape")
    result["_path"] = resolved
    return result


def _ensure_rootful_account() -> bool:
    try:
        account = pwd.getpwnam(ROOTFUL_COLLECTOR_USER)
    except KeyError:
        try:
            pwd.getpwuid(ROOTFUL_COLLECTOR_UID)
        except KeyError:
            pass
        else:
            raise CollectorDeploymentError("rootful collector UID is already occupied")
        _run([
            "useradd", "--system", "--uid", str(ROOTFUL_COLLECTOR_UID), "--gid", CONTROL_GROUP,
            "--groups", DOCKER_GROUP, "--home-dir", "/nonexistent", "--no-create-home",
            "--shell", "/usr/sbin/nologin", ROOTFUL_COLLECTOR_USER,
        ])
        return True
    if account.pw_uid != ROOTFUL_COLLECTOR_UID or account.pw_gid != CONTROL_GID:
        raise CollectorDeploymentError("rootful collector account identity is incompatible")
    if DOCKER_GID not in set(os.getgrouplist(ROOTFUL_COLLECTOR_USER, account.pw_gid)):
        raise CollectorDeploymentError("rootful collector Docker group is unavailable")
    return False


def _verify_file(item: ManagedFile) -> None:
    metadata = _lstat_regular(item.path)
    if (
        metadata.st_uid != item.uid
        or metadata.st_gid != item.gid
        or stat.S_IMODE(metadata.st_mode) != item.mode
        or item.path.read_bytes() != item.content
    ):
        raise CollectorDeploymentError("installed collector file does not match the reviewed deployment")


def _verify_socket(source: SourceSpec) -> None:
    transport = source.transport
    if transport is None:
        raise CollectorDeploymentError("collector transport is unavailable")
    parent = Path(str(transport["parentPath"]))
    socket_path = Path(str(transport["socketPath"]))
    try:
        parent_metadata = parent.lstat()
        socket_metadata = socket_path.lstat()
    except OSError as exc:
        raise CollectorDeploymentError("collector socket is unavailable") from exc
    if (
        stat.S_ISLNK(parent_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != transport["parentUid"]
        or parent_metadata.st_gid != transport["parentGid"]
        or stat.S_IMODE(parent_metadata.st_mode) != int(transport["parentMode"], 8)
        or stat.S_ISLNK(socket_metadata.st_mode)
        or not stat.S_ISSOCK(socket_metadata.st_mode)
        or socket_metadata.st_uid != transport["socketUid"]
        or socket_metadata.st_gid != transport["socketGid"]
        or stat.S_IMODE(socket_metadata.st_mode) != int(transport["socketMode"], 8)
    ):
        raise CollectorDeploymentError("collector socket binding is incompatible")


def _service_identity(service: str) -> tuple[str, str]:
    user = _run(["systemctl", "show", service, "-p", "User", "--value"]).stdout.strip()
    group = _run(["systemctl", "show", service, "-p", "Group", "--value"]).stdout.strip()
    return user, group


def status(root: Path, *, require_refresh: bool = False) -> dict[str, Any]:
    _require_root()
    root = root.resolve()
    registry = validate_registry(root)
    preflight(root, permit_missing_rootful=False)
    files = expected_files(root, registry, live_bindings=True)
    for item in files:
        _verify_file(item)
    expected_identities = {
        "argus-rootful-docker-collector.service": (ROOTFUL_COLLECTOR_USER, CONTROL_GROUP),
        "argus-system-schedules-collector.service": (CLIENT_USER, CONTROL_GROUP),
        **{f"argus-rootless-docker-collector@{domain}.service": (f"argus-{domain}", CONTROL_GROUP) for domain in ROOTLESS_DOMAINS},
        **{f"argus-user-schedules-collector-{name}.service": (user, CONTROL_GROUP) for name, user in SCHEDULE_USERS},
        **{f"argus-optional-evidence-collector@{name}.service": (CLIENT_USER, CONTROL_GROUP) for name in OPTIONAL_SOURCES},
    }
    for service in COLLECTOR_SERVICES:
        if not _service_enabled(service) or not _service_active(service):
            raise CollectorDeploymentError("reviewed collector service is not active and enabled")
        if _service_identity(service) != expected_identities[service]:
            raise CollectorDeploymentError("reviewed collector service identity is incompatible")
    if not _service_enabled(REFRESH_TIMER) or not _service_active(REFRESH_TIMER):
        raise CollectorDeploymentError("estate refresh timer is not active and enabled")
    for source in registry.sources.values():
        _verify_socket(source)
    refresh = read_status(root)
    if require_refresh and (
        refresh is None
        or refresh.get("state") not in {"completed", "partial"}
        or not isinstance(refresh.get("collection"), dict)
        or len(refresh["collection"].get("sources", [])) != len(registry.sources)
    ):
        raise CollectorDeploymentError("estate refresh did not produce a complete terminal source report")
    return {
        "schemaVersion": 1,
        "ok": True,
        "sources": len(registry.sources),
        "services": len(COLLECTOR_SERVICES),
        "refresh": refresh or {"state": "never-run", "safeToMoveWorkloads": False},
    }


def _restore_file(record: dict[str, Any], backup: Path) -> None:
    raw_path = record.get("path")
    expected = record.get("expected")
    if not isinstance(raw_path, str) or not isinstance(expected, str):
        raise CollectorDeploymentError("collector rollback file record is invalid")
    path = Path(raw_path)
    allowed_roots = (Path("/etc/systemd/system"), Path("/etc/argus/collectors"))
    if not any(path.parent == root or root in path.parents for root in allowed_roots):
        raise CollectorDeploymentError("collector rollback file target is outside reviewed roots")
    if record.get("exists") is True:
        backup_name = record.get("backup")
        if not isinstance(backup_name, str):
            raise CollectorDeploymentError("collector rollback backup file is invalid")
        source = backup / backup_name
        metadata = _lstat_regular(source)
        if metadata.st_uid != 0 or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise CollectorDeploymentError("collector rollback backup file is unsafe")
        content = source.read_bytes()
        item = ManagedFile(
            path,
            content,
            int(record["priorMode"]),
            int(record["priorUid"]),
            int(record["priorGid"]),
        )
        _atomic_install(item)
        return
    if os.path.lexists(path):
        metadata = _lstat_regular(path)
        if metadata.st_uid != int(record["uid"]) or metadata.st_gid != int(record["gid"]) or path.read_bytes() != expected.encode("utf-8"):
            raise CollectorDeploymentError("refusing to remove collector file that changed after deployment")
        path.unlink()


def rollback(backup: Path) -> dict[str, Any]:
    _require_root()
    metadata = _read_backup(backup)
    resolved = metadata.pop("_path")
    for service in (*COLLECTOR_SERVICES, REFRESH_TIMER):
        _run(["systemctl", "disable", "--now", service], check=False)
    for record in metadata["files"]:
        if not isinstance(record, dict):
            raise CollectorDeploymentError("collector rollback file record is invalid")
        _restore_file(record, resolved)
    _run(["systemctl", "daemon-reload"])
    service_records = metadata["services"]
    for service in (*COLLECTOR_SERVICES, REFRESH_TIMER):
        prior = service_records.get(service)
        if not isinstance(prior, dict):
            raise CollectorDeploymentError("collector rollback service record is invalid")
        if prior.get("enabled") is True:
            _run(["systemctl", "enable", service])
        else:
            _run(["systemctl", "disable", service], check=False)
        if prior.get("active") is True:
            _run(["systemctl", "start", service])
    if metadata.get("rootfulCollectorCreated") is True:
        try:
            account = _account(ROOTFUL_COLLECTOR_USER, ROOTFUL_COLLECTOR_UID)
        except CollectorDeploymentError:
            account = None
        if account is not None:
            if _run(["pgrep", "-u", str(ROOTFUL_COLLECTOR_UID)], check=False).returncode == 0:
                raise CollectorDeploymentError("rootful collector account still owns a process; manual recovery required")
            _run(["userdel", ROOTFUL_COLLECTOR_USER])
    return {"schemaVersion": 1, "ok": True, "rolledBack": str(resolved)}


def apply(root: Path) -> dict[str, Any]:
    preflight(root, permit_missing_rootful=True)
    root = root.resolve()
    registry = validate_registry(root)
    files = expected_files(root, registry, live_bindings=True)
    backup = _backup(files)
    try:
        _prepare_directories(files)
        created = _ensure_rootful_account()
        _update_backup(backup, rootfulCollectorCreated=created)
        _validate_live_identities(registry, permit_missing_rootful=False)
        for item in files:
            _atomic_install(item)
        _run(["systemctl", "daemon-reload"])
        for service in COLLECTOR_SERVICES:
            _run(["systemctl", "enable", service])
            _run(["systemctl", "restart", service])
        _run(["systemctl", "enable", "--now", REFRESH_TIMER])
        _run(["systemctl", "start", REFRESH_SERVICE])
        deadline = time.monotonic() + 45
        while True:
            try:
                report = status(root, require_refresh=True)
                break
            except CollectorDeploymentError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        return {**report, "backup": str(backup)}
    except Exception as exc:
        try:
            rollback(backup)
        except CollectorDeploymentError as rollback_error:
            raise CollectorDeploymentError(
                "collector deployment failed and automatic rollback requires manual recovery"
            ) from rollback_error
        raise exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--preflight", action="store_true", help="validate the reviewed deployment without changing the host")
    actions.add_argument("--status", action="store_true", help="verify installed collectors and the latest refresh report")
    actions.add_argument("--apply", action="store_true", help="install and start reviewed collectors")
    actions.add_argument("--rollback", type=Path, metavar="BACKUP", help="restore one deployment backup")
    parser.add_argument(APPLY_ACKNOWLEDGEMENT, action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(ROLLBACK_ACKNOWLEDGEMENT, action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(os.environ.get("ARGUS_ROOT", CANONICAL_ROOT))
    try:
        if args.preflight:
            result = preflight(root)
        elif args.status:
            result = status(root)
        elif args.apply:
            if not getattr(args, APPLY_ACKNOWLEDGEMENT.removeprefix("--").replace("-", "_")):
                raise CollectorDeploymentError("explicit apply acknowledgement is required")
            result = apply(root)
        else:
            if not getattr(args, ROLLBACK_ACKNOWLEDGEMENT.removeprefix("--").replace("-", "_")):
                raise CollectorDeploymentError("explicit rollback acknowledgement is required")
            result = rollback(args.rollback)
    except CollectorDeploymentError as exc:
        print(f"ESTATE_COLLECTOR_DEPLOY_FAIL reason={exc}", file=os.sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
