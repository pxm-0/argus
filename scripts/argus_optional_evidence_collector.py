"""Bounded, read-only optional host evidence for the Argus observation protocol."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from argus_collectors import CollectorError, PageBuilder, _validate_request
from argus_ipc import MAX_FRAME_BYTES, receive_frame, send_frame
from argus_observations import (
    ObservationError,
    SourceRegistry,
    SourceSpec,
    canonical_bytes,
    digest,
    normalize_records,
)


PAGE_RECORD_BYTES = 48 * 1024
SOURCE_IDS = {
    "oreochiserver.process-listeners",
    "oreochiserver.proxy-overlay",
    "oreochiserver.configured-roots",
}
SAFE_NAME = re.compile(r"[A-Za-z0-9_.@:+-]{1,96}\Z")
SAFE_PORT = re.compile(r"(?:[0-9]{1,5}|[A-Za-z][A-Za-z0-9_-]{0,31})\Z")


class OptionalEvidenceError(CollectorError):
    """Stable failure from an optional evidence source."""


def _native_id(kind: str, value: str) -> str:
    return "sha256:" + hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()


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
            "adapter": "argus-optional-evidence",
            "adapterVersion": "1",
            "ordinal": ordinal,
        },
    }


def _environment() -> dict[str, str]:
    return {"LC_ALL": "C", "PATH": "/usr/bin:/bin", "SYSTEMD_PAGER": "cat", "SYSTEMD_COLORS": "0"}


def _run(
    source: SourceSpec,
    argv: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if argv not in source.allowlist["commands"]:
        raise OptionalEvidenceError("optional-command-not-allowlisted")
    command_runner = runner or subprocess.run
    try:
        result = command_runner(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_environment(),
            timeout=source.bounds["timeoutMilliseconds"] / 1000,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OptionalEvidenceError("optional-command-unavailable") from exc
    payload = result.stdout
    if not isinstance(payload, bytes) or len(payload) > source.bounds["maxOutputBytes"]:
        raise OptionalEvidenceError("optional-output-limit-exceeded")
    return result


def _text(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OptionalEvidenceError("optional-output-invalid") from exc


def _address_scope(value: str) -> str:
    candidate = value.strip().strip("[]")
    if candidate in {"*", "0.0.0.0", "::"}:
        return "wildcard"
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return "named"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link-local"
    if address.is_private:
        return "private"
    return "public"


def _split_endpoint(value: str) -> tuple[str, str]:
    endpoint = value.strip()
    if endpoint.startswith("[") and "]:" in endpoint:
        return endpoint[1:].rsplit("]:", 1)
    if ":" not in endpoint:
        return endpoint, ""
    return endpoint.rsplit(":", 1)


def _listener_records(source: SourceSpec, observed_at: str, payload: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in _text(payload).splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        protocol = fields[0].casefold()
        address, port = _split_endpoint(fields[4])
        if not SAFE_NAME.fullmatch(protocol) or not SAFE_PORT.fullmatch(port):
            raise OptionalEvidenceError("listener-output-invalid")
        scope = _address_scope(address)
        identity = (protocol, port, scope)
        if identity in seen:
            continue
        seen.add(identity)
        records.append(_record(
            source,
            "listener",
            _native_id("listener", "\0".join(identity)),
            observed_at,
            {"protocol": protocol, "port": port, "addressScope": scope},
            len(records),
        ))
    return records


def _process_records(source: SourceSpec, observed_at: str, payload: bytes) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    filtered = False
    for line in _text(payload).splitlines():
        fields = line.split()
        if len(fields) < 2:
            filtered = True
            continue
        name, state = fields[0], fields[-1]
        if not SAFE_NAME.fullmatch(name) or not state or not state[0].isalpha():
            filtered = True
            continue
        identity = (name, state[0].upper())
        if identity in seen:
            continue
        seen.add(identity)
        records.append(_record(
            source,
            "process-summary",
            _native_id("process", "\0".join(identity)),
            observed_at,
            {"name": identity[0], "state": identity[1]},
            len(records),
        ))
    return records, filtered


def collect_process_listeners(
    source: SourceSpec,
    request: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> tuple[list[dict[str, Any]], str | None, str]:
    process = _run(source, ["ps", "-eo", "comm=,state="], runner=runner)
    listeners = _run(source, ["ss", "-H", "-lntu", "-n"], runner=runner)
    if process.returncode != 0 or listeners.returncode != 0:
        raise OptionalEvidenceError("process-listener-command-failed")
    records, filtered = _process_records(source, request["explicitClock"], process.stdout)
    records.extend(_listener_records(source, request["explicitClock"], listeners.stdout))
    records.sort(key=lambda item: (item["resourceKind"], item["nativeId"]))
    gap_code = "process-record-filtered" if filtered else None
    return normalize_records(source, records)[0], gap_code, "partial" if gap_code else "completed"


def _json_payload(result: subprocess.CompletedProcess[bytes]) -> Any:
    try:
        return json.loads(_text(result.stdout))
    except (json.JSONDecodeError, OptionalEvidenceError) as exc:
        raise OptionalEvidenceError("proxy-output-invalid") from exc


def _bool_values(value: Any, *, depth: int = 0) -> list[bool]:
    if depth > 4:
        return []
    if isinstance(value, dict):
        values: list[bool] = []
        for key, item in value.items():
            if str(key).casefold() in {"enabled", "active", "running", "configured"} and isinstance(item, bool):
                values.append(item)
            values.extend(_bool_values(item, depth=depth + 1))
        return values
    if isinstance(value, list):
        values: list[bool] = []
        for item in value[:64]:
            values.extend(_bool_values(item, depth=depth + 1))
        return values
    return []


def collect_proxy_overlay(
    source: SourceSpec,
    request: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> tuple[list[dict[str, Any]], str | None, str]:
    commands = (
        ("tailscale-serve", ["tailscale", "serve", "status", "--json"], "json"),
        ("tailscale-funnel", ["tailscale", "funnel", "status", "--json"], "json"),
        ("caddy", ["systemctl", "is-active", "caddy"], "text"),
        ("cloudflared", ["systemctl", "is-active", "cloudflared"], "text"),
    )
    records: list[dict[str, Any]] = []
    unavailable = False
    for provider, argv, kind in commands:
        try:
            result = _run(source, argv, runner=runner)
        except OptionalEvidenceError:
            result = subprocess.CompletedProcess(argv, 127, b"", b"")
        if kind == "json":
            if result.returncode != 0:
                available = configured = active = False
                state = "unavailable"
                unavailable = True
            else:
                try:
                    payload = _json_payload(result)
                except OptionalEvidenceError:
                    available = configured = active = False
                    state = "unavailable"
                    unavailable = True
                else:
                    values = _bool_values(payload)
                    available = True
                    configured = bool(payload)
                    active = any(values) if values else False
                    state = "active" if active else ("configured" if configured else "disabled")
        else:
            text = _text(result.stdout).strip().casefold() if result.stdout else ""
            available = result.returncode in {0, 3}
            configured = False
            active = result.returncode == 0 and text == "active"
            state = "active" if active else ("inactive" if available else "unavailable")
            if not available:
                unavailable = True
        records.append(_record(
            source,
            "provider-state",
            _native_id("provider", provider),
            request["explicitClock"],
            {
                "provider": provider,
                "available": available,
                "configured": configured,
                "active": active,
                "state": state,
                "evidenceDigest": digest({
                    "provider": provider,
                    "returncode": result.returncode,
                    "available": available,
                    "configured": configured,
                    "active": active,
                    "state": state,
                }),
            },
            len(records),
        ))
    records, _byte_count, _snapshot = normalize_records(source, records)
    return records, "proxy-state-unavailable" if unavailable else None, "partial" if unavailable else "completed"


ROOT_LAYOUT = (("workloads", "workloads"), ("config", "config"))
COMPOSE_NAMES = {"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"}


def _root_summary(source: SourceSpec, observed_at: str, root: Path, logical: str, relative: str) -> tuple[dict[str, Any], str | None]:
    directory = root / relative
    if not directory.is_dir() or directory.is_symlink():
        return _record(source, "root-summary", _native_id("root", logical), observed_at, {
            "rootRef": logical,
            "entryCount": 0,
            "manifestCount": 0,
            "composeCount": 0,
            "jsonValid": False,
            "contentDigest": digest({"rootRef": logical, "missing": True}),
        }, 0), "configured-root-unavailable"
    files: list[Path] = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            files.append(path)
            if len(files) > source.bounds["maxRecords"]:
                return _record(source, "root-summary", _native_id("root", logical), observed_at, {
                    "rootRef": logical,
                    "entryCount": 0,
                    "manifestCount": 0,
                    "composeCount": 0,
                    "jsonValid": False,
                    "contentDigest": digest({"rootRef": logical, "tooMany": True}),
                }, 0), "configured-root-limit-exceeded"
    files.sort(key=lambda path: path.relative_to(directory).as_posix())
    json_valid = True
    manifest_count = 0
    compose_count = 0
    fingerprints: list[dict[str, Any]] = []
    total_bytes = 0
    for path in files:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise OptionalEvidenceError("configured-root-unavailable") from exc
        total_bytes += len(payload)
        if total_bytes > source.bounds["maxOutputBytes"]:
            raise OptionalEvidenceError("configured-root-limit-exceeded")
        name = path.name.casefold()
        if name == "manifest.json":
            manifest_count += 1
        if name in COMPOSE_NAMES:
            compose_count += 1
        if path.suffix.casefold() == ".json":
            try:
                json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                json_valid = False
        fingerprints.append({
            "entry": path.relative_to(directory).as_posix(),
            "bytes": len(payload),
            "digest": digest(payload.decode("utf-8", errors="replace")),
        })
    return _record(source, "root-summary", _native_id("root", logical), observed_at, {
        "rootRef": logical,
        "entryCount": len(files),
        "manifestCount": manifest_count,
        "composeCount": compose_count,
        "jsonValid": json_valid,
        "contentDigest": digest({"rootRef": logical, "files": fingerprints}),
    }, 0), None if json_valid else "configured-root-json-invalid"


def collect_configured_roots(
    source: SourceSpec,
    request: dict[str, Any],
    *,
    root: Path,
) -> tuple[list[dict[str, Any]], str | None, str]:
    records: list[dict[str, Any]] = []
    gaps: list[str] = []
    for logical, relative in ROOT_LAYOUT:
        record, gap = _root_summary(source, request["explicitClock"], root, logical, relative)
        records.append(record)
        if gap:
            gaps.append(gap)
    records, _byte_count, _snapshot = normalize_records(source, records)
    return records, sorted(set(gaps))[0] if gaps else None, "partial" if gaps else "completed"


def collect_records(
    source: SourceSpec,
    request: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    root: Path = Path("/srv/argus"),
) -> tuple[list[dict[str, Any]], str | None, str]:
    if source.source_id == "oreochiserver.process-listeners":
        return collect_process_listeners(source, request, runner=runner)
    if source.source_id == "oreochiserver.proxy-overlay":
        return collect_proxy_overlay(source, request, runner=runner)
    if source.source_id == "oreochiserver.configured-roots":
        return collect_configured_roots(source, request, root=root)
    raise OptionalEvidenceError("optional-source-unsupported")


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
        return [builder.build([], terminal=True, terminal_state=state, gap_code=gap_code)]
    pages: list[dict[str, Any]] = []
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for record in normalized:
        record_bytes = len(canonical_bytes(record))
        if record_bytes > PAGE_RECORD_BYTES:
            raise OptionalEvidenceError("optional-record-page-oversize")
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
        if len(canonical_bytes(page)) > MAX_FRAME_BYTES:
            raise OptionalEvidenceError("optional-page-oversize")
        pages.append(page)
    return pages


def _peer_credentials(connection: socket.socket) -> tuple[int, int]:
    if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
        payload = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, gid = struct.unpack("3i", payload)
        return uid, gid
    getpeereid = getattr(socket, "getpeereid", None)
    if getpeereid is None:
        raise OptionalEvidenceError("collector-peer-credentials-unavailable")
    try:
        return tuple(int(value) for value in getpeereid(connection))  # type: ignore[misc]
    except OSError as exc:
        raise OptionalEvidenceError("collector-peer-credentials-unavailable") from exc


class OptionalEvidenceServer:
    def __init__(self, source: SourceSpec, *, client_uid: int, client_gid: int, root: Path):
        self.source = source
        self.client_uid = client_uid
        self.client_gid = client_gid
        self.root = root
        self.listener: socket.socket | None = None

    def _prepare_listener(self) -> socket.socket:
        if self.source.transport is None:
            raise OptionalEvidenceError("collector-transport-not-configured")
        binding = self.source.transport
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
                raise OptionalEvidenceError("collector-parent-binding-mismatch")
            if socket_path.exists() or socket_path.is_symlink():
                stale = os.lstat(socket_path)
                if (
                    not stat.S_ISSOCK(stale.st_mode)
                    or stale.st_uid != binding["socketUid"]
                    or stale.st_gid != binding["socketGid"]
                    or stat.S_IMODE(stale.st_mode) != int(binding["socketMode"], 8)
                ):
                    raise OptionalEvidenceError("collector-stale-socket-unsafe")
                socket_path.unlink()
        except OSError as exc:
            raise OptionalEvidenceError("collector-parent-unavailable") from exc
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(socket_path))
            os.chown(socket_path, binding["socketUid"], binding["socketGid"])
            os.chmod(socket_path, int(binding["socketMode"], 8))
            after = os.lstat(parent)
            if (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino):
                raise OptionalEvidenceError("collector-parent-replaced")
            listener.listen(8)
            listener.settimeout(0.5)
            return listener
        except (OSError, OptionalEvidenceError):
            listener.close()
            socket_path.unlink(missing_ok=True)
            raise

    def _handle(self, connection: socket.socket) -> None:
        connection.settimeout(self.source.bounds["timeoutMilliseconds"] / 1000)
        if _peer_credentials(connection) != (self.client_uid, self.client_gid):
            raise OptionalEvidenceError("collector-client-peer-mismatch")
        request = receive_frame(connection)
        _validate_request(self.source, request)
        try:
            records, gap_code, state = collect_records(self.source, request, root=self.root)
            pages = build_pages(self.source, request, records, state=state, gap_code=gap_code)
        except (OptionalEvidenceError, ObservationError, OSError, ValueError, KeyError) as exc:
            code = exc.code if isinstance(exc, CollectorError) else "optional-record-invalid"
            pages = build_pages(self.source, request, [], state="failed", gap_code=code)
        for page in pages:
            send_frame(connection, page)

    def serve_forever(self, stop: threading.Event) -> None:
        if (
            os.geteuid() != self.source.execution_identity["uid"]
            or os.getegid() != self.source.execution_identity["gid"]
        ):
            raise OptionalEvidenceError("collector-execution-identity-mismatch")
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
                raise OptionalEvidenceError("collector-runtime-source-invalid")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise OptionalEvidenceError("collector-runtime-source-invalid") from exc


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
            raise OptionalEvidenceError("collector-runtime-source-binding-mismatch")
        payload = _strict_json(path.read_bytes())
    except OSError as exc:
        raise OptionalEvidenceError("collector-runtime-source-unavailable") from exc
    if not isinstance(payload, dict):
        raise OptionalEvidenceError("collector-runtime-source-invalid")
    registry = SourceRegistry(payload, ["legacy-rootful", "personal-sandbox", "work-sandbox"])
    if set(registry.sources) != {source_id} or registry.host_sources != (source_id,):
        raise OptionalEvidenceError("collector-source-registry-invalid")
    if source_id not in SOURCE_IDS:
        raise OptionalEvidenceError("collector-source-registry-invalid")
    return registry.sources[source_id]


def main() -> int:
    try:
        source_id = os.environ["ARGUS_SOURCE_ID"]
        source = load_runtime_source(
            Path(os.environ["ARGUS_SOURCE_REGISTRY"]),
            source_id=source_id,
            uid=int(os.environ.get("ARGUS_SOURCE_CONFIG_UID", "0")),
            gid=int(os.environ["ARGUS_SOURCE_CONFIG_GID"]),
            mode=int(os.environ.get("ARGUS_SOURCE_CONFIG_MODE", "0640"), 8),
        )
        server = OptionalEvidenceServer(
            source,
            client_uid=int(os.environ["ARGUS_COLLECTOR_CLIENT_UID"]),
            client_gid=int(os.environ["ARGUS_COLLECTOR_CLIENT_GID"]),
            root=Path(os.environ.get("ARGUS_REPO_ROOT", "/srv/argus")),
        )
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
        server.serve_forever(stop)
    except (CollectorError, ObservationError, OSError, ValueError, KeyError):
        print("OPTIONAL_EVIDENCE_COLLECTOR_FAIL reason=collector-contract", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
