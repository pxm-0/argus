"""Authenticated local collector paging and bounded deterministic scheduling."""

from __future__ import annotations

import concurrent.futures
import ctypes
import os
import queue
import re
import socket
import stat
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from argus_ipc import receive_frame, send_frame
from argus_observations import (
    ObservationError,
    ObservationRepository,
    SourceRegistry,
    SourceSpec,
    digest,
    normalize_records,
)


CURRENT_PROTOCOL_VERSION = 2
PREVIOUS_PROTOCOL_VERSION = 1
SUPPORTED_PROTOCOL_VERSIONS = {PREVIOUS_PROTOCOL_VERSION, CURRENT_PROTOCOL_VERSION}
GAP_CODE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,127})\Z")
REFRESH_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:-]{0,127})\Z")
PAGE_FIELDS = {
    "protocolVersion", "refreshId", "runId", "sourceId", "hostId", "trustDomain",
    "sequence", "terminal", "terminalState", "recordCount", "byteCount",
    "cumulativeRecordCount", "cumulativeByteCount", "runningDigest", "gapCode", "records",
}
REQUEST_FIELDS = {
    "protocolVersion", "method", "refreshId", "runId", "sourceId", "hostId",
    "trustDomain", "explicitClock",
}


class CollectorError(ObservationError):
    """Stable, secret-safe collector protocol failure."""

    def __init__(self, code: str, *, records: list[dict[str, Any]] | None = None):
        super().__init__(code)
        self.code = code
        self.records = records or []


@dataclass(frozen=True)
class CollectionResult:
    state: str
    records: list[dict[str, Any]]
    gap_code: str | None
    protocol_version: int


def _exact_nonempty_text(payload: dict[str, Any], key: str, *, maximum: int = 512) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise CollectorError("collector-envelope-invalid")
    return value


def _exact_nonnegative_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CollectorError("collector-envelope-invalid")
    return value


def _binding(source: SourceSpec) -> dict[str, Any]:
    if source.transport is None:
        raise CollectorError("source-transport-not-configured")
    return source.transport


def select_protocol(source: SourceSpec) -> int:
    versions = set(_binding(source)["protocolVersions"])
    common = sorted(versions & SUPPORTED_PROTOCOL_VERSIONS)
    if not common:
        raise CollectorError("collector-version-unsupported")
    return common[-1]


def _validate_request(source: SourceSpec, request: Any) -> None:
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise CollectorError("collector-request-invalid")
    expected = {
        "protocolVersion": select_protocol(source),
        "method": "collect",
        "sourceId": source.source_id,
        "hostId": source.host_id,
        "trustDomain": source.trust_domain,
    }
    if any(request.get(field) != value for field, value in expected.items()):
        raise CollectorError("collector-request-invalid")
    for field in ("refreshId", "runId", "explicitClock"):
        _exact_nonempty_text(request, field)


def _verify_path(path: Path, *, kind: str, uid: int, gid: int, mode: str) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CollectorError(f"collector-{kind}-unavailable") from exc
    if kind == "parent":
        correct_type = stat.S_ISDIR(metadata.st_mode)
    else:
        correct_type = stat.S_ISSOCK(metadata.st_mode)
    if (
        not correct_type
        or metadata.st_uid != uid
        or metadata.st_gid != gid
        or stat.S_IMODE(metadata.st_mode) != int(mode, 8)
    ):
        raise CollectorError(f"collector-{kind}-binding-mismatch")
    return metadata


def verify_socket_binding(source: SourceSpec) -> tuple[Path, os.stat_result, os.stat_result]:
    binding = _binding(source)
    parent = Path(binding["parentPath"])
    socket_path = Path(binding["socketPath"])
    try:
        if parent.resolve(strict=True) != parent:
            raise CollectorError("collector-parent-binding-mismatch")
    except OSError as exc:
        raise CollectorError("collector-parent-unavailable") from exc
    parent_metadata = _verify_path(
        parent,
        kind="parent",
        uid=binding["parentUid"],
        gid=binding["parentGid"],
        mode=binding["parentMode"],
    )
    socket_metadata = _verify_path(
        socket_path,
        kind="socket",
        uid=binding["socketUid"],
        gid=binding["socketGid"],
        mode=binding["socketMode"],
    )
    return socket_path, parent_metadata, socket_metadata


