"""Deterministic, minimized rootful Docker observations over the D1b protocol."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import signal
import socket
import stat
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from argus_collectors import (
    CollectorError,
    PageBuilder,
    peer_credentials,
    validate_collection_request,
)
from argus_ipc import MAX_FRAME_BYTES, encode_frame, receive_frame, send_frame
from argus_observations import (
    NORMALIZED_RECORD_VERSION,
    ObservationError,
    SourceRegistry,
    SourceSpec,
    canonical_bytes,
    digest,
    normalize_records,
)


DOCKER_API_VERSION = "1.40"
DOCKER_SOCKET = "/var/run/docker.sock"
SOURCE_ID = "oreochiserver.rootful-docker"
RAW_RESPONSE_CEILING = 8 * 1024 * 1024
RAW_TOTAL_CEILING = 32 * 1024 * 1024
PAGE_RECORD_BYTES = 48 * 1024
MAX_NESTED_ITEMS = 1_000
HEX_ID = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"1\.([0-9]{1,3})\Z")
DETAIL_ROUTE = re.compile(rf"/v{re.escape(DOCKER_API_VERSION)}/containers/([0-9a-f]{{64}})/json\?size=0\Z")
STATIC_ROUTES = {
    "/version",
    f"/v{DOCKER_API_VERSION}/containers/json?all=1&size=0",
    f"/v{DOCKER_API_VERSION}/images/json?all=1&digests=1",
    f"/v{DOCKER_API_VERSION}/networks",
    f"/v{DOCKER_API_VERSION}/volumes",
}
LIFECYCLE = {"created", "running", "paused", "restarting", "removing", "exited", "dead"}
HEALTH = {"none", "starting", "healthy", "unhealthy"}


class DockerCollectorError(CollectorError):
    """Stable failure from the rootful Docker source."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DockerCollectorError("docker-api-json-invalid")
        result[key] = value
    return result


