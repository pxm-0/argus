from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_fixture_adapter import adapt_fixture  # noqa: E402
import argus_observations  # noqa: E402
from argus_observations import (  # noqa: E402
    ObservationError,
    ObservationRepository,
    SourceRegistry,
    canonical_trust_domains,
    digest,
    normalize_records,
)


FIXTURES = ROOT / "tests" / "fixtures" / "observation"


def registry_payload() -> dict:
    return json.loads((FIXTURES / "reference-registry.json").read_text())


def registry(*, domains: tuple[str, ...] = ("personal-sandbox",)) -> SourceRegistry:
    return SourceRegistry(registry_payload(), domains)


def fixture_records(source_registry: SourceRegistry) -> list[dict]:
    source = source_registry.sources["oreochiserver.reference-compose"]
    return adapt_fixture(FIXTURES / "reference-compose.json", source)


class ObservationRegistryTests(unittest.TestCase):
    def test_canonical_domains_are_derived_and_empty_registry_is_not_configured(self) -> None:
        self.assertEqual(
            ["legacy-rootful", "personal-sandbox", "work-sandbox"],
            canonical_trust_domains(ROOT),
        )
        empty = SourceRegistry({"schemaVersion": 1, "hostSources": [], "sources": []}, ["work-sandbox"])
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(empty, explicit_clock="2026-08-05T00:00:00Z")
            coverage = repo.coverage(empty, explicit_clock_epoch=1785888000)
        self.assertEqual("not-configured", coverage["status"])
        self.assertEqual([{"kind": "configuration-gap", "trustDomain": "work-sandbox"}], coverage["gaps"])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ObservationError, "source is missing"):
                canonical_trust_domains(Path(directory))

    def test_omitted_domain_duplicate_source_and_unknown_registry_version_fail_closed(self) -> None:
        configured = registry(domains=("personal-sandbox", "work-sandbox"))
        self.assertEqual(
            [{"kind": "configuration-gap", "trustDomain": "work-sandbox"}],
            configured.configuration_gaps(),
        )
        duplicate = registry_payload()
        duplicate["sources"].append(copy.deepcopy(duplicate["sources"][0]))
        with self.assertRaisesRegex(ObservationError, "duplicate source"):
            SourceRegistry(duplicate, [])
        future = registry_payload()
        future["schemaVersion"] = 3
        with self.assertRaisesRegex(ObservationError, "unsupported source registry version"):
            SourceRegistry(future, [])
        missing_host = registry_payload()
        missing_host["hostSources"].append("oreochiserver.missing-host-source")
        host_registry = SourceRegistry(missing_host, ["personal-sandbox"])
        self.assertIn(
            {"kind": "configuration-gap", "sourceId": "oreochiserver.missing-host-source"},
            host_registry.configuration_gaps(),
        )

    def test_expired_exclusion_is_visible_and_reenable_requires_new_evidence(self) -> None:
        payload = registry_payload()
        payload["sources"][0]["exclusion"] = {
            "owner": "argus-operator",
            "reason": "maintenance",
            "expiresAt": "2026-08-05T00:01:00Z",
        }
        excluded = SourceRegistry(payload, ["personal-sandbox"])
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(excluded, explicit_clock="2026-08-05T00:00:00Z")
            before = repo.coverage(excluded, explicit_clock_epoch=1785888000)
            after = repo.coverage(excluded, explicit_clock_epoch=1785888061)
        self.assertEqual("excluded", before["sources"][0]["state"])
        self.assertEqual("never_observed", after["sources"][0]["state"])
        self.assertEqual("expired-exclusion", after["gaps"][0]["kind"])

    def test_source_removal_retains_history_but_deactivates_ingest(self) -> None:
        configured = registry()
        empty = SourceRegistry({"schemaVersion": 1, "hostSources": [], "sources": []}, [])
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(configured, explicit_clock="2026-08-05T00:00:00Z")
            repo.ingest(
                configured, run_id="run-1", source_id="oreochiserver.reference-compose", sequence=1,
                state="completed", started_at="2026-08-05T00:00:00Z", terminal_at="2026-08-05T00:00:01Z",
                records=fixture_records(configured),
            )
            repo.sync_registry(empty, explicit_clock="2026-08-05T00:05:00Z")
            row = repo.connection.execute(
                "SELECT active,removed_at,current_run_id FROM sources WHERE source_id=?",
                ("oreochiserver.reference-compose",),
            ).fetchone()
            self.assertEqual((0, "2026-08-05T00:05:00Z", "run-1"), tuple(row))
            with self.assertRaisesRegex(ObservationError, "active registry"):
                repo.ingest(
                    empty, run_id="run-2", source_id="oreochiserver.reference-compose", sequence=2,
                    state="completed", started_at="2026-08-05T00:06:00Z", terminal_at="2026-08-05T00:06:01Z",
                    records=[],
                )