def _verify_connected_socket(
    connection: socket.socket,
    source: SourceSpec,
    parent_before: os.stat_result,
    socket_before: os.stat_result,
) -> None:
    binding = _binding(source)
    parent_after = _verify_path(
        Path(binding["parentPath"]),
        kind="parent",
        uid=binding["parentUid"],
        gid=binding["parentGid"],
        mode=binding["parentMode"],
    )
    socket_after = _verify_path(
        Path(binding["socketPath"]),
        kind="socket",
        uid=binding["socketUid"],
        gid=binding["socketGid"],
        mode=binding["socketMode"],
    )
    if (parent_before.st_dev, parent_before.st_ino) != (parent_after.st_dev, parent_after.st_ino):
        raise CollectorError("collector-parent-replaced")
    if (socket_before.st_dev, socket_before.st_ino) != (socket_after.st_dev, socket_after.st_ino):
        raise CollectorError("collector-socket-replaced")
    peer_uid, peer_gid = peer_credentials(connection)
    if peer_uid != binding["peerUid"] or peer_gid != binding["peerGid"]:
        raise CollectorError("collector-peer-credentials-mismatch")


def peer_credentials(connection: socket.socket) -> tuple[int, int]:
    """Return authenticated Unix peer identity on supported platforms."""
    if sys.platform.startswith("linux"):
        if not hasattr(socket, "SO_PEERCRED"):
            raise CollectorError("collector-peer-credentials-unavailable")
        size = struct.calcsize("3i")
        _pid, peer_uid, peer_gid = struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
        )
        return peer_uid, peer_gid
    elif sys.platform == "darwin":
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            getpeereid = libc.getpeereid
            getpeereid.argtypes = [
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint),
            ]
            getpeereid.restype = ctypes.c_int
            peer_uid = ctypes.c_uint()
            peer_gid = ctypes.c_uint()
            status = getpeereid(connection.fileno(), ctypes.byref(peer_uid), ctypes.byref(peer_gid))
        except (AttributeError, OSError, TypeError) as exc:
            raise CollectorError("collector-peer-credentials-unavailable") from exc
        if status != 0:
            raise CollectorError("collector-peer-credentials-unavailable")
        return peer_uid.value, peer_gid.value
    else:
        raise CollectorError("collector-peer-credentials-unavailable")


def validate_collection_request(source: SourceSpec, request: Any) -> None:
    """Expose the exact D1b request validator to separately reviewed collectors."""
    _validate_request(source, request)


def collection_request(
    source: SourceSpec,
    *,
    refresh_id: str,
    run_id: str,
    explicit_clock: str,
) -> dict[str, Any]:
    protocol = select_protocol(source)
    request = {
        "protocolVersion": protocol,
        "method": "collect",
        "refreshId": refresh_id,
        "runId": run_id,
        "sourceId": source.source_id,
        "hostId": source.host_id,
        "trustDomain": source.trust_domain,
        "explicitClock": explicit_clock,
    }
    if set(request) != REQUEST_FIELDS:
        raise CollectorError("collector-request-invalid")
    return request