def _strict_json(payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DockerCollectorError("docker-api-json-invalid") from exc


def _version_number(value: Any) -> int:
    if not isinstance(value, str):
        raise DockerCollectorError("docker-api-version-invalid")
    matched = VERSION.fullmatch(value)
    if matched is None:
        raise DockerCollectorError("docker-api-version-invalid")
    return int(matched.group(1))


def _bounded_text(value: Any, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum or any(
        ord(character) < 32 for character in value
    ):
        raise DockerCollectorError("docker-api-shape-invalid")
    return value


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DockerCollectorError("docker-api-shape-invalid")
    return value


def _list(value: Any, *, maximum: int = MAX_NESTED_ITEMS) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise DockerCollectorError("docker-api-shape-invalid")
    return value


def _integer(value: Any, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise DockerCollectorError("docker-api-shape-invalid")
    return value


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise DockerCollectorError("docker-api-shape-invalid")
    return value


def _opaque(kind: str, value: str) -> str:
    return "sha256:" + hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()


def _docker_id(value: Any) -> str:
    candidate = _bounded_text(value, maximum=71)
    hexadecimal = candidate.removeprefix("sha256:")
    if HEX_ID.fullmatch(hexadecimal) is None:
        raise DockerCollectorError("docker-resource-id-invalid")
    return f"sha256:{hexadecimal}"


def _labels(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    labels = _object(value)
    if len(labels) > MAX_NESTED_ITEMS:
        raise DockerCollectorError("docker-api-shape-invalid")
    return labels


def _compose(labels: dict[str, Any], field: str) -> str:
    value = labels.get(f"com.docker.compose.{field}", "")
    return _bounded_text(value) if value is not None else ""


def _address_scope(value: Any) -> str:
    candidate = _bounded_text(value, maximum=128).strip().strip("[]")
    if candidate in {"", "*", "0.0.0.0", "::"}:
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


def _port(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DockerCollectorError("docker-api-shape-invalid") from exc
    if not 1 <= parsed <= 65_535:
        raise DockerCollectorError("docker-api-shape-invalid")
    return parsed


class UnixHttpConnection(http.client.HTTPConnection):
    def __init__(
        self,
        socket_path: str,
        timeout: float,
        connected: Callable[[socket.socket], None],
    ) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path
        self.connected = connected

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(self.timeout)
            connection.connect(self.socket_path)
            self.connected(connection)
            self.sock = connection
        except (CollectorError, OSError, ValueError):
            connection.close()
            raise


class DockerApiClient:
    """Bounded GET-only Docker Engine client for one immutable collection run."""

    def __init__(
        self,
        socket_path: str,
        *,
        deadline: float,
        socket_uid: int,
        socket_gid: int,
        socket_mode: int = 0o660,
        daemon_uid: int = 0,
        daemon_gid: int = 0,
        response_ceiling: int = RAW_RESPONSE_CEILING,
        total_ceiling: int = RAW_TOTAL_CEILING,
    ) -> None:
        if response_ceiling <= 0 or total_ceiling < response_ceiling:
            raise DockerCollectorError("docker-api-bound-invalid")
        self.socket_path = Path(socket_path)
        self.deadline = deadline
        self.socket_uid = socket_uid
        self.socket_gid = socket_gid
        self.socket_mode = socket_mode
        self.daemon_uid = daemon_uid
        self.daemon_gid = daemon_gid
        self.response_ceiling = response_ceiling
        self.total_ceiling = total_ceiling
        self.total_bytes = 0
        self.binding = self._verify_binding()

    def _verify_binding(self) -> os.stat_result:
        try:
            metadata = os.lstat(self.socket_path)
        except OSError as exc:
            raise DockerCollectorError("docker-socket-unavailable") from exc
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != self.socket_uid
            or metadata.st_gid != self.socket_gid
            or stat.S_IMODE(metadata.st_mode) != self.socket_mode
        ):
            raise DockerCollectorError("docker-socket-binding-mismatch")
        if hasattr(self, "binding") and (
            metadata.st_dev,
            metadata.st_ino,
        ) != (self.binding.st_dev, self.binding.st_ino):
            raise DockerCollectorError("docker-socket-replaced")
        return metadata

    def _connected(self, connection: socket.socket) -> None:
        self._verify_binding()
        peer_uid, peer_gid = peer_credentials(connection)
        if peer_uid != self.daemon_uid or peer_gid != self.daemon_gid:
            raise DockerCollectorError("docker-daemon-peer-mismatch")

    def _remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DockerCollectorError("docker-api-timeout")
        return remaining

    @staticmethod
    def _route_allowed(path: str) -> bool:
        return path in STATIC_ROUTES or DETAIL_ROUTE.fullmatch(path) is not None

    def get(self, path: str) -> Any:
        if not isinstance(path, str) or not self._route_allowed(path):
            raise DockerCollectorError("docker-api-route-denied")
        connection = UnixHttpConnection(str(self.socket_path), self._remaining(), self._connected)
        try:
            connection.request(
                "GET",
                path,
                headers={"Accept": "application/json", "Connection": "close", "Host": "docker"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise DockerCollectorError("docker-api-request-failed")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise DockerCollectorError("docker-api-content-type-invalid")
            raw_length = response.getheader("Content-Length")
            if raw_length is not None:
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise DockerCollectorError("docker-api-length-invalid") from exc
                if length < 0 or length > self.response_ceiling:
                    raise DockerCollectorError("docker-api-response-oversize")
            payload = response.read(self.response_ceiling + 1)
            if len(payload) > self.response_ceiling:
                raise DockerCollectorError("docker-api-response-oversize")
            if time.monotonic() >= self.deadline:
                raise DockerCollectorError("docker-api-timeout")
            self.total_bytes += len(payload)
            if self.total_bytes > self.total_ceiling:
                raise DockerCollectorError("docker-api-total-oversize")
            return _strict_json(payload)
        except socket.timeout as exc:
            raise DockerCollectorError("docker-api-timeout") from exc
        except DockerCollectorError:
            raise
        except (http.client.HTTPException, OSError, ValueError) as exc:
            raise DockerCollectorError("docker-api-unavailable") from exc
        finally:
            connection.close()

    def verify_unchanged(self) -> None:
        self._verify_binding()


def _record(kind: str, native_id: str, observed_at: str, attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": NORMALIZED_RECORD_VERSION,
        "resourceKind": kind,
        "nativeId": native_id,
        "observedAt": observed_at,
        "attributes": attributes,
        "provenance": {"adapter": "docker-engine-api", "adapterVersion": DOCKER_API_VERSION, "ordinal": 0},
    }


def _mounts(value: Any) -> list[dict[str, Any]]:
    results = []
    for mount in _list(value):
        item = _object(mount)
        source = _bounded_text(item.get("Source", ""), maximum=4096)
        results.append({
            "type": _bounded_text(item.get("Type", "unknown"), maximum=32),
            "sourceRef": _opaque("docker-mount", source) if source else "",
            "destination": _bounded_text(item.get("Destination", ""), maximum=4096),
            "readOnly": not _boolean(item.get("RW", False)),
            "propagation": _bounded_text(item.get("Propagation", ""), maximum=64),
        })
    return sorted(results, key=lambda item: canonical_bytes(item))


def _published_ports(value: Any) -> list[dict[str, Any]]:
    ports = _object(value) if value is not None else {}
    if len(ports) > MAX_NESTED_ITEMS:
        raise DockerCollectorError("docker-api-shape-invalid")
    results = []
    for container_port, bindings in ports.items():
        private_text, separator, protocol = str(container_port).partition("/")
        if separator != "/" or protocol not in {"tcp", "udp", "sctp"}:
            raise DockerCollectorError("docker-api-shape-invalid")
        if bindings is None:
            continue
        for binding in _list(bindings):
            item = _object(binding)
            results.append({
                "privatePort": _port(private_text),
                "publicPort": _port(item.get("HostPort")),
                "protocol": protocol,
                "addressScope": _address_scope(item.get("HostIp", "")),
            })
    return sorted(results, key=lambda item: canonical_bytes(item))


def _container_record(detail: Any, observed_at: str) -> dict[str, Any]:
    item = _object(detail)
    container_id = _docker_id(item.get("Id"))
    config = _object(item.get("Config"))
    labels = _labels(config.get("Labels"))
    state = _object(item.get("State"))
    lifecycle = _bounded_text(state.get("Status", ""), maximum=32)
    if lifecycle not in LIFECYCLE:
        raise DockerCollectorError("docker-container-state-invalid")
    health_payload = state.get("Health")
    health = "none" if health_payload is None else _bounded_text(_object(health_payload).get("Status", ""), maximum=32)
    if health not in HEALTH:
        raise DockerCollectorError("docker-container-health-invalid")
    host = _object(item.get("HostConfig"))
    restart = _object(host.get("RestartPolicy", {}))
    network_settings = _object(item.get("NetworkSettings"))
    networks = _object(network_settings.get("Networks", {}))
    if len(networks) > MAX_NESTED_ITEMS:
        raise DockerCollectorError("docker-api-shape-invalid")
    name = _bounded_text(item.get("Name", ""), maximum=512).lstrip("/")
    return _record(
        "container",
        container_id,
        observed_at,
        {
            "lifecycle": lifecycle,
            "name": name,
            "project": _compose(labels, "project"),
            "service": _compose(labels, "service"),
            "imageRef": _opaque("docker-image-ref", _bounded_text(config.get("Image", ""), maximum=4096)),
            "health": health,
            "restartPolicy": _bounded_text(restart.get("Name", ""), maximum=64),
            "networkRefs": sorted(_bounded_text(network, maximum=512) for network in networks),
            "mounts": _mounts(item.get("Mounts", [])),
            "publishedPorts": _published_ports(network_settings.get("Ports", {})),
            "privilegeFlags": {
                "privileged": _boolean(host.get("Privileged", False)),
                "hostNetwork": host.get("NetworkMode") == "host",
                "hostPid": host.get("PidMode") == "host",
                "addedCapabilities": bool(_list(host.get("CapAdd", []))) if host.get("CapAdd") is not None else False,
                "hostDevices": bool(_list(host.get("Devices", []))) if host.get("Devices") is not None else False,
            },
        },
    )


def _image_record(value: Any, observed_at: str) -> dict[str, Any]:
    item = _object(value)
    tags = [] if item.get("RepoTags") is None else _list(item.get("RepoTags"))
    digests = [] if item.get("RepoDigests") is None else _list(item.get("RepoDigests"))
    return _record(
        "image",
        _docker_id(item.get("Id")),
        observed_at,
        {
            "createdEpoch": _integer(item.get("Created", 0)),
            "sizeBytes": _integer(item.get("Size", 0)),
            "referenceCount": len({_bounded_text(entry, maximum=4096) for entry in [*tags, *digests]}),
        },
    )


def _network_record(value: Any, observed_at: str) -> dict[str, Any]:
    item = _object(value)
    labels = _labels(item.get("Labels"))
    containers = _object(item.get("Containers", {}))
    if len(containers) > MAX_NESTED_ITEMS:
        raise DockerCollectorError("docker-api-shape-invalid")
    return _record(
        "network",
        _docker_id(item.get("Id")),
        observed_at,
        {
            "name": _bounded_text(item.get("Name", ""), maximum=512),
            "driver": _bounded_text(item.get("Driver", ""), maximum=64),
            "scope": _bounded_text(item.get("Scope", ""), maximum=64),
            "internal": _boolean(item.get("Internal", False)),
            "attachable": _boolean(item.get("Attachable", False)),
            "containerCount": len(containers),
            "project": _compose(labels, "project"),
            "network": _compose(labels, "network"),
        },
    )


def _volume_record(value: Any, observed_at: str) -> dict[str, Any]:
    item = _object(value)
    name = _bounded_text(item.get("Name", ""), maximum=512)
    labels = _labels(item.get("Labels"))
    return _record(
        "volume",
        _opaque("docker-volume", name),
        observed_at,
        {
            "name": name,
            "driver": _bounded_text(item.get("Driver", ""), maximum=64),
            "project": _compose(labels, "project"),
            "volume": _compose(labels, "volume"),
        },
    )


def collect_docker_records(
    source: SourceSpec,
    request: dict[str, Any],
    client: DockerApiClient,
) -> list[dict[str, Any]]:
    """Collect and locally minimize one rootful Docker snapshot."""
    validate_collection_request(source, request)
    try:
        datetime.strptime(request["explicitClock"], "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, TypeError, ValueError) as exc:
        raise DockerCollectorError("collector-clock-invalid") from exc
    version = _object(client.get("/version"))
    minimum = _version_number(version.get("MinAPIVersion"))
    maximum = _version_number(version.get("ApiVersion"))
    pinned = _version_number(DOCKER_API_VERSION)
    if minimum > pinned or maximum < pinned:
        raise DockerCollectorError("docker-api-version-unsupported")

    summaries = _list(client.get(f"/v{DOCKER_API_VERSION}/containers/json?all=1&size=0"), maximum=source.bounds["maxRecords"])
    listed_ids = [_docker_id(_object(item).get("Id")) for item in summaries]
    if len(listed_ids) != len(set(listed_ids)):
        raise DockerCollectorError("docker-resource-id-duplicate")
    records = []
    for container_id in sorted(listed_ids):
        hexadecimal = container_id.removeprefix("sha256:")
        detail = client.get(f"/v{DOCKER_API_VERSION}/containers/{hexadecimal}/json?size=0")
        record = _container_record(detail, request["explicitClock"])
        if record["nativeId"] != container_id:
            raise DockerCollectorError("docker-container-detail-mismatch")
        records.append(record)

    images = _list(client.get(f"/v{DOCKER_API_VERSION}/images/json?all=1&digests=1"), maximum=source.bounds["maxRecords"])
    networks = _list(client.get(f"/v{DOCKER_API_VERSION}/networks"), maximum=source.bounds["maxRecords"])
    volumes_payload = _object(client.get(f"/v{DOCKER_API_VERSION}/volumes"))
    volumes = [] if volumes_payload.get("Volumes") is None else _list(
        volumes_payload.get("Volumes"), maximum=source.bounds["maxRecords"]
    )
    records.extend(_image_record(item, request["explicitClock"]) for item in images)
    records.extend(_network_record(item, request["explicitClock"]) for item in networks)
    records.extend(_volume_record(item, request["explicitClock"]) for item in volumes)
    if len(records) > source.bounds["maxRecords"]:
        raise DockerCollectorError("docker-record-limit-exceeded")
    records.sort(key=lambda item: (item["resourceKind"], item["nativeId"], canonical_bytes(item["attributes"])))
    for ordinal, record in enumerate(records):
        record["provenance"]["ordinal"] = ordinal
    normalized, _byte_count, _snapshot_digest = normalize_records(source, records)
    client.verify_unchanged()
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
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for record in normalized:
        record_bytes = len(canonical_bytes(record))
        if record_bytes > PAGE_RECORD_BYTES:
            raise DockerCollectorError("docker-record-page-oversize")
        if current and current_bytes + record_bytes > PAGE_RECORD_BYTES:
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(record)
        current_bytes += record_bytes
    chunks.append(current)
    pages = []
    for index, chunk in enumerate(chunks):
        terminal = index == len(chunks) - 1
        page = builder.build(
            chunk,
            terminal=terminal,
            terminal_state=state if terminal else None,
            gap_code=gap_code if terminal else None,
        )
        if len(encode_frame(page)) - 4 > MAX_FRAME_BYTES:
            raise DockerCollectorError("docker-page-oversize")
        pages.append(page)
    return pages


class RootfulDockerCollectorServer:
    """One-method local collector service with mutual Unix peer authentication."""

    def __init__(
        self,
        source: SourceSpec,
        *,
        client_uid: int,
        client_gid: int,
        docker_socket: str = DOCKER_SOCKET,
        docker_socket_uid: int = 0,
        docker_socket_gid: int,
        docker_socket_mode: int = 0o660,
        daemon_uid: int = 0,
        daemon_gid: int = 0,
        client_factory: Callable[..., DockerApiClient] = DockerApiClient,
    ) -> None:
        self.source = source
        self.client_uid = client_uid
        self.client_gid = client_gid
        self.docker_socket = docker_socket
        self.docker_socket_uid = docker_socket_uid
        self.docker_socket_gid = docker_socket_gid
        self.docker_socket_mode = docker_socket_mode
        self.daemon_uid = daemon_uid
        self.daemon_gid = daemon_gid
        self.client_factory = client_factory
        self.listener: socket.socket | None = None

    def _prepare_listener(self) -> socket.socket:
        if self.source.transport is None:
            raise DockerCollectorError("collector-transport-not-configured")
        binding = self.source.transport
        parent = Path(binding["parentPath"])
        socket_path = Path(binding["socketPath"])
        try:
            parent_metadata = os.lstat(parent)
        except OSError as exc:
            raise DockerCollectorError("collector-parent-unavailable") from exc
        if (
            parent.resolve(strict=True) != parent
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != binding["parentUid"]
            or parent_metadata.st_gid != binding["parentGid"]
            or stat.S_IMODE(parent_metadata.st_mode) != int(binding["parentMode"], 8)
        ):
            raise DockerCollectorError("collector-parent-binding-mismatch")
        if socket_path.exists() or socket_path.is_symlink():
            stale = os.lstat(socket_path)
            if (
                not stat.S_ISSOCK(stale.st_mode)
                or stale.st_uid != binding["socketUid"]
                or stale.st_gid != binding["socketGid"]
                or stat.S_IMODE(stale.st_mode) != int(binding["socketMode"], 8)
            ):
                raise DockerCollectorError("collector-stale-socket-unsafe")
            socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(socket_path))
            os.chown(socket_path, binding["socketUid"], binding["socketGid"])
            os.chmod(socket_path, int(binding["socketMode"], 8))
            parent_after = os.lstat(parent)
            if (parent_metadata.st_dev, parent_metadata.st_ino) != (
                parent_after.st_dev,
                parent_after.st_ino,
            ):
                raise DockerCollectorError("collector-parent-replaced")
            listener.listen(8)
            listener.settimeout(0.5)
            return listener
        except (CollectorError, OSError):
            listener.close()
            socket_path.unlink(missing_ok=True)
            raise

    def _handle(self, connection: socket.socket) -> None:
        timeout = self.source.bounds["timeoutMilliseconds"] / 1000
        deadline = time.monotonic() + timeout
        connection.settimeout(timeout)
        peer_uid, peer_gid = peer_credentials(connection)
        if peer_uid != self.client_uid or peer_gid != self.client_gid:
            raise DockerCollectorError("collector-client-peer-mismatch")
        request = receive_frame(connection)
        validate_collection_request(self.source, request)
        try:
            client = self.client_factory(
                self.docker_socket,
                deadline=deadline,
                socket_uid=self.docker_socket_uid,
                socket_gid=self.docker_socket_gid,
                socket_mode=self.docker_socket_mode,
                daemon_uid=self.daemon_uid,
                daemon_gid=self.daemon_gid,
            )
            records = collect_docker_records(self.source, request, client)
            pages = build_pages(self.source, request, records)
        except (DockerCollectorError, ObservationError) as exc:
            code = exc.code if isinstance(exc, CollectorError) else "docker-record-invalid"
            pages = build_pages(self.source, request, [], state="failed", gap_code=code)
        for page in pages:
            if time.monotonic() >= deadline:
                raise DockerCollectorError("docker-api-timeout")
            send_frame(connection, page)

    def serve_forever(self, stop: threading.Event) -> None:
        if os.geteuid() != self.source.execution_identity["uid"] or os.getegid() != self.source.execution_identity["gid"]:
            raise DockerCollectorError("collector-execution-identity-mismatch")
        self.listener = self._prepare_listener()
        socket_path = Path(self.source.transport["socketPath"]) if self.source.transport else None
        try:
            while not stop.is_set():
                try:
                    connection, _address = self.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if stop.is_set():
                        break
                    raise
                with connection:
                    try:
                        self._handle(connection)
                    except (CollectorError, ObservationError, OSError, ValueError):
                        continue
        finally:
            self.listener.close()
            if socket_path is not None:
                socket_path.unlink(missing_ok=True)


def load_runtime_source(
    path: Path,
    *,
    uid: int,
    gid: int,
    mode: int = 0o640,
    expected_source_ids: set[str] | None = None,
    expected_host_sources: tuple[str, ...] | None = None,
) -> SourceSpec:
    try:
        metadata = os.lstat(path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != uid
            or metadata.st_gid != gid
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_size <= 0
            or metadata.st_size > 65_536
        ):
            raise DockerCollectorError("collector-runtime-source-binding-mismatch")
        payload = _strict_json(path.read_bytes())
    except OSError as exc:
        raise DockerCollectorError("collector-runtime-source-unavailable") from exc
    if not isinstance(payload, dict):
        raise DockerCollectorError("collector-runtime-source-invalid")
    registry = SourceRegistry(payload, [])
    source_ids = expected_source_ids if expected_source_ids is not None else {SOURCE_ID}
    host_sources = expected_host_sources if expected_host_sources is not None else tuple(sorted(source_ids))
    if set(registry.sources) != source_ids or registry.host_sources != host_sources:
        raise DockerCollectorError("collector-source-registry-invalid")
    if len(source_ids) != 1:
        raise DockerCollectorError("collector-source-registry-invalid")
    return registry.sources[next(iter(source_ids))]


def main() -> int:
    registry_path = Path(os.environ.get(
        "ARGUS_SOURCE_REGISTRY",
        "/etc/argus/collectors/rootful-docker-source.json",
    ))
    stop = threading.Event()
    try:
        source = load_runtime_source(
            registry_path,
            uid=int(os.environ.get("ARGUS_SOURCE_CONFIG_UID", "0")),
            gid=int(os.environ["ARGUS_SOURCE_CONFIG_GID"]),
            mode=int(os.environ.get("ARGUS_SOURCE_CONFIG_MODE", "0640"), 8),
        )
        server = RootfulDockerCollectorServer(
            source,
            client_uid=int(os.environ["ARGUS_COLLECTOR_CLIENT_UID"]),
            client_gid=int(os.environ["ARGUS_COLLECTOR_CLIENT_GID"]),
            docker_socket=os.environ.get("ARGUS_DOCKER_SOCKET", DOCKER_SOCKET),
            docker_socket_uid=int(os.environ.get("ARGUS_DOCKER_SOCKET_UID", "0")),
            docker_socket_gid=int(os.environ["ARGUS_DOCKER_SOCKET_GID"]),
            docker_socket_mode=int(os.environ.get("ARGUS_DOCKER_SOCKET_MODE", "0660"), 8),
        )
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
        server.serve_forever(stop)
    except (DockerCollectorError, ObservationError, OSError, ValueError, KeyError):
        print("ROOTFUL_DOCKER_COLLECTOR_FAIL reason=collector-contract", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
