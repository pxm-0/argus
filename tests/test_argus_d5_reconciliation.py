from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_cli import run  # noqa: E402
from argus_observations import ObservationRepository, SourceRegistry, digest  # noqa: E402
from argus_reconciliation import reconcile  # noqa: E402


SOURCE_ID = "oreochiserver.reference-compose"


def registry_payload() -> dict:
    return json.loads((ROOT / "tests/fixtures/observation/reference-registry.json").read_text())


def record(project: str, native_id: str = "container-1") -> dict:
    return {
        "schemaVersion": 1,
        "resourceKind": "container",
        "nativeId": native_id,
        "observedAt": "2026-08-05T00:00:01Z",
        "attributes": {"lifecycle": "running", "name": project, "project": project},
        "provenance": {"adapter": "fixture", "adapterVersion": "1", "ordinal": 0},
    }


class D5ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "config/argus").mkdir(parents=True)
        (self.root / "config/workloads.json").write_text(json.dumps({
            "version": 1,
            "workloads": [{
                "id": "demo",
                "runtime": {"composeProject": "demo"},
            }],
        }))
        (self.root / "config/argus/workload-classification.json").write_text(json.dumps({
            "schemaVersion": 1,
            "workloads": {"demo": {"trustDomain": "personal-sandbox"}},
        }))
        (self.root / "config/argus/legacy-classification.json").write_text(json.dumps({
            "trustDomain": "personal-sandbox",
        }))
        (self.root / "config/argus/observation-sources.json").write_text(json.dumps(registry_payload()))
        (self.root / "config/privacy.json").write_text(json.dumps({"workloads": {"demo": {}}}))
        (self.root / "config/access.json").write_text(json.dumps({"workloads": {"demo": {}}}))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def setup_repository(self, payload: dict | None = None) -> tuple[SourceRegistry, ObservationRepository]:
        registry = SourceRegistry(payload or registry_payload(), ["personal-sandbox"])
        repository = ObservationRepository(self.root / "observations.sqlite3")
        repository.sync_registry(registry, explicit_clock="2026-08-05T00:00:00Z")
        self.addCleanup(repository.close)
        return registry, repository

    def ingest(self, registry: SourceRegistry, repository: ObservationRepository, *, state: str = "completed", records=None, gap=None) -> None:
        repository.ingest(
            registry,
            run_id=f"run-{repository.connection.execute('SELECT COUNT(*) FROM collection_runs').fetchone()[0] + 1}",
            source_id=SOURCE_ID,
            sequence=None,
            state=state,
            started_at="2026-08-05T00:00:00Z",
            terminal_at="2026-08-05T00:00:01Z",
            records=records or [],
            gap_code=gap,
        )

    def test_empty_and_unknown_are_incomplete_or_unknown_without_mutation_authority(self) -> None:
        registry, repository = self.setup_repository()
        empty = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T00:01:00Z")
        self.assertEqual("incomplete", empty["workloads"][0]["state"])
        self.assertFalse(empty["safeToMoveWorkloads"])
        self.assertIn("source-never-observed", {item["code"] for item in empty["blockers"]})

        self.ingest(registry, repository, records=[record("other")])
        unknown = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T00:01:00Z")
        self.assertEqual("unknown", unknown["workloads"][0]["state"])
        self.assertIn("workload-identity-unknown", {item["code"] for item in unknown["blockers"]})

    def test_known_stale_and_failed_states_are_distinct(self) -> None:
        registry, repository = self.setup_repository()
        self.ingest(registry, repository, records=[record("demo")])
        known = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T00:01:00Z")
        self.assertEqual("known", known["workloads"][0]["state"])
        self.assertTrue(known["safeToMoveWorkloads"])
        self.assertEqual("none", known["mutationAuthority"])

        stale = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T01:00:00Z")
        self.assertEqual("stale", stale["workloads"][0]["state"])
        self.ingest(registry, repository, state="failed", gap="fixture-failed")
        failed = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T01:00:00Z")
        self.assertEqual("failed", failed["workloads"][0]["state"])

    def test_conflicting_domains_and_repeated_digest_are_fail_closed(self) -> None:
        payload = registry_payload()
        second = copy.deepcopy(payload["sources"][0])
        second["sourceId"] = "oreochiserver.work.reference-compose"
        second["hostId"] = "oreochiserver"
        second["trustDomain"] = "work-sandbox"
        payload["hostSources"].append(second["sourceId"])
        payload["sources"].append(second)
        registry, repository = self.setup_repository(payload)
        self.ingest(registry, repository, records=[record("demo", "personal")])
        repository.ingest(
            registry,
            run_id="run-work",
            source_id="oreochiserver.work.reference-compose",
            sequence=None,
            state="completed",
            started_at="2026-08-05T00:00:00Z",
            terminal_at="2026-08-05T00:00:01Z",
            records=[record("demo", "work")],
        )
        first = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T00:01:00Z")
        second_result = reconcile(self.root, repository, registry, explicit_clock="2026-08-05T00:01:00Z")
        self.assertEqual("conflicting", first["workloads"][0]["state"])
        self.assertFalse(first["safeToMoveWorkloads"])
        self.assertEqual(digest(first), digest(second_result))

    def test_cli_exposes_only_the_sanitized_reconciliation_view(self) -> None:
        registry, repository = self.setup_repository()
        self.ingest(registry, repository, records=[record("demo")])
        repository.close()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {
            "ARGUS_OBSERVATIONS_DB": str(self.root / "observations.sqlite3"),
            "ARGUS_OBSERVATIONS_CLOCK": "2026-08-05T00:01:00Z",
        }, clear=False):
            code = run(["estate", "coverage", "--json"], repo=self.root, stdout=stdout, stderr=stderr)
        payload = json.loads(stdout.getvalue())
        reconciliation = payload["data"]["reconciliation"]
        self.assertEqual(0, code)
        self.assertEqual("complete", reconciliation["status"])
        self.assertEqual("known", reconciliation["workloads"][0]["state"])
        self.assertFalse("attributes" in json.dumps(reconciliation))
        self.assertEqual("none", reconciliation["mutationAuthority"])
        self.assertEqual("", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