class ObservationNormalizationTests(unittest.TestCase):
    def test_shuffled_native_fixture_has_byte_identical_snapshot_and_digest(self) -> None:
        configured = registry()
        source = configured.sources["oreochiserver.reference-compose"]
        payload = json.loads((FIXTURES / "reference-compose.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            shuffled = Path(directory) / "shuffled.json"
            payload["records"].reverse()
            shuffled.write_text(json.dumps(payload))
            first = adapt_fixture(FIXTURES / "reference-compose.json", source)
            second = adapt_fixture(shuffled, source)
        first_records, first_bytes, first_digest = normalize_records(source, first)
        second_records, second_bytes, second_digest = normalize_records(source, second)
        self.assertEqual(first_records, second_records)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(first_digest, digest({"sourceId": source.source_id, "records": first_records}))
        for _iteration in range(100):
            replay, replay_bytes, replay_digest = normalize_records(source, list(reversed(second)))
            self.assertEqual((first_records, first_bytes, first_digest), (replay, replay_bytes, replay_digest))

    def test_duplicate_native_identity_and_forbidden_fields_fail_closed(self) -> None:
        configured = registry()
        source = configured.sources["oreochiserver.reference-compose"]
        records = fixture_records(configured)
        with self.assertRaisesRegex(ObservationError, "duplicate native identity"):
            normalize_records(source, [records[0], copy.deepcopy(records[0])])
        hostile = copy.deepcopy(records[0])
        hostile["attributes"]["environment"] = {"API_KEY": "redacted"}
        with self.assertRaisesRegex(ObservationError, "non-allowlisted"):
            normalize_records(source, [hostile])
        for forbidden in (
            "commandLine", "environment", "fileContent", "gitRemote", "credential",
            "canonicalIdentity", "policy", "effectiveAccess", "authorization", "mutationAuthority",
        ):
            hostile = copy.deepcopy(records[0])
            hostile["attributes"][forbidden] = "must-not-enter"
            with self.subTest(forbidden=forbidden), self.assertRaisesRegex(ObservationError, "non-allowlisted"):
                normalize_records(source, [hostile])

    def test_same_native_id_is_scoped_by_source_and_run(self) -> None:
        payload = registry_payload()
        second = copy.deepcopy(payload["sources"][0])
        second["sourceId"] = "oreochiserver.second-reference"
        payload["sources"].append(second)
        configured = SourceRegistry(payload, ["personal-sandbox"])
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(configured, explicit_clock="2026-08-05T00:00:00Z")
            for source_id in sorted(configured.sources):
                records = adapt_fixture(FIXTURES / "reference-compose.json", configured.sources[source_id])
                repo.ingest(
                    configured, run_id=f"run-{source_id}", source_id=source_id, sequence=1,
                    state="completed", started_at="2026-08-05T00:00:00Z", terminal_at="2026-08-05T00:00:01Z",
                    records=records,
                )
            count = repo.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        self.assertEqual(4, count)

    def test_future_normalized_record_and_native_adapter_fields_fail_closed(self) -> None:
        configured = registry()
        source = configured.sources["oreochiserver.reference-compose"]
        future = fixture_records(configured)[0]
        future["schemaVersion"] = 3
        with self.assertRaisesRegex(ObservationError, "unsupported normalized"):
            normalize_records(source, [future])
        payload = json.loads((FIXTURES / "reference-compose.json").read_text())
        payload["records"][0]["Mounts"] = ["/private"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hostile.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ObservationError, "unknown or missing fields"):
                adapt_fixture(path, source)

    def test_current_and_previous_normalized_versions_are_readable_but_secret_markers_are_not(self) -> None:
        configured = registry()
        source = configured.sources["oreochiserver.reference-compose"]
        previous = fixture_records(configured)[0]
        current = copy.deepcopy(previous)
        current["schemaVersion"] = 2
        current["nativeId"] = "sha256:current"
        records, _size, _digest = normalize_records(source, [previous, current])
        self.assertEqual([1, 2], sorted(record["schemaVersion"] for record in records))
        hostile = copy.deepcopy(previous)
        hostile["attributes"]["name"] = "token=not-safe-even-in-an-allowed-field"
        with self.assertRaisesRegex(ObservationError, "secret marker"):
            normalize_records(source, [hostile])

    def test_record_count_record_bytes_and_output_bytes_stop_at_the_declared_bounds(self) -> None:
        base = registry_payload()
        sample = fixture_records(registry())[0]
        cases = (
            ("maxRecords", {"maxRecords": 1}, [sample, {**copy.deepcopy(sample), "nativeId": "second"}]),
            ("maxRecordBytes", {"maxRecordBytes": 100}, [sample]),
            ("maxOutputBytes", {"maxOutputBytes": 200}, [sample]),
        )
        for message, changed_bounds, records in cases:
            payload = copy.deepcopy(base)
            payload["sources"][0]["bounds"].update(changed_bounds)
            configured = SourceRegistry(payload, ["personal-sandbox"])
            with self.subTest(bound=message), self.assertRaisesRegex(ObservationError, message):
                normalize_records(configured.sources["oreochiserver.reference-compose"], records)

    def test_repository_consumer_does_not_reference_fixture_native_field_names(self) -> None:
        consumer = (ROOT / "scripts" / "argus_observations.py").read_text(encoding="utf-8")
        for native_field in ("object_type", "object_id", "captured_at"):
            self.assertNotIn(native_field, consumer)


class ObservationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = registry()
        self.source_id = "oreochiserver.reference-compose"
        self.records = fixture_records(self.registry)

    def ingest(self, repo: ObservationRepository, sequence: int, state: str = "completed", records=None, gap=None):
        return repo.ingest(
            self.registry, run_id=f"run-{sequence}-{state}", source_id=self.source_id, sequence=sequence,
            state=state, started_at=f"2026-08-05T00:{sequence:02d}:00Z",
            terminal_at=f"2026-08-05T00:{sequence:02d}:01Z",
            records=self.records if records is None else records, gap_code=gap,
        )

    def test_valid_empty_run_is_current_and_source_transitions_fresh_to_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            result = self.ingest(repo, 1, records=[])
            future = repo.coverage(self.registry, explicit_clock_epoch=1785888001)
            fresh = repo.coverage(self.registry, explicit_clock_epoch=1785888061)
            stale = repo.coverage(self.registry, explicit_clock_epoch=1785889000)
        self.assertTrue(result["becameCurrent"])
        self.assertEqual(0, result["recordCount"])
        self.assertEqual("failed", future["sources"][0]["state"])
        self.assertEqual("source-clock-ahead", future["gaps"][0]["kind"])
        self.assertEqual("fresh", fresh["sources"][0]["state"])
        self.assertEqual("stale", stale["sources"][0]["state"])
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "other.sqlite3") as repo:
            with self.assertRaisesRegex(ObservationError, "source is unknown"):
                repo.current_snapshot("missing-source")

    def test_partial_and_failed_runs_preserve_last_known_good(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            good = self.ingest(repo, 1)
            partial = self.ingest(repo, 2, state="partial", records=self.records[:1], gap="collector-disconnected")
            failed = self.ingest(repo, 3, state="failed", records=[], gap="collector-timeout")
            current = repo.current_snapshot(self.source_id)
            coverage = repo.coverage(self.registry, explicit_clock_epoch=1785888181)
        self.assertTrue(good["becameCurrent"])
        self.assertFalse(partial["becameCurrent"])
        self.assertFalse(failed["becameCurrent"])
        self.assertEqual(self.records, current)
        self.assertEqual("failed", coverage["sources"][0]["state"])
        self.assertEqual("run-1-completed", coverage["sources"][0]["currentRunId"])
        self.assertEqual("run-3-failed", coverage["sources"][0]["latestRunId"])
        self.assertEqual("collector-timeout", coverage["gaps"][0]["gapCode"])

    def test_first_failed_run_is_visible_without_a_current_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            self.ingest(repo, 1, state="failed", records=[], gap="collector-unavailable")
            coverage = repo.coverage(self.registry, explicit_clock_epoch=1785888061)
        self.assertEqual("failed", coverage["sources"][0]["state"])
        self.assertIsNone(coverage["sources"][0]["currentRunId"])
        self.assertEqual("run-1-failed", coverage["sources"][0]["latestRunId"])
        self.assertEqual("collection-gap", coverage["gaps"][0]["kind"])

    def test_changed_source_contract_requires_new_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            self.ingest(repo, 1)
            changed_payload = registry_payload()
            changed_payload["sources"][0]["freshnessSloSeconds"] = 1200
            changed = SourceRegistry(changed_payload, ["personal-sandbox"])
            repo.sync_registry(changed, explicit_clock="2026-08-05T00:02:00Z")
            coverage = repo.coverage(changed, explicit_clock_epoch=1785888120)
        self.assertEqual("failed", coverage["sources"][0]["state"])
        self.assertEqual("source-contract-changed", coverage["gaps"][0]["kind"])
        self.assertEqual("run-1-completed", coverage["sources"][0]["currentRunId"])

    def test_atomic_switch_and_supersession_reject_stale_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            newer = self.ingest(repo, 2)
            older = self.ingest(repo, 1)
            current = repo.connection.execute(
                "SELECT current_run_id FROM sources WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
            superseded = repo.connection.execute(
                "SELECT superseded_by FROM collection_runs WHERE run_id='run-1-completed'"
            ).fetchone()[0]
            hostile = copy.deepcopy(self.records)
            hostile[0]["attributes"]["secret"] = "no"
            with self.assertRaises(ObservationError):
                self.ingest(repo, 3, records=hostile)
            current_after = repo.connection.execute(
                "SELECT current_run_id FROM sources WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
        self.assertTrue(newer["becameCurrent"])
        self.assertFalse(older["becameCurrent"])
        self.assertEqual("run-2-completed", current)
        self.assertEqual(current, superseded)
        self.assertEqual(current, current_after)

    def test_concurrent_duplicate_ingest_commits_exactly_one_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            with ObservationRepository(database) as setup:
                setup.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            barrier = threading.Barrier(2)
            outcomes: list[str] = []

            def ingest_same_run() -> None:
                with ObservationRepository(database) as repository:
                    barrier.wait()
                    try:
                        self.ingest(repository, 1)
                        outcomes.append("committed")
                    except ObservationError as exc:
                        outcomes.append(str(exc))

            threads = [threading.Thread(target=ingest_same_run) for _index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
            with ObservationRepository(database, read_only=True) as repository:
                run_count = repository.connection.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0]
        self.assertEqual(1, run_count)
        self.assertEqual(1, outcomes.count("committed"))
        self.assertEqual(1, sum("must be unique" in outcome for outcome in outcomes))

    def test_restart_recovery_marks_only_collecting_runs_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            self.ingest(repo, 1)
            with repo.connection:
                repo.connection.execute(
                    """INSERT INTO collection_runs(
                           run_id,source_id,sequence,repository_version,source_schema_version,
                           protocol_version,registry_digest,state,started_at)
                       VALUES('crashed',?,2,2,1,1,'sha256:test','collecting','2026-08-05T00:02:00Z')""",
                    (self.source_id,),
                )
            self.assertEqual(1, repo.recover_interrupted(terminal_at="2026-08-05T00:03:00Z"))
            crashed = repo.connection.execute(
                "SELECT state,gap_code FROM collection_runs WHERE run_id='crashed'"
            ).fetchone()
            current = repo.connection.execute(
                "SELECT current_run_id FROM sources WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
        self.assertEqual(("failed", "restart-interrupted"), tuple(crashed))
        self.assertEqual("run-1-completed", current)

    def test_migration_previous_read_compatibility_backup_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "observations.sqlite3"
            backup = root / "observations-v1.backup"
            ObservationRepository.create_version(database, 1)
            with ObservationRepository(database, read_only=True) as previous_reader:
                self.assertEqual(1, previous_reader.version)
            with ObservationRepository(database) as repo:
                self.assertEqual(1, repo.version)
                backup_digest = repo.backup(backup)
                repo.migrate()
                self.assertEqual(2, repo.version)
                self.assertEqual([], repo.connection.execute("SELECT * FROM reconciliation_links").fetchall())
            ObservationRepository.restore_backup(backup, database)
            with ObservationRepository(database, read_only=True) as rolled_back:
                self.assertEqual(1, rolled_back.version)
            self.assertRegex(backup_digest, r"^sha256:[0-9a-f]{64}$")

    def test_migration_failure_rolls_back_every_schema_statement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            ObservationRepository.create_version(database, 1)
            repository = ObservationRepository(database)
            statements = (
                "ALTER TABLE sources ADD COLUMN should_rollback TEXT",
                "THIS IS NOT VALID SQL",
            )
            with patch.object(argus_observations, "SCHEMA_V2_STATEMENTS", statements):
                with self.assertRaisesRegex(ObservationError, "migration failed"):
                    repository.migrate()
            columns = [row[1] for row in repository.connection.execute("PRAGMA table_info(sources)")]
            version = repository.connection.execute(
                "SELECT value FROM metadata WHERE key='repository_version'"
            ).fetchone()[0]
            repository.close()
        self.assertNotIn("should_rollback", columns)
        self.assertEqual("1", version)

    def test_unknown_repository_version_and_database_ceiling_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.sqlite3"
            ObservationRepository.create_version(path, 1)
            connection = sqlite3.connect(path)
            connection.execute("UPDATE metadata SET value='3' WHERE key='repository_version'")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ObservationError, "unsupported observation repository version"):
                ObservationRepository(path)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ObservationError, "database-size ceiling"):
                ObservationRepository(Path(directory) / "observations.sqlite3", max_database_bytes=1024)

    def test_database_ceiling_rolls_back_the_entire_oversized_run(self) -> None:
        payload = registry_payload()
        payload["sources"][0]["bounds"].update({
            "maxOutputBytes": 1048576,
            "maxRecords": 200,
            "maxRecordBytes": 4096,
        })
        configured = SourceRegistry(payload, ["personal-sandbox"])
        records = []
        for ordinal in range(100):
            records.append({
                "schemaVersion": 2,
                "resourceKind": "container",
                "nativeId": f"native-{ordinal:03d}",
                "observedAt": "2026-08-05T00:00:00Z",
                "attributes": {"lifecycle": "running", "name": "x" * 2000, "project": "fixture"},
                "provenance": {"adapter": "reference-compose", "adapterVersion": "2", "ordinal": ordinal},
            })
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(
            Path(directory) / "observations.sqlite3", max_database_bytes=65536
        ) as repo:
            repo.sync_registry(configured, explicit_clock="2026-08-05T00:00:00Z")
            with self.assertRaisesRegex(ObservationError, "database-size ceiling"):
                repo.ingest(
                    configured, run_id="oversized", source_id=self.source_id, sequence=1,
                    state="completed", started_at="2026-08-05T00:00:00Z",
                    terminal_at="2026-08-05T00:00:01Z", records=records,
                )
            self.assertEqual(0, repo.connection.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0])
            self.assertIsNone(repo.connection.execute("SELECT current_run_id FROM sources").fetchone()[0])

    def test_retention_preserves_current_and_rollback_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            for sequence in range(1, 6):
                self.ingest(repo, sequence)
            self.ingest(repo, 6, state="partial", records=self.records[:1], gap="disconnect")
            self.ingest(repo, 7, state="failed", records=[], gap="timeout")
            self.assertEqual(4, repo.prune(keep_completed=2, keep_failed=1))
            remaining = [row[0] for row in repo.connection.execute(
                "SELECT run_id FROM collection_runs ORDER BY sequence"
            )]
        self.assertEqual(["run-4-completed", "run-5-completed", "run-7-failed"], remaining)

    def test_pruning_preserves_runs_referenced_by_reconciliation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            for sequence in range(1, 4):
                self.ingest(repo, sequence)
            first = repo.current_snapshot(self.source_id)[0]
            with repo.connection:
                repo.connection.execute(
                    """INSERT INTO reconciliation_links(
                           link_id,source_id,resource_kind,native_id,run_id,canonical_ref,link_state,evidence_digest)
                       VALUES('link-1',?,?,?,?,?,?,?)""",
                    (
                        self.source_id, first["resourceKind"], first["nativeId"], "run-1-completed",
                        "workload:fixture", "candidate", "sha256:evidence",
                    ),
                )
            self.assertEqual(0, repo.prune(keep_completed=2, keep_failed=1))
            remaining = [row[0] for row in repo.connection.execute(
                "SELECT run_id FROM collection_runs ORDER BY sequence"
            )]
        self.assertEqual(["run-1-completed", "run-2-completed", "run-3-completed"], remaining)

    def test_collection_run_pins_repository_protocol_and_registry_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            self.ingest(repo, 1)
            row = repo.connection.execute(
                """SELECT repository_version,source_schema_version,protocol_version,registry_digest
                   FROM collection_runs WHERE run_id='run-1-completed'"""
            ).fetchone()
        self.assertEqual((2, 1, 1), tuple(row[:3]))
        self.assertRegex(row[3], r"^sha256:[0-9a-f]{64}$")

    def test_invalid_clock_and_duplicate_sequence_fail_closed_without_switching_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(self.registry, explicit_clock="2026-08-05T00:00:00Z")
            self.ingest(repo, 1)
            with self.assertRaisesRegex(ObservationError, "canonical UTC"):
                repo.ingest(
                    self.registry, run_id="bad-clock", source_id=self.source_id, sequence=2,
                    state="completed", started_at="today", terminal_at="later", records=[],
                )
            with self.assertRaisesRegex(ObservationError, "must be unique"):
                repo.ingest(
                    self.registry, run_id="duplicate-sequence", source_id=self.source_id, sequence=1,
                    state="completed", started_at="2026-08-05T01:00:00Z",
                    terminal_at="2026-08-05T01:00:01Z", records=[],
                )
            current = repo.connection.execute(
                "SELECT current_run_id FROM sources WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
        self.assertEqual("run-1-completed", current)

    def test_repository_schema_has_no_canonical_policy_access_or_authority_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            schema = " ".join(row[0] or "" for row in repo.connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table'"
            )).casefold()
        for forbidden in ("effective_access", "authorization", "mutation_authority", "canonical_identity", "policy_decision"):
            self.assertNotIn(forbidden, schema)

    def test_central_source_row_contains_digests_not_command_or_api_allowlists(self) -> None:
        configured = registry()
        payload = copy.deepcopy(registry_payload())
        payload["sources"][0]["allowlist"]["commands"] = [["/usr/bin/example", "--read-only"]]
        payload["sources"][0]["allowlist"]["apis"] = ["unix:/run/example.sock:List"]
        configured = SourceRegistry(payload, ["personal-sandbox"])
        with tempfile.TemporaryDirectory() as directory, ObservationRepository(Path(directory) / "observations.sqlite3") as repo:
            repo.sync_registry(configured, explicit_clock="2026-08-05T00:00:00Z")
            persisted = repo.connection.execute("SELECT registry_json FROM sources").fetchone()[0]
        self.assertNotIn("/usr/bin/example", persisted)
        self.assertNotIn("unix:/run/example.sock", persisted)
        self.assertIn("allowlistDigest", persisted)

    def test_acceptance_runner_emits_a_valid_three_run_local_summary(self) -> None:
        completed = subprocess.run(
            [
                str(ROOT / "scripts" / "argus-observation-repository-acceptance"),
                "--root", str(ROOT),
                "--source-revision", "a16e803",
                "--captured-at", "2026-08-05T00:00:00Z",
                "--target", "local-ci",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        summary = json.loads(completed.stdout)
        self.assertEqual("local-ci", summary["target"])
        self.assertEqual(3, len(summary["runs"]))
        self.assertIn("\"databaseBytes\":[", completed.stderr)


if __name__ == "__main__":
    unittest.main()