def _validate_page(
    page: Any,
    source: SourceSpec,
    request: dict[str, Any],
    *,
    expected_sequence: int,
    accumulated: list[dict[str, Any]],
    existing_identities: set[tuple[str, str]],
    cumulative_bytes: int,
    previous_digest: str,
) -> tuple[list[dict[str, Any]], int, str]:
    if not isinstance(page, dict) or set(page) != PAGE_FIELDS:
        raise CollectorError("collector-envelope-invalid", records=accumulated)
    if page.get("protocolVersion") != request["protocolVersion"]:
        raise CollectorError("collector-version-mismatch", records=accumulated)
    for field in ("refreshId", "runId", "sourceId", "hostId", "trustDomain"):
        if _exact_nonempty_text(page, field) != request[field]:
            raise CollectorError(f"collector-{field}-mismatch", records=accumulated)
    sequence = _exact_nonnegative_int(page, "sequence")
    if sequence != expected_sequence:
        raise CollectorError("collector-page-sequence-invalid", records=accumulated)
    if not isinstance(page.get("terminal"), bool):
        raise CollectorError("collector-envelope-invalid", records=accumulated)
    if not isinstance(page.get("records"), list):
        raise CollectorError("collector-envelope-invalid", records=accumulated)
    try:
        normalized_page, page_bytes, page_digest = normalize_records(source, page["records"])
    except ObservationError as exc:
        raise CollectorError("collector-record-invalid", records=accumulated) from exc
    if any((item["resourceKind"], item["nativeId"]) in existing_identities for item in normalized_page):
        raise CollectorError("collector-record-invalid", records=accumulated)
    cumulative_records = len(accumulated) + len(normalized_page)
    total_bytes = cumulative_bytes + page_bytes
    if cumulative_records > source.bounds["maxRecords"] or total_bytes > source.bounds["maxOutputBytes"]:
        raise CollectorError("collector-record-invalid", records=accumulated)
    running_digest = digest({
        "previousDigest": previous_digest,
        "sequence": expected_sequence,
        "pageDigest": page_digest,
        "cumulativeRecordCount": cumulative_records,
        "cumulativeByteCount": total_bytes,
    })
    if _exact_nonnegative_int(page, "recordCount") != len(normalized_page):
        raise CollectorError("collector-page-count-mismatch", records=accumulated)
    if _exact_nonnegative_int(page, "byteCount") != page_bytes:
        raise CollectorError("collector-page-byte-mismatch", records=accumulated)
    if _exact_nonnegative_int(page, "cumulativeRecordCount") != cumulative_records:
        raise CollectorError("collector-cumulative-count-mismatch", records=accumulated)
    if _exact_nonnegative_int(page, "cumulativeByteCount") != total_bytes or total_bytes < cumulative_bytes:
        raise CollectorError("collector-cumulative-byte-mismatch", records=accumulated)
    if _exact_nonempty_text(page, "runningDigest") != running_digest:
        raise CollectorError("collector-running-digest-mismatch", records=accumulated)
    terminal_state = page.get("terminalState")
    gap_code = page.get("gapCode")
    if not page["terminal"]:
        if not normalized_page or terminal_state is not None or gap_code is not None:
            raise CollectorError("collector-terminal-invalid", records=accumulated)
    else:
        if terminal_state not in {"completed", "partial", "failed"}:
            raise CollectorError("collector-terminal-invalid", records=accumulated)
        if terminal_state == "completed" and gap_code is not None:
            raise CollectorError("collector-terminal-invalid", records=accumulated)
        if terminal_state in {"partial", "failed"} and (
            not isinstance(gap_code, str) or GAP_CODE.fullmatch(gap_code) is None
        ):
            raise CollectorError("collector-terminal-invalid", records=accumulated)
        if terminal_state == "failed" and cumulative_records:
            raise CollectorError("collector-terminal-invalid", records=accumulated)
    return normalized_page, total_bytes, running_digest


class PageValidator:
    """Stateful validator for one ordered, terminal collector page stream."""

    def __init__(
        self,
        source: SourceSpec,
        request: dict[str, Any],
        *,
        deadline: float | None = None,
    ):
        _validate_request(source, request)
        self.source = source
        self.request = request
        self.expected_sequence = 1
        self.records: list[dict[str, Any]] = []
        self.identities: set[tuple[str, str]] = set()
        self.cumulative_bytes = 0
        self.running_digest = digest({"collectorRequest": request})
        self.terminal = False
        self.deadline = deadline

    def accept(self, page: dict[str, Any]) -> CollectionResult | None:
        if self.terminal:
            raise CollectorError("collector-page-after-terminal", records=self.records)
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise CollectorError("collector-timeout", records=self.records)
        if self.expected_sequence > self.source.bounds["maxRecords"] + 1:
            raise CollectorError("collector-page-limit-exceeded", records=self.records)
        try:
            normalized_page, self.cumulative_bytes, self.running_digest = _validate_page(
                page,
                self.source,
                self.request,
                expected_sequence=self.expected_sequence,
                accumulated=self.records,
                existing_identities=self.identities,
                cumulative_bytes=self.cumulative_bytes,
                previous_digest=self.running_digest,
            )
        except CollectorError as exc:
            if not exc.records:
                exc.records = list(self.records)
            raise
        self.records.extend(normalized_page)
        self.identities.update((item["resourceKind"], item["nativeId"]) for item in normalized_page)
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise CollectorError("collector-timeout", records=self.records)
        self.expected_sequence += 1
        if page["terminal"]:
            try:
                self.records, _total_bytes, _snapshot_digest = normalize_records(self.source, self.records)
            except ObservationError as exc:
                raise CollectorError("collector-record-invalid", records=self.records) from exc
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise CollectorError("collector-timeout", records=self.records)
            self.terminal = True
            return CollectionResult(
                state=page["terminalState"],
                records=self.records,
                gap_code=page["gapCode"],
                protocol_version=self.request["protocolVersion"],
            )
        return None

    def finish(self) -> None:
        if not self.terminal:
            raise CollectorError("collector-terminal-missing", records=self.records)


