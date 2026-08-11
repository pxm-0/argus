"""Bounded, read-only systemd and cron observations for one host account."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from argus_collectors import CollectorError, PageBuilder, _validate_request
from argus_ipc import MAX_FRAME_BYTES, encode_frame, receive_frame, send_frame
from argus_observations import (
    ObservationError,
    SourceRegistry,
    SourceSpec,
    canonical_bytes,
    digest,
    normalize_records,
)


PAGE_RECORD_BYTES = 48 * 1024
UNIT_NAME = re.compile(r"[A-Za-z0-9_.@%:+\\-]{1,255}\Z")
LEGACY_MARKERS = (
    "legacy",
    "oreo-",
    "docker-compose",
    "docker compose",
    "@reboot",
    "/home/oreo/",
    "hastur",
    "intake-os",
)
CRON_DIRECTORIES = ("cron.d", "cron.daily", "cron.hourly", "cron.weekly", "cron.monthly")
SCHEDULE_SOURCE_IDS = {
    "oreochiserver.system-schedules",
    "oreochiserver.user-schedules-oreo",
    "oreochiserver.user-schedules-personal-sandbox",
    "oreochiserver.user-schedules-work-sandbox",
}


class ScheduleCollectorError(CollectorError):
    """Stable failure from the systemd/cron source."""


def _native_id(kind: str, value: str) -> str:
    return "sha256:" + hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()


def _safe_text(value: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise ScheduleCollectorError("schedule-output-invalid")
    if any(ord(character) < 32 for character in value):
        raise ScheduleCollectorError("schedule-output-invalid")
    return value


def _unit(value: str) -> str:
    candidate = _safe_text(value, maximum=255)
    if UNIT_NAME.fullmatch(candidate) is None:
        raise ScheduleCollectorError("schedule-unit-invalid")
    return candidate


def _legacy_reference(value: str) -> bool:
    folded = value.casefold()
    return any(marker in folded for marker in LEGACY_MARKERS)


def _record(
    source: SourceSpec,
    kind: str,
    native_id: str,
    observed_at: str,
    attributes: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "resourceKind": kind,
        "nativeId": native_id,
        "observedAt": observed_at,
        "attributes": attributes,
        "provenance": {
            "adapter": "argus-systemd-schedule",
            "adapterVersion": "1",
            "ordinal": ordinal,
        },
    }


def _command_environment(source: SourceSpec) -> dict[str, str]:
    environment = {
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "SYSTEMD_COLORS": "0",
        "SYSTEMD_PAGER": "cat",
        "SYSTEMD_LESS": "FRX",
    }
    if "user-schedules-" in source.source_id:
        runtime_dir = f"/run/user/{source.execution_identity['uid']}"
        environment["XDG_RUNTIME_DIR"] = runtime_dir
        environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
    return environment


def _run_command(
    source: SourceSpec,
    argv: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> bytes:
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ScheduleCollectorError("schedule-command-invalid")
    command_runner = runner or subprocess.run
    try:
        result = command_runner(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_command_environment(source),
            timeout=source.bounds["timeoutMilliseconds"] / 1000,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScheduleCollectorError("schedule-command-unavailable") from exc
    if result.returncode != 0:
        raise ScheduleCollectorError("schedule-command-failed")
    payload = result.stdout
    if not isinstance(payload, bytes) or len(payload) > source.bounds["maxOutputBytes"]:
        raise ScheduleCollectorError("schedule-output-limit-exceeded")
    return payload


def _scope_args(source: SourceSpec) -> list[str]:
    return ["--user"] if "user-schedules-" in source.source_id else []


def _decode_lines(payload: bytes) -> list[str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScheduleCollectorError("schedule-output-invalid") from exc
    return text.splitlines()


def _enabled_units(source: SourceSpec, runner: Callable[..., subprocess.CompletedProcess[bytes]] | None) -> set[str]:
    payload = _run_command(
        source,
        ["systemctl", *_scope_args(source), "list-unit-files", "--type=service", "--no-legend", "--no-pager", "--plain"],
        runner=runner,
    )
    enabled: set[str] = set()
    for line in _decode_lines(payload):
        fields = line.split()
        if len(fields) < 2:
            continue
        name = _unit(fields[0])
        if fields[1] in {"enabled", "enabled-runtime"}:
            enabled.add(name)
    return enabled


def _systemd_records(
    source: SourceSpec,
    observed_at: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> list[dict[str, Any]]:
    enabled = _enabled_units(source, runner)
    services = _run_command(
        source,
        ["systemctl", *_scope_args(source), "list-units", "--all", "--type=service", "--no-legend", "--no-pager", "--plain"],
        runner=runner,
    )
    timers = _run_command(
        source,
        ["systemctl", *_scope_args(source), "list-timers", "--all", "--no-legend", "--no-pager", "--plain"],
        runner=runner,
    )
    records: list[dict[str, Any]] = []
    for line in _decode_lines(services):
        fields = line.split()
        if len(fields) < 4:
            continue
        name = _unit(fields[0])
        records.append(_record(
            source,
            "systemd-service",
            name,
            observed_at,
            {
                "name": name,
                "loadState": _safe_text(fields[1], maximum=32),
                "enabled": name in enabled,
                "legacyReference": _legacy_reference(name),
                "scope": "user" if "user-schedules-" in source.source_id else "system",
            },
            len(records),
        ))
    for line in _decode_lines(timers):
        fields = line.split()
        if len(fields) < 2:
            continue
        name = _unit(fields[-2])
        activates = _unit(fields[-1])
        records.append(_record(
            source,
            "systemd-timer",
            name,
            observed_at,
            {
                "name": name,
                "activates": activates,
                "legacyReference": _legacy_reference(f"{name} {activates}"),
                "scope": "user" if "user-schedules-" in source.source_id else "system",
            },
            len(records),
        ))
    return records


def _read_bounded(path: Path, maximum: int) -> str:
    try:
        with path.open("rb") as handle:
            payload = handle.read(maximum + 1)
    except OSError as exc:
        raise ScheduleCollectorError("cron-file-unavailable") from exc
    if len(payload) > maximum:
        raise ScheduleCollectorError("cron-file-too-large")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScheduleCollectorError("cron-file-invalid") from exc


def _cron_entry_records(
    source: SourceSpec,
    observed_at: str,
    *,
    location: str,
    text: str,
    owner: str | None,
    start_ordinal: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        schedule_class = "reboot" if line.casefold().startswith("@reboot") else "scheduled"
        attributes: dict[str, Any] = {
            "scope": "user" if owner is not None else "system",
            "location": location,
            "scheduleClass": schedule_class,
            "legacyReference": _legacy_reference(line),
        }
        if owner is not None:
            attributes["owner"] = owner
        records.append(_record(
            source,
            "cron-entry",
            _native_id("cron-entry", f"{location}\0{index}\0{line}"),
            observed_at,
            attributes,
            start_ordinal + len(records),
        ))
    return records


def _cron_file_record(
    source: SourceSpec,
    observed_at: str,
    *,
    path: Path,
    directory: str,
    text: str,
    start_ordinal: int,
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ScheduleCollectorError("cron-file-unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ScheduleCollectorError("cron-file-invalid")
    name = _safe_text(path.name, maximum=255)
    return _record(
        source,
        "cron-directory",
        _native_id("cron-file", f"{directory}\0{name}"),
        observed_at,
        {
            "directory": directory,
            "entryName": name,
            "mode": stat.S_IMODE(metadata.st_mode),
            "legacyReference": _legacy_reference(f"{name}\n{text}"),
        },
        start_ordinal,
    )


def _system_cron_records(source: SourceSpec, observed_at: str, root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    crontab = root / "etc" / "crontab"
    if crontab.is_file():
        text = _read_bounded(crontab, source.bounds["maxOutputBytes"])
        records.extend(_cron_entry_records(
            source, observed_at, location="/etc/crontab", text=text, owner=None, start_ordinal=len(records)
        ))
    for directory in CRON_DIRECTORIES:
        path = root / "etc" / directory
        if not path.is_dir():
            continue
        for entry in sorted(path.iterdir(), key=lambda item: item.name):
            if entry.name == ".placeholder" or entry.is_symlink():
                continue
            text = _read_bounded(entry, source.bounds["maxOutputBytes"])
            records.append(_cron_file_record(
                source,
                observed_at,
                path=entry,
                directory=f"/etc/{directory}",
                text=text,
                start_ordinal=len(records),
            ))
            if directory == "cron.d":
                records.extend(_cron_entry_records(
                    source,
                    observed_at,
                    location=f"/etc/{directory}/{entry.name}",
                    text=text,
                    owner=None,
                    start_ordinal=len(records),
                ))
    return records


def _user_cron_records(
    source: SourceSpec,
    observed_at: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> list[dict[str, Any]]:
    try:
        payload = _run_command(source, ["crontab", "-l"], runner=runner)
    except ScheduleCollectorError as exc:
        if exc.code == "schedule-command-failed":
            # `crontab -l` uses exit 1 for an intentionally empty user crontab.
            command_runner = runner or subprocess.run
            result = command_runner(
                ["crontab", "-l"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_command_environment(source),
                timeout=source.bounds["timeoutMilliseconds"] / 1000,
                check=False,
            )
            if result.returncode == 1 and b"no crontab for" in result.stderr.lower():
                return []
        raise
    try:
        owner = pwd.getpwuid(source.execution_identity["uid"]).pw_name
    except KeyError:
        # Fixture platforms do not necessarily carry the server's pinned UIDs.
        owner = source.source_id.removeprefix("oreochiserver.user-schedules-")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScheduleCollectorError("cron-output-invalid") from exc
    return _cron_entry_records(
        source, observed_at, location="user-crontab", text=text, owner=owner, start_ordinal=0
    )


def collect_records(
    source: SourceSpec,
    request: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    root: Path = Path("/"),
) -> list[dict[str, Any]]:
    observed_at = request["explicitClock"]
    records = _systemd_records(source, observed_at, runner=runner)
    if source.source_id == "oreochiserver.system-schedules":
        records.extend(_system_cron_records(source, observed_at, root))
    else:
        records.extend(_user_cron_records(source, observed_at, runner=runner))
    records.sort(key=lambda item: (item["resourceKind"], item["nativeId"]))
    for ordinal, record in enumerate(records):
        record["provenance"]["ordinal"] = ordinal
    normalized, _byte_count, _snapshot_digest = normalize_records(source, records)
    return normalized


def build_pages(
    source: SourceSpec,
    request: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    state: str = "completed",
    gap_code: str | None = None,
) -> list[dict[str, Any]]:
    normalized, _bytes, _snapshot = normalize_records(source, records)
    builder = PageBuilder(source, request)
    if not normalized:
        page = builder.build([], terminal=True, terminal_state=state, gap_code=gap_code)
        encode_frame(page)
        return [page]
    pages: list[dict[str, Any]] = []
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for record in normalized:
        record_bytes = len(canonical_bytes(record))
        if record_bytes > PAGE_RECORD_BYTES:
            raise ScheduleCollectorError("schedule-record-page-oversize")
        if current and current_bytes + record_bytes > PAGE_RECORD_BYTES:
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(record)
        current_bytes += record_bytes
    chunks.append(current)
    for index, chunk in enumerate(chunks):
        terminal = index == len(chunks) - 1
        page = builder.build(
            chunk,
            terminal=terminal,
            terminal_state=state if terminal else None,
            gap_code=gap_code if terminal else None,
        )
        if len(encode_frame(page)) - 4 > MAX_FRAME_BYTES:
            raise ScheduleCollectorError("schedule-page-oversize")
        pages.append(page)
    return pages


def _peer_credentials(connection: socket.socket) -> tuple[int, int]:
    if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
        payload = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        if len(payload) != 12:
            raise ScheduleCollectorError("collector-peer-credentials-unavailable")
        _pid = int.from_bytes(payload[0:4], byteorder=sys.byteorder, signed=True)
        uid = int.from_bytes(payload[4:8], byteorder=sys.byteorder, signed=True)
        gid = int.from_bytes(payload[8:12], byteorder=sys.byteorder, signed=True)
        return uid, gid
    getpeereid = getattr(socket, "getpeereid", None)
    if getpeereid is None:
        raise ScheduleCollectorError("collector-peer-credentials-unavailable")
    try:
        return tuple(int(value) for value in getpeereid(connection))  # type: ignore[misc]
    except OSError as exc:
        raise ScheduleCollectorError("collector-peer-credentials-unavailable") from exc


class ScheduleCollectorServer:
    """One-method local collector service with exact Unix binding."""

    def __init__(
        self,
        source: SourceSpec,
        *,
        client_uid: int,
        client_gid: int,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
        root: Path = Path("/"),
    ) -> None:
        self.source = source
        self.client_uid = client_uid
        self.client_gid = client_gid
        self.runner = runner
        self.root = root
        self.listener: socket.socket | None = None

    def _prepare_listener(self) -> socket.socket:
        binding = self.source.transport
        if binding is None:
            raise ScheduleCollectorError("collector-transport-not-configured")
        parent = Path(binding["parentPath"])
        socket_path = Path(binding["socketPath"])
        try:
            metadata = os.lstat(parent)
            if (
                parent.resolve(strict=True) != parent
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != binding["parentUid"]
                or metadata.st_gid != binding["parentGid"]
                or stat.S_IMODE(metadata.st_mode) != int(binding["parentMode"], 8)
            ):
                raise ScheduleCollectorError("collector-parent-binding-mismatch")
            if socket_path.exists() or socket_path.is_symlink():
                stale = os.lstat(socket_path)
                if (
                    not stat.S_ISSOCK(stale.st_mode)
                    or stale.st_uid != binding["socketUid"]
                    or stale.st_gid != binding["socketGid"]
                    or stat.S_IMODE(stale.st_mode) != int(binding["socketMode"], 8)
                ):
                    raise ScheduleCollectorError("collector-stale-socket-unsafe")
                socket_path.unlink()
        except OSError as exc:
            raise ScheduleCollectorError("collector-parent-unavailable") from exc
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(socket_path))
            os.chown(socket_path, binding["socketUid"], binding["socketGid"])
            os.chmod(socket_path, int(binding["socketMode"], 8))
            after = os.lstat(parent)
            if (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino):
                raise ScheduleCollectorError("collector-parent-replaced")
            listener.listen(8)
            listener.settimeout(0.5)
            return listener
        except (OSError, ScheduleCollectorError):
            listener.close()
            socket_path.unlink(missing_ok=True)
            raise

    def _handle(self, connection: socket.socket) -> None:
        timeout = self.source.bounds["timeoutMilliseconds"] / 1000
        connection.settimeout(timeout)
        peer_uid, peer_gid = _peer_credentials(connection)
        if peer_uid != self.client_uid or peer_gid != self.client_gid:
            raise ScheduleCollectorError("collector-client-peer-mismatch")
        request = receive_frame(connection)
        _validate_request(self.source, request)
        try:
            records = collect_records(self.source, request, runner=self.runner, root=self.root)
            pages = build_pages(self.source, request, records)
        except (ScheduleCollectorError, ObservationError, OSError, ValueError, KeyError) as exc:
            code = exc.code if isinstance(exc, CollectorError) else "schedule-record-invalid"
            pages = build_pages(self.source, request, [], state="failed", gap_code=code)
        for page in pages:
            send_frame(connection, page)

    def serve_forever(self, stop: threading.Event) -> None:
        if os.geteuid() != self.source.execution_identity["uid"] or os.getegid() != self.source.execution_identity["gid"]:
            raise ScheduleCollectorError("collector-execution-identity-mismatch")
        self.listener = self._prepare_listener()
        socket_path = Path(self.source.transport["socketPath"]) if self.source.transport else None
        try:
            while not stop.is_set():
                try:
                    connection, _address = self.listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    try:
                        self._handle(connection)
                    except (CollectorError, ObservationError, OSError, ValueError):
                        continue
        finally:
            self.listener.close()
            if socket_path is not None:
                socket_path.unlink(missing_ok=True)


def _strict_json(payload: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ScheduleCollectorError("collector-runtime-source-invalid")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ScheduleCollectorError("collector-runtime-source-invalid") from exc


def load_runtime_source(path: Path, *, source_id: str, uid: int, gid: int, mode: int = 0o640) -> SourceSpec:
    try:
        metadata = os.lstat(path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != uid
            or metadata.st_gid != gid
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_size <= 0
            or metadata.st_size > MAX_FRAME_BYTES
        ):
            raise ScheduleCollectorError("collector-runtime-source-binding-mismatch")
        payload = _strict_json(path.read_bytes())
    except OSError as exc:
        raise ScheduleCollectorError("collector-runtime-source-unavailable") from exc
    if not isinstance(payload, dict):
        raise ScheduleCollectorError("collector-runtime-source-invalid")
    registry = SourceRegistry(payload, ["legacy-rootful", "personal-sandbox", "work-sandbox"])
    if set(registry.sources) != {source_id} or registry.host_sources != (source_id,):
        raise ScheduleCollectorError("collector-source-registry-invalid")
    if source_id not in SCHEDULE_SOURCE_IDS:
        raise ScheduleCollectorError("collector-source-registry-invalid")
    return registry.sources[source_id]


def main() -> int:
    source_id = os.environ.get("ARGUS_SOURCE_ID", "")
    stop = threading.Event()
    try:
        source = load_runtime_source(
            Path(os.environ["ARGUS_SOURCE_REGISTRY"]),
            source_id=source_id,
            uid=int(os.environ.get("ARGUS_SOURCE_CONFIG_UID", "0")),
            gid=int(os.environ["ARGUS_SOURCE_CONFIG_GID"]),
            mode=int(os.environ.get("ARGUS_SOURCE_CONFIG_MODE", "0640"), 8),
        )
        server = ScheduleCollectorServer(
            source,
            client_uid=int(os.environ["ARGUS_COLLECTOR_CLIENT_UID"]),
            client_gid=int(os.environ["ARGUS_COLLECTOR_CLIENT_GID"]),
        )
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
        server.serve_forever(stop)
    except (CollectorError, ObservationError, OSError, ValueError, KeyError):
        print("SYSTEMD_SCHEDULE_COLLECTOR_FAIL reason=collector-contract", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
