from __future__ import annotations

import copy
import json
import os
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_collectors import (  # noqa: E402
    CollectionResult,
    CollectorError,
    CollectorScheduler,
    PageBuilder,
    PageValidator,
    collect_from_socket,
    collection_request,
)
from argus_fixture_adapter import adapt_fixture  # noqa: E402
from argus_ipc import receive_frame, send_frame  # noqa: E402
from argus_observations import ObservationError, ObservationRepository, SourceRegistry  # noqa: E402


OBSERVATION_FIXTURES = ROOT / "tests" / "fixtures" / "observation"


def registry_payload(root: Path, *, count: int = 1, protocols: list[int] | None = None) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    base = json.loads((OBSERVATION_FIXTURES / "reference-registry.json").read_text())
    template = base["sources"][0]
    sources = []
    host_sources = []
    for index in range(count):
        source = copy.deepcopy(template)
        source_id = f"oreochiserver.reference-{index}"
        source["sourceId"] = source_id
        runtime = root / f"source-{index}"
        runtime.mkdir(mode=0o750)
        runtime.chmod(0o750)
        source["transport"] = {
            "kind": "unix-stream",
            "socketPath": str(runtime / "collector.sock"),
            "parentPath": str(runtime),
            "parentUid": os.getuid(),
            "parentGid": os.getgid(),
            "parentMode": "0750",
            "socketUid": os.getuid(),
            "socketGid": os.getgid(),
            "socketMode": "0660",
            "peerUid": os.getuid(),
            "peerGid": os.getgid(),
            "protocolVersions": protocols or [1, 2],
        }
        sources.append(source)
        host_sources.append(source_id)
    return {"schemaVersion": 2, "hostSources": host_sources, "sources": sources}


def configured_registry(root: Path, *, count: int = 1, protocols: list[int] | None = None) -> SourceRegistry:
    return SourceRegistry(registry_payload(root, count=count, protocols=protocols), ["personal-sandbox"])


def normalized_records(source) -> list[dict]:
    return adapt_fixture(OBSERVATION_FIXTURES / "reference-compose.json", source)


def completed_pages(source, request: dict, *, split: bool = True) -> list[dict]:
    records = normalized_records(source)
    builder = PageBuilder(source, request)
    if not split:
        return [builder.build(records, terminal=True, terminal_state="completed", gap_code=None)]
    first = builder.build(
        records[:1], terminal=False,
        terminal_state=None, gap_code=None,
    )
    second = builder.build(
        records[1:], terminal=True, terminal_state="completed", gap_code=None,
    )
    return [first, second]