def collect_from_socket(
    source: SourceSpec,
    request: dict[str, Any],
    timeout_seconds: float,
    *,
    pre_connect_hook: Callable[[], None] | None = None,
) -> CollectionResult:
    socket_path, parent_before, socket_before = verify_socket_binding(source)
    if timeout_seconds <= 0:
        raise CollectorError("collector-timeout")
    deadline = time.monotonic() + timeout_seconds
    validator = PageValidator(source, request, deadline=deadline)
    try:
        if pre_connect_hook is not None:
            pre_connect_hook()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(max(0.001, deadline - time.monotonic()))
            connection.connect(str(socket_path))
            _verify_connected_socket(connection, source, parent_before, socket_before)
            send_frame(connection, request)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectorError("collector-timeout", records=validator.records)
                connection.settimeout(remaining)
                page = receive_frame(connection)
                result = validator.accept(page)
                if result is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CollectorError("collector-timeout", records=validator.records)
                    connection.settimeout(remaining)
                    if connection.recv(1):
                        raise CollectorError("collector-page-after-terminal", records=validator.records)
                    return result
    except socket.timeout as exc:
        raise CollectorError("collector-timeout", records=validator.records) from exc
    except CollectorError:
        raise
    except (OSError, ValueError, UnicodeError) as exc:
        code = "collector-disconnected" if validator.records else "collector-unavailable"
        raise CollectorError(code, records=validator.records) from exc


CollectorCallable = Callable[[SourceSpec, dict[str, Any], float], CollectionResult]
_GLOBAL_WORKER_SLOTS = threading.BoundedSemaphore(32)


def _collect_before_deadline(
    collector: CollectorCallable,
    source: SourceSpec,
    request: dict[str, Any],
    source_timeout: float,
    global_deadline: float,
) -> CollectionResult:
    remaining = global_deadline - time.monotonic()
    if remaining <= 0:
        raise CollectorError("scheduler-global-timeout")
    # When the global deadline is what bounds this run, an overrun is the
    # scheduler's, not the collector's. Blaming the collector made the gap code
    # depend on which thread noticed first: the waiter marks unfinished futures
    # scheduler-global-timeout, while a worker that completed just before that
    # wait returned reported collector-timeout for the very same cause.
    global_bound = remaining <= source_timeout
    effective_timeout = min(source_timeout, remaining)
    source_deadline = time.monotonic() + effective_timeout
    result = collector(source, request, effective_timeout)
    if time.monotonic() >= source_deadline:
        raise CollectorError(
            "scheduler-global-timeout" if global_bound else "collector-timeout"
        )
    return result


def _start_daemon_workers(
    jobs: list[tuple[str, CollectorCallable, SourceSpec, dict[str, Any], float, float]],
    worker_count: int,
) -> dict[concurrent.futures.Future[CollectionResult], str]:
    work: queue.Queue[tuple[concurrent.futures.Future[CollectionResult], tuple[Any, ...]] | None] = queue.Queue()
    futures: dict[concurrent.futures.Future[CollectionResult], str] = {}
    for source_id, collector, source, request, source_timeout, global_deadline in jobs:
        future: concurrent.futures.Future[CollectionResult] = concurrent.futures.Future()
        futures[future] = source_id
        work.put((future, (collector, source, request, source_timeout, global_deadline)))
    for _index in range(worker_count):
        work.put(None)

    def worker() -> None:
        while True:
            item = work.get()
            if item is None:
                return
            future, arguments = item
            if not future.set_running_or_notify_cancel():
                continue
            if not _GLOBAL_WORKER_SLOTS.acquire(blocking=False):
                future.set_exception(CollectorError("scheduler-worker-capacity"))
                continue
            try:
                future.set_result(_collect_before_deadline(*arguments))
            except Exception as exc:
                future.set_exception(exc)
            finally:
                _GLOBAL_WORKER_SLOTS.release()

    for index in range(worker_count):
        threading.Thread(
            target=worker,
            name=f"argus-collector-{index}",
            daemon=True,
        ).start()
    return futures