class UnixPageServer:
    def __init__(self, source, handler):
        self.source = source
        self.handler = handler
        self.requests: list[dict] = []
        self.errors: list[Exception] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(source.transport["socketPath"])
        os.chmod(source.transport["socketPath"], 0o660)
        self.server.listen(1)
        self.server.settimeout(0.1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                connection, _address = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                with connection:
                    request = receive_frame(connection)
                    self.requests.append(request)
                    pages = self.handler(request)
                    if pages is not None:
                        for page in pages:
                            send_frame(connection, page)
            except (OSError, ValueError) as exc:
                self.errors.append(exc)
            return

    def close(self) -> None:
        self.stop.set()
        self.server.close()
        self.thread.join(timeout=2)
        Path(self.source.transport["socketPath"]).unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class CollectorPageProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.temporary.name)
        self.registry = configured_registry(self.root)
        self.source = next(iter(self.registry.sources.values()))
        self.request = collection_request(
            self.source,
            refresh_id="refresh-1",
            run_id="run-1",
            explicit_clock="2026-08-05T00:00:00Z",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_multi_page_empty_and_current_previous_protocols(self) -> None:
        validator = PageValidator(self.source, self.request)
        result = None
        for page in completed_pages(self.source, self.request):
            result = validator.accept(page)
        validator.finish()
        self.assertEqual("completed", result.state)
        self.assertEqual(normalized_records(self.source), result.records)
        empty = PageBuilder(self.source, self.request).build(
            [], terminal=True, terminal_state="completed", gap_code=None,
        )
        empty_result = PageValidator(self.source, self.request).accept(empty)
        self.assertEqual([], empty_result.records)
        previous_registry = configured_registry(self.root / "previous", protocols=[1])
        previous_source = next(iter(previous_registry.sources.values()))
        previous = collection_request(
            previous_source, refresh_id="refresh-v1", run_id="run-v1",
            explicit_clock="2026-08-05T00:00:00Z",
        )
        self.assertEqual(1, previous["protocolVersion"])

    def test_portable_unix_socket_path_boundary_is_103_bytes(self) -> None:
        parent = "/" + "p" * 95
        accepted = registry_payload(self.root / "path-accepted")
        accepted["sources"][0]["transport"]["parentPath"] = parent
        accepted["sources"][0]["transport"]["socketPath"] = parent + "/" + "s" * 6
        SourceRegistry(accepted, ["personal-sandbox"])
        rejected = copy.deepcopy(accepted)
        rejected["sources"][0]["transport"]["socketPath"] = parent + "/" + "s" * 7
        with self.assertRaisesRegex(ObservationError, "socketPath must be non-empty bounded text"):
            SourceRegistry(rejected, ["personal-sandbox"])

    def test_repeated_and_shuffled_inputs_are_protocol_deterministic(self) -> None:
        original = normalized_records(self.source)
        shuffled = list(reversed(original))
        first = PageBuilder(self.source, self.request).build(
            original, terminal=True, terminal_state="completed", gap_code=None,
        )
        for _iteration in range(100):
            replay = PageBuilder(self.source, self.request).build(
                shuffled, terminal=True, terminal_state="completed", gap_code=None,
            )
            self.assertEqual(first, replay)
            result = PageValidator(self.source, self.request).accept(replay)
            self.assertEqual(original, result.records)

    def test_identity_version_sequence_replay_and_terminal_fail_closed(self) -> None:
        valid = completed_pages(self.source, self.request, split=False)[0]
        mutations = (
            ("protocolVersion", 3, "version-mismatch"),
            ("protocolVersion", 0, "version-mismatch"),
            ("refreshId", "wrong", "refreshId-mismatch"),
            ("runId", "wrong", "runId-mismatch"),
            ("sourceId", "wrong", "sourceId-mismatch"),
            ("hostId", "wrong", "hostId-mismatch"),
            ("trustDomain", "work-sandbox", "trustDomain-mismatch"),
            ("sequence", 2, "page-sequence-invalid"),
        )
        for field, value, reason in mutations:
            page = copy.deepcopy(valid)
            page[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(CollectorError, reason):
                PageValidator(self.source, self.request).accept(page)
        validator = PageValidator(self.source, self.request)
        validator.accept(valid)
        with self.assertRaisesRegex(CollectorError, "page-after-terminal"):
            validator.accept(valid)
        nonterminal = completed_pages(self.source, self.request)[0]
        validator = PageValidator(self.source, self.request)
        validator.accept(nonterminal)
        with self.assertRaisesRegex(CollectorError, "terminal-missing"):
            validator.finish()

    def test_request_identity_and_nonterminal_empty_page_fail_closed(self) -> None:
        wrong_request = copy.deepcopy(self.request)
        wrong_request["trustDomain"] = "work-sandbox"
        with self.assertRaisesRegex(CollectorError, "request-invalid"):
            PageValidator(self.source, wrong_request)
        validator = PageValidator(self.source, self.request)
        with self.assertRaisesRegex(CollectorError, "terminal-invalid"):
            page = PageBuilder(self.source, self.request).build(
                [], terminal=True, terminal_state="completed", gap_code=None,
            )
            page["terminal"] = False
            page["terminalState"] = None
            validator.accept(page)

    def test_counts_bytes_digest_shape_and_records_fail_closed(self) -> None:
        valid = completed_pages(self.source, self.request, split=False)[0]
        mutations = (
            ("recordCount", valid["recordCount"] + 1, "page-count-mismatch"),
            ("byteCount", valid["byteCount"] + 1, "page-byte-mismatch"),
            ("cumulativeRecordCount", valid["cumulativeRecordCount"] + 1, "cumulative-count-mismatch"),
            ("cumulativeByteCount", valid["cumulativeByteCount"] + 1, "cumulative-byte-mismatch"),
            ("runningDigest", "sha256:" + "0" * 64, "running-digest-mismatch"),
        )
        for field, value, reason in mutations:
            page = copy.deepcopy(valid)
            page[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(CollectorError, reason):
                PageValidator(self.source, self.request).accept(page)
        unknown = copy.deepcopy(valid)
        unknown["native"] = "forbidden"
        with self.assertRaisesRegex(CollectorError, "envelope-invalid"):
            PageValidator(self.source, self.request).accept(unknown)
        malformed = copy.deepcopy(valid)
        malformed["records"][0]["attributes"]["environment"] = {"TOKEN": "redacted"}
        with self.assertRaisesRegex(CollectorError, "record-invalid"):
            PageValidator(self.source, self.request).accept(malformed)

        for bound, value in (("maxRecords", 1), ("maxOutputBytes", 1), ("maxRecordBytes", 1)):
            payload = registry_payload(self.root / f"bounded-{bound}")
            payload["sources"][0]["bounds"][bound] = value
            bounded_source = next(iter(SourceRegistry(payload, ["personal-sandbox"]).sources.values()))
            bounded_request = collection_request(
                bounded_source,
                refresh_id=self.request["refreshId"],
                run_id=self.request["runId"],
                explicit_clock=self.request["explicitClock"],
            )
            with self.subTest(bound=bound), self.assertRaisesRegex(CollectorError, "record-invalid"):
                PageValidator(bounded_source, bounded_request).accept(valid)

    def test_partial_and_failed_terminal_contract(self) -> None:
        builder = PageBuilder(self.source, self.request)
        first = builder.build(
            normalized_records(self.source)[:1], terminal=False, terminal_state=None, gap_code=None,
        )
        partial = builder.build(
            [], terminal=True, terminal_state="partial", gap_code="collector-disconnected",
        )
        invalid_failed = copy.deepcopy(partial)
        invalid_failed["terminalState"] = "failed"
        invalid_failed["gapCode"] = "collector-failed"
        validator = PageValidator(self.source, self.request)
        validator.accept(first)
        with self.assertRaisesRegex(CollectorError, "terminal-invalid"):
            validator.accept(invalid_failed)
        validator = PageValidator(self.source, self.request)
        validator.accept(first)
        result = validator.accept(partial)
        self.assertEqual("partial", result.state)
        self.assertEqual(1, len(result.records))
        unsafe_gap = copy.deepcopy(partial)
        unsafe_gap["gapCode"] = "TOKEN=secret"
        validator = PageValidator(self.source, self.request)
        validator.accept(first)
        with self.assertRaisesRegex(CollectorError, "terminal-invalid"):
            validator.accept(unsafe_gap)


class CollectorSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.temporary.name)
        self.registry = configured_registry(self.root)
        self.source = next(iter(self.registry.sources.values()))
        self.request = collection_request(
            self.source, refresh_id="refresh-socket", run_id="run-socket",
            explicit_clock="2026-08-05T00:00:00Z",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_authenticated_socket_collects_valid_pages(self) -> None:
        with UnixPageServer(self.source, lambda request: completed_pages(self.source, request)) as server:
            result = collect_from_socket(self.source, self.request, 2)
        self.assertEqual("completed", result.state)
        self.assertEqual(normalized_records(self.source), result.records)
        self.assertEqual([self.request], server.requests)

    def test_socket_single_page_empty_and_current_previous_versions(self) -> None:
        for protocol, empty in ((2, False), (1, True)):
            registry = configured_registry(self.root / f"socket-v{protocol}", protocols=[protocol])
            source = next(iter(registry.sources.values()))
            request = collection_request(
                source, refresh_id=f"socket-v{protocol}", run_id=f"socket-v{protocol}",
                explicit_clock="2026-08-05T00:00:00Z",
            )

            def pages(received_request):
                records = [] if empty else list(reversed(normalized_records(source)))
                return [PageBuilder(source, received_request).build(
                    records, terminal=True, terminal_state="completed", gap_code=None,
                )]

            with UnixPageServer(source, pages):
                result = collect_from_socket(source, request, 1)
            self.assertEqual(protocol, result.protocol_version)
            self.assertEqual([] if empty else normalized_records(source), result.records)

    def test_terminal_requires_eof_and_rejects_trailing_frame(self) -> None:
        terminal = completed_pages(self.source, self.request, split=False)[0]
        with UnixPageServer(self.source, lambda _request: [terminal, terminal]):
            with self.assertRaisesRegex(CollectorError, "page-after-terminal"):
                collect_from_socket(self.source, self.request, 1)

        def keep_open(_request):
            yield terminal
            time.sleep(0.2)

        with UnixPageServer(self.source, keep_open):
            with self.assertRaisesRegex(CollectorError, "collector-timeout"):
                collect_from_socket(self.source, self.request, 0.03)

    def test_disconnect_and_timeout_preserve_validated_partial_records(self) -> None:
        with UnixPageServer(
            self.source,
            lambda request: completed_pages(self.source, request)[:1],
        ):
            with self.assertRaisesRegex(CollectorError, "collector-disconnected") as disconnected:
                collect_from_socket(self.source, self.request, 2)
        self.assertEqual(1, len(disconnected.exception.records))

        def delayed(request):
            time.sleep(0.2)
            return completed_pages(self.source, request, split=False)

        with UnixPageServer(self.source, delayed):
            with self.assertRaisesRegex(CollectorError, "collector-timeout"):
                collect_from_socket(self.source, self.request, 0.02)

        def drip(request):
            records = normalized_records(self.source)
            builder = PageBuilder(self.source, request)
            for sequence in range(1, 3):
                time.sleep(0.03)
                page = builder.build(
                    records[:1] if sequence == 1 else [],
                    terminal=sequence == 2,
                    terminal_state="completed" if sequence == 2 else None,
                    gap_code=None,
                )
                yield page

        with UnixPageServer(self.source, drip):
            with self.assertRaisesRegex(CollectorError, "collector-timeout"):
                collect_from_socket(self.source, self.request, 0.05)

    def test_parent_socket_and_peer_binding_mismatches_fail_closed(self) -> None:
        with UnixPageServer(self.source, lambda request: completed_pages(self.source, request, split=False)):
            for field, value, reason in (
                ("parentMode", "0700", "parent-binding-mismatch"),
                ("parentUid", os.getuid() + 1, "parent-binding-mismatch"),
                ("parentGid", os.getgid() + 1, "parent-binding-mismatch"),
                ("socketMode", "0600", "socket-binding-mismatch"),
                ("socketUid", os.getuid() + 1, "socket-binding-mismatch"),
                ("socketGid", os.getgid() + 1, "socket-binding-mismatch"),
            ):
                payload = registry_payload(self.root / field)
                payload["sources"][0]["transport"]["socketPath"] = self.source.transport["socketPath"]
                payload["sources"][0]["transport"]["parentPath"] = self.source.transport["parentPath"]
                payload["sources"][0]["transport"][field] = value
                wrong = next(iter(SourceRegistry(payload, ["personal-sandbox"]).sources.values()))
                with self.subTest(field=field), self.assertRaisesRegex(CollectorError, reason):
                    collect_from_socket(wrong, collection_request(
                        wrong, refresh_id="wrong", run_id="wrong", explicit_clock="2026-08-05T00:00:00Z"
                    ), 1)

    def test_wrong_parent_and_socket_types_fail_closed(self) -> None:
        parent_payload = registry_payload(self.root / "parent-type")
        parent_path = Path(parent_payload["sources"][0]["transport"]["parentPath"])
        parent_path.rmdir()
        parent_path.write_text("not-a-directory", encoding="utf-8")
        parent_source = next(iter(SourceRegistry(parent_payload, ["personal-sandbox"]).sources.values()))
        with self.assertRaisesRegex(CollectorError, "parent-binding-mismatch"):
            collect_from_socket(parent_source, collection_request(
                parent_source, refresh_id="parent-type", run_id="parent-type",
                explicit_clock="2026-08-05T00:00:00Z",
            ), 1)

        socket_payload = registry_payload(self.root / "socket-type")
        socket_path = Path(socket_payload["sources"][0]["transport"]["socketPath"])
        socket_path.write_text("not-a-socket", encoding="utf-8")
        socket_path.chmod(0o660)
        socket_source = next(iter(SourceRegistry(socket_payload, ["personal-sandbox"]).sources.values()))
        with self.assertRaisesRegex(CollectorError, "socket-binding-mismatch"):
            collect_from_socket(socket_source, collection_request(
                socket_source, refresh_id="socket-type", run_id="socket-type",
                explicit_clock="2026-08-05T00:00:00Z",
            ), 1)

    @unittest.skipUnless(
        sys.platform.startswith("linux") or sys.platform == "darwin",
        "Unix peer credential assertion requires Linux or macOS",
    )
    def test_wrong_peer_credentials_fail_closed(self) -> None:
        payload = registry_payload(self.root / "peer")
        payload["sources"][0]["transport"]["peerUid"] = os.getuid() + 1
        wrong_peer_registry = SourceRegistry(payload, ["personal-sandbox"])
        wrong_peer = next(iter(wrong_peer_registry.sources.values()))
        request = collection_request(
            wrong_peer, refresh_id="peer", run_id="peer", explicit_clock="2026-08-05T00:00:00Z"
        )
        with UnixPageServer(wrong_peer, lambda req: completed_pages(wrong_peer, req, split=False)):
            with self.assertRaisesRegex(CollectorError, "peer-credentials-mismatch"):
                collect_from_socket(wrong_peer, request, 1)

    def test_socket_replacement_fails_closed(self) -> None:
        with UnixPageServer(self.source, lambda req: completed_pages(self.source, req, split=False)):
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

            def replace() -> None:
                Path(self.source.transport["socketPath"]).unlink()
                replacement.bind(self.source.transport["socketPath"])
                os.chmod(self.source.transport["socketPath"], 0o660)
                replacement.listen(1)

            try:
                with self.assertRaisesRegex(CollectorError, "socket-replaced"):
                    collect_from_socket(self.source, self.request, 1, pre_connect_hook=replace)
            finally:
                replacement.close()

    def test_parent_replacement_fails_closed(self) -> None:
        parent = Path(self.source.transport["parentPath"])
        moved = parent.with_name(parent.name + "-moved")
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        with UnixPageServer(self.source, lambda req: completed_pages(self.source, req, split=False)):
            def replace_parent() -> None:
                parent.rename(moved)
                parent.mkdir(mode=0o750)
                parent.chmod(0o750)
                replacement.bind(self.source.transport["socketPath"])
                os.chmod(self.source.transport["socketPath"], 0o660)
                replacement.listen(1)

            try:
                with self.assertRaisesRegex(CollectorError, "parent-replaced"):
                    collect_from_socket(self.source, self.request, 1, pre_connect_hook=replace_parent)
            finally:
                replacement.close()
                Path(self.source.transport["socketPath"]).unlink(missing_ok=True)


class CollectorSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.temporary.name)
        self.registry = configured_registry(self.root, count=3)
        self.repository = ObservationRepository(self.root / "observations.sqlite3")

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_empty_registry_is_not_configured(self) -> None:
        empty = SourceRegistry({"schemaVersion": 2, "hostSources": [], "sources": []}, ["personal-sandbox"])
        scheduler = CollectorScheduler(self.repository, empty)
        result = scheduler.refresh(refresh_id="empty", explicit_clock="2026-08-05T00:00:00Z")
        self.assertEqual("not-configured", result["status"])
        self.assertEqual([], result["sources"])

    def test_repository_persists_transport_digest_not_socket_binding(self) -> None:
        self.repository.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
        rows = self.repository.connection.execute(
            "SELECT registry_json FROM sources ORDER BY source_id"
        ).fetchall()
        for row in rows:
            persisted = row[0]
            self.assertIn("transportDigest", persisted)
            self.assertNotIn("collector.sock", persisted)
            self.assertNotIn(str(self.root), persisted)

    def test_scheduler_caps_concurrency_and_commits_in_source_order(self) -> None:
        active = 0
        maximum = 0
        lock = threading.Lock()

        def collect(source, request, timeout):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep({"oreochiserver.reference-0": 0.03, "oreochiserver.reference-1": 0.01}.get(source.source_id, 0.02))
            with lock:
                active -= 1
            return CollectionResult("completed", normalized_records(source), None, request["protocolVersion"])

        scheduler = CollectorScheduler(self.repository, self.registry, max_workers=2, collector=collect)
        result = scheduler.refresh(refresh_id="ordered", explicit_clock="2026-08-05T00:00:00Z")
        self.assertLessEqual(maximum, 2)
        self.assertEqual(sorted(self.registry.sources), [item["sourceId"] for item in result["sources"]])
        self.assertEqual("completed", result["status"])

    def test_partial_failure_preserves_source_specific_results_and_is_idempotent(self) -> None:
        calls = 0

        def collect(source, request, timeout):
            nonlocal calls
            calls += 1
            records = normalized_records(source)
            if source.source_id.endswith("-1"):
                raise CollectorError("collector-disconnected", records=records[:1])
            if source.source_id.endswith("-2"):
                raise CollectorError("collector-timeout")
            return CollectionResult("completed", records, None, request["protocolVersion"])

        scheduler = CollectorScheduler(self.repository, self.registry, collector=collect)
        first = scheduler.refresh(refresh_id="partial", explicit_clock="2026-08-05T00:00:00Z")
        replay = scheduler.refresh(refresh_id="partial", explicit_clock="2026-08-05T00:00:00Z")
        self.assertEqual(first, replay)
        self.assertEqual(3, calls)
        self.assertEqual("partial", first["status"])
        self.assertEqual(["completed", "partial", "failed"], [item["state"] for item in first["sources"]])
        self.assertEqual(
            [None, "collector-disconnected", "collector-timeout"],
            [item["gapCode"] for item in first["sources"]],
        )
        protocol_versions = [row[0] for row in self.repository.connection.execute(
            "SELECT protocol_version FROM collection_runs ORDER BY source_id"
        )]
        self.assertEqual([2, 2, 2], protocol_versions)
        with self.assertRaisesRegex(CollectorError, "refresh-id-conflict"):
            scheduler.refresh(refresh_id="partial", explicit_clock="2026-08-05T00:01:00Z")

    def test_repository_finalization_failure_isolated_and_all_reservations_terminal(self) -> None:
        def collect(source, request, timeout):
            if source.source_id.endswith("-0"):
                return CollectionResult("invalid", [], None, request["protocolVersion"])
            return CollectionResult("completed", [], None, request["protocolVersion"])

        result = CollectorScheduler(self.repository, self.registry, collector=collect).refresh(
            refresh_id="finalize-failure",
            explicit_clock="2026-08-05T00:00:00Z",
        )

        self.assertEqual("partial", result["status"])
        self.assertEqual("failed", result["sources"][0]["state"])
        self.assertEqual("repository-finalize-failed", result["sources"][0]["gapCode"])
        self.assertEqual(["completed", "completed"], [item["state"] for item in result["sources"][1:]])
        collecting = self.repository.connection.execute(
            "SELECT COUNT(*) FROM collection_runs WHERE state='collecting'"
        ).fetchone()[0]
        self.assertEqual(0, collecting)

    def test_global_deadline_does_not_discard_completed_source(self) -> None:
        def collect(source, request, timeout):
            if source.source_id.endswith("-0"):
                return CollectionResult("completed", [], None, request["protocolVersion"])
            time.sleep(0.08)
            return CollectionResult("completed", [], None, request["protocolVersion"])

        scheduler = CollectorScheduler(
            self.repository, self.registry, max_workers=3, global_timeout_milliseconds=20, collector=collect
        )
        result = scheduler.refresh(refresh_id="deadline", explicit_clock="2026-08-05T00:00:00Z")
        self.assertEqual("completed", result["sources"][0]["state"])
        self.assertEqual("scheduler-global-timeout", result["sources"][1]["gapCode"])
        self.assertEqual("scheduler-global-timeout", result["sources"][2]["gapCode"])

    def test_scheduler_enforces_per_source_timeout_even_for_custom_collector(self) -> None:
        payload = registry_payload(self.root / "source-timeout", count=1)
        payload["sources"][0]["bounds"]["timeoutMilliseconds"] = 10
        registry = SourceRegistry(payload, ["personal-sandbox"])

        def collect(source, request, timeout):
            time.sleep(0.03)
            return CollectionResult("completed", [], None, request["protocolVersion"])

        scheduler = CollectorScheduler(
            self.repository,
            registry,
            global_timeout_milliseconds=200,
            collector=collect,
        )
        result = scheduler.refresh(refresh_id="source-timeout", explicit_clock="2026-08-05T00:00:00Z")
        self.assertEqual("failed", result["sources"][0]["state"])
        self.assertEqual("collector-timeout", result["sources"][0]["gapCode"])

    def test_abandoned_test_collectors_are_daemonized_and_globally_bounded(self) -> None:
        registry = configured_registry(self.root / "daemon-bound", count=1)
        release = threading.Event()
        lock = threading.Lock()
        active = 0
        maximum = 0

        def collect(source, request, timeout):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                release.wait(timeout=2)
                return CollectionResult("completed", [], None, request["protocolVersion"])
            finally:
                with lock:
                    active -= 1

        try:
            for ordinal in range(35):
                CollectorScheduler(
                    self.repository,
                    registry,
                    max_workers=1,
                    global_timeout_milliseconds=5,
                    collector=collect,
                ).refresh(
                    refresh_id=f"daemon-{ordinal}",
                    explicit_clock="2026-08-05T00:00:00Z",
                )
            workers = [thread for thread in threading.enumerate() if thread.name.startswith("argus-collector-")]
            self.assertLessEqual(maximum, 32)
            self.assertLessEqual(len(workers), 32)
            self.assertTrue(all(thread.daemon for thread in workers))
        finally:
            release.set()
            deadline = time.monotonic() + 2
            while active and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(0, active)

    def test_new_refresh_supersedes_source_snapshots(self) -> None:
        def collect(source, request, timeout):
            return CollectionResult("completed", [], None, request["protocolVersion"])

        scheduler = CollectorScheduler(self.repository, self.registry, collector=collect)
        first = scheduler.refresh(refresh_id="first", explicit_clock="2026-08-05T00:00:00Z")
        second = scheduler.refresh(refresh_id="second", explicit_clock="2026-08-05T00:01:00Z")
        for old, new in zip(first["sources"], second["sources"]):
            superseded = self.repository.connection.execute(
                "SELECT superseded_by FROM collection_runs WHERE run_id=?", (old["runId"],)
            ).fetchone()[0]
            self.assertEqual(new["runId"], superseded)

    def test_concurrent_refreshes_allocate_unique_sequences_atomically(self) -> None:
        registry = configured_registry(self.root / "concurrent", count=1)
        database = self.root / "concurrent.sqlite3"
        with ObservationRepository(database) as repository:
            repository.sync_registry(registry, explicit_clock="2026-08-05T00:00:00Z")
        barrier = threading.Barrier(2)
        results: list[dict] = []
        errors: list[Exception] = []

        def worker(refresh_id: str) -> None:
            try:
                with ObservationRepository(database) as repository:
                    def collect(source, request, timeout):
                        barrier.wait(timeout=2)
                        return CollectionResult("completed", [], None, request["protocolVersion"])

                    scheduler = CollectorScheduler(repository, registry, collector=collect)
                    results.append(scheduler.refresh(
                        refresh_id=refresh_id,
                        explicit_clock="2026-08-05T00:00:00Z",
                    ))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(refresh_id,)) for refresh_id in ("race-a", "race-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        with ObservationRepository(database, read_only=True) as repository:
            sequences = [row[0] for row in repository.connection.execute(
                "SELECT sequence FROM collection_runs ORDER BY sequence"
            )]
        self.assertEqual([1, 2], sequences)

    def test_identical_concurrent_refresh_is_reserved_once(self) -> None:
        registry = configured_registry(self.root / "same-refresh", count=1)
        database = self.root / "same-refresh.sqlite3"
        entered = threading.Event()
        release = threading.Event()
        first_results: list[dict] = []
        first_errors: list[Exception] = []

        def first_worker() -> None:
            try:
                with ObservationRepository(database) as repository:
                    def collect(source, request, timeout):
                        entered.set()
                        release.wait(timeout=2)
                        return CollectionResult(
                            "completed", normalized_records(source), None, request["protocolVersion"]
                        )

                    first_results.append(CollectorScheduler(repository, registry, collector=collect).refresh(
                        refresh_id="same-refresh",
                        explicit_clock="2026-08-05T00:00:00Z",
                    ))
            except Exception as exc:
                first_errors.append(exc)

        thread = threading.Thread(target=first_worker)
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        second_calls = 0
        try:
            with ObservationRepository(database) as repository:
                def second_collect(source, request, timeout):
                    nonlocal second_calls
                    second_calls += 1
                    return CollectionResult("completed", [], None, request["protocolVersion"])

                with self.assertRaisesRegex(CollectorError, "refresh-in-progress"):
                    CollectorScheduler(repository, registry, collector=second_collect).refresh(
                        refresh_id="same-refresh",
                        explicit_clock="2026-08-05T00:00:00Z",
                    )
        finally:
            release.set()
            thread.join(timeout=5)
        self.assertEqual(0, second_calls)
        self.assertEqual([], first_errors)
        self.assertEqual(1, len(first_results))

    def test_non_ascii_refresh_id_fails_before_reservation(self) -> None:
        scheduler = CollectorScheduler(self.repository, self.registry, collector=lambda *_args: None)
        with self.assertRaisesRegex(CollectorError, "refresh-id-invalid"):
            scheduler.refresh(refresh_id="e\u0301", explicit_clock="2026-08-05T00:00:00Z")
        count = self.repository.connection.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0]
        self.assertEqual(0, count)

    def test_collector_module_has_no_mutation_or_model_authority(self) -> None:
        source = (ROOT / "scripts" / "argus_collectors.py").read_text(encoding="utf-8").casefold()
        for forbidden in (
            "operationledger", "capability", "docker.sock", "subprocess", "shell=true",
            "openai", "anthropic", "mutation_authority", "effective_access",
        ):
            self.assertNotIn(forbidden, source)

    def test_acceptance_runner_emits_valid_three_run_local_summary(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "argus-collector-protocol-acceptance"),
                "--root", str(ROOT),
                "--source-revision", "5bc84f5",
                "--captured-at", "2026-08-05T00:00:00Z",
                "--target", "local-ci",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        summary = json.loads(completed.stdout)
        self.assertEqual(307, summary["issueId"])
        self.assertEqual(3, len(summary["runs"]))
        self.assertIn('"protocolVersions":[1,2]', completed.stderr)

    def test_acceptance_rejects_persisted_evidence_divergence(self) -> None:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-collector-protocol-acceptance"))
        baseline = {
            "protocolVersions": [1, 2],
            "resultDigest": "sha256:result",
            "snapshotDigests": ["sha256:snapshot"],
            "persistedDigest": "sha256:persisted-a",
        }
        divergent = dict(baseline, persistedDigest="sha256:persisted-b")
        with self.assertRaisesRegex(ObservationError, "repeated collector evidence differs"):
            namespace["validate_repeated_measurements"]([baseline, baseline, divergent])


if __name__ == "__main__":
    unittest.main()