class CollectorScheduler:
    """Collect in parallel, then serialize deterministic repository commits."""

    def __init__(
        self,
        repository: ObservationRepository,
        registry: SourceRegistry,
        *,
        max_workers: int = 4,
        global_timeout_milliseconds: int = 30_000,
        collector: CollectorCallable = collect_from_socket,
    ) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or not 1 <= max_workers <= 32:
            raise CollectorError("scheduler-worker-bound-invalid")
        if (
            not isinstance(global_timeout_milliseconds, int)
            or isinstance(global_timeout_milliseconds, bool)
            or not 1 <= global_timeout_milliseconds <= 600_000
        ):
            raise CollectorError("scheduler-deadline-invalid")
        self.repository = repository
        self.registry = registry
        self.max_workers = max_workers
        self.global_timeout_milliseconds = global_timeout_milliseconds
        self.collector = collector

    @staticmethod
    def source_run_id(refresh_id: str, source_id: str) -> str:
        suffix = digest({"refreshId": refresh_id, "sourceId": source_id})[7:31]
        return f"collect:{refresh_id}:{suffix}"

    def refresh(self, *, refresh_id: str, explicit_clock: str) -> dict[str, Any]:
        if not isinstance(refresh_id, str) or REFRESH_ID.fullmatch(refresh_id) is None:
            raise CollectorError("refresh-id-invalid")
        source_ids = sorted(self.registry.sources)
        if not source_ids:
            self.repository.sync_registry(self.registry, explicit_clock=explicit_clock)
            return {
                "schemaVersion": 1,
                "refreshId": refresh_id,
                "status": "not-configured",
                "sources": [],
            }
        collected: dict[str, CollectionResult | CollectorError] = {}
        requests: dict[str, dict[str, Any]] = {}
        existing: dict[str, dict[str, Any]] = {}
        futures: dict[concurrent.futures.Future[CollectionResult], str] = {}
        global_seconds = self.global_timeout_milliseconds / 1000
        global_deadline = time.monotonic() + global_seconds
        reservations = []
        jobs = []
        try:
            for source_id in source_ids:
                source = self.registry.sources[source_id]
                run_id = self.source_run_id(refresh_id, source_id)
                try:
                    request = collection_request(
                        source,
                        refresh_id=refresh_id,
                        run_id=run_id,
                        explicit_clock=explicit_clock,
                    )
                except CollectorError as exc:
                    collected[source_id] = exc
                    protocol_version = source.protocol_version
                else:
                    requests[source_id] = request
                    protocol_version = request["protocolVersion"]
                reservations.append({
                    "runId": run_id,
                    "sourceId": source_id,
                    "protocolVersion": protocol_version,
                })
            try:
                reservation_statuses = self.repository.reserve_collection_runs(
                    self.registry,
                    reservations,
                    started_at=explicit_clock,
                )
            except ObservationError as exc:
                raise CollectorError("refresh-id-conflict") from exc
            if "active" in reservation_statuses.values():
                raise CollectorError("refresh-in-progress")
            for source_id in source_ids:
                run_id = self.source_run_id(refresh_id, source_id)
                if reservation_statuses[run_id] == "existing":
                    prior = self.repository.run_result(run_id)
                    if prior is None or prior["state"] == "collecting":
                        raise CollectorError("refresh-in-progress")
                    existing[source_id] = prior
                    continue
                if source_id in collected:
                    continue
                source = self.registry.sources[source_id]
                request = requests[source_id]
                source_timeout = source.bounds["timeoutMilliseconds"] / 1000
                jobs.append((
                    source_id,
                    self.collector,
                    source,
                    request,
                    source_timeout,
                    global_deadline,
                ))
            futures = _start_daemon_workers(jobs, min(self.max_workers, len(jobs))) if jobs else {}
            remaining = max(0, global_deadline - time.monotonic())
            done, not_done = concurrent.futures.wait(
                futures,
                timeout=remaining,
                return_when=concurrent.futures.ALL_COMPLETED,
            )
            for future in done:
                source_id = futures[future]
                try:
                    collected[source_id] = future.result()
                except CollectorError as exc:
                    collected[source_id] = exc
                except Exception:
                    collected[source_id] = CollectorError("collector-failed")
            for future in not_done:
                source_id = futures[future]
                future.cancel()
                collected[source_id] = CollectorError("scheduler-global-timeout")
        finally:
            for future in futures:
                future.cancel()
        results = []
        for source_id in source_ids:
            if source_id in existing:
                prior = existing[source_id]
                results.append({
                    "runId": prior["runId"],
                    "sourceId": prior["sourceId"],
                    "state": prior["state"],
                    "recordCount": prior["recordCount"],
                    "byteCount": prior["byteCount"],
                    "snapshotDigest": prior["snapshotDigest"],
                    "gapCode": prior["gapCode"],
                })
                continue
            source = self.registry.sources[source_id]
            outcome = collected[source_id]
            run_id = self.source_run_id(refresh_id, source_id)
            if isinstance(outcome, CollectionResult):
                state = outcome.state
                records = outcome.records
                gap_code = outcome.gap_code
                protocol_version = outcome.protocol_version
            else:
                records = outcome.records
                state = "partial" if records else "failed"
                gap_code = outcome.code
                protocol_version = requests.get(source_id, {}).get("protocolVersion", source.protocol_version)
            try:
                result = self.repository.ingest(
                    self.registry,
                    run_id=run_id,
                    source_id=source_id,
                    sequence=None,
                    state=state,
                    started_at=explicit_clock,
                    terminal_at=explicit_clock,
                    records=records,
                    gap_code=gap_code,
                    protocol_version=protocol_version,
                    reserved=True,
                )
            except ObservationError:
                gap_code = "repository-finalize-failed"
                result = self.repository.fail_reserved_run(
                    self.registry,
                    run_id=run_id,
                    source_id=source_id,
                    started_at=explicit_clock,
                    terminal_at=explicit_clock,
                    protocol_version=protocol_version,
                    gap_code=gap_code,
                )
            result["gapCode"] = gap_code
            results.append({
                "runId": result["runId"],
                "sourceId": result["sourceId"],
                "state": result["state"],
                "recordCount": result["recordCount"],
                "byteCount": result["byteCount"],
                "snapshotDigest": result["snapshotDigest"],
                "gapCode": result["gapCode"],
            })
        failed = sum(item["state"] != "completed" for item in results)
        return {
            "schemaVersion": 1,
            "refreshId": refresh_id,
            "status": "completed" if failed == 0 else "partial",
            "sources": results,
        }


class PageBuilder:
    """Linear-time reference builder for one normalized collector stream."""

    def __init__(self, source: SourceSpec, request: dict[str, Any]):
        _validate_request(source, request)
        self.source = source
        self.request = request
        self.sequence = 1
        self.cumulative_records = 0
        self.cumulative_bytes = 0
        self.running_digest = digest({"collectorRequest": request})
        self.identities: set[tuple[str, str]] = set()
        self.terminal = False

    def build(
        self,
        records: list[dict[str, Any]],
        *,
        terminal: bool,
        terminal_state: str | None,
        gap_code: str | None,
    ) -> dict[str, Any]:
        if self.terminal:
            raise CollectorError("collector-page-builder-invalid")
        normalized_page, page_bytes, page_digest = normalize_records(self.source, records)
        page_identities = {(item["resourceKind"], item["nativeId"]) for item in normalized_page}
        if self.identities & page_identities:
            raise CollectorError("collector-page-builder-invalid")
        cumulative_records = self.cumulative_records + len(normalized_page)
        cumulative_bytes = self.cumulative_bytes + page_bytes
        if (
            cumulative_records > self.source.bounds["maxRecords"]
            or cumulative_bytes > self.source.bounds["maxOutputBytes"]
            or (not terminal and not normalized_page)
        ):
            raise CollectorError("collector-page-builder-invalid")
        running_digest = digest({
            "previousDigest": self.running_digest,
            "sequence": self.sequence,
            "pageDigest": page_digest,
            "cumulativeRecordCount": cumulative_records,
            "cumulativeByteCount": cumulative_bytes,
        })
        page = {
            "protocolVersion": self.request["protocolVersion"],
            "refreshId": self.request["refreshId"],
            "runId": self.request["runId"],
            "sourceId": self.request["sourceId"],
            "hostId": self.request["hostId"],
            "trustDomain": self.request["trustDomain"],
            "sequence": self.sequence,
            "terminal": terminal,
            "terminalState": terminal_state,
            "recordCount": len(normalized_page),
            "byteCount": page_bytes,
            "cumulativeRecordCount": cumulative_records,
            "cumulativeByteCount": cumulative_bytes,
            "runningDigest": running_digest,
            "gapCode": gap_code,
            "records": normalized_page,
        }
        self.sequence += 1
        self.cumulative_records = cumulative_records
        self.cumulative_bytes = cumulative_bytes
        self.running_digest = running_digest
        self.identities.update(page_identities)
        self.terminal = terminal
        return page
