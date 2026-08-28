from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_observations import load_registry  # noqa: E402
from argus_optional_evidence_collector import collect_process_listeners  # noqa: E402


SOURCE_IDS = {
    "oreochiserver.configured-roots",
    "oreochiserver.process-listeners",
    "oreochiserver.proxy-overlay",
}


class OptionalEvidenceCollectorTests(unittest.TestCase):
    def test_fixture_acceptance_is_three_run_and_sanitized(self) -> None:
        result = subprocess.run(
            [
                str(ROOT / "scripts/argus-d4-optional-evidence-acceptance"),
                "--root", str(ROOT),
                "--source-revision", "c4b4293",
                "--captured-at", "2026-08-11T00:00:00Z",
                "--target", "local-ci",
            ],
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")},
        )
        payload = json.loads(result.stdout)
        self.assertEqual(325, payload["issueId"])
        self.assertEqual(3, payload["expectedRuns"])
        self.assertEqual(["pass", "pass", "pass"], [run["result"] for run in payload["runs"]])
        self.assertNotIn("/srv/", result.stdout + result.stderr)
        self.assertNotIn("docker compose", result.stdout + result.stderr)

    def test_sources_have_independent_bounds_and_socket_bindings(self) -> None:
        registry = load_registry(ROOT / "config/argus/observation-sources.json", ROOT)
        sources = {source_id: registry.sources[source_id] for source_id in SOURCE_IDS}
        self.assertEqual(3, len(sources))
        self.assertEqual(3, len({source.transport["socketPath"] for source in sources.values()}))
        self.assertEqual(SOURCE_IDS, set(sources))
        self.assertEqual("filesystem:reviewed-root-summaries", sources["oreochiserver.configured-roots"].allowlist["apis"][0])
        self.assertEqual(2, len(sources["oreochiserver.process-listeners"].allowlist["commands"]))

    def test_fixture_measurement_does_not_expose_provider_payload(self) -> None:
        result = subprocess.run(
            [
                str(ROOT / "scripts/argus-d4-optional-evidence-acceptance"),
                "--root", str(ROOT),
                "--source-revision", "c4b4293",
                "--captured-at", "2026-08-11T00:00:00Z",
                "--target", "local-ci",
            ],
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")},
        )
        self.assertNotIn("enabled", result.stderr)
        self.assertNotIn("127.0.0.1", result.stderr)

    def test_kernel_threads_are_outside_the_minimized_process_scope_not_a_coverage_gap(self) -> None:
        registry = load_registry(ROOT / "config/argus/observation-sources.json", ROOT)
        source = registry.sources["oreochiserver.process-listeners"]

        def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            payloads = {
                ("ps", "-eo", "comm=,state="): b"[kthreadd] I\nsystemd S\nnginx S\n",
                ("ss", "-H", "-lntu", "-n"): b"tcp LISTEN 0 511 127.0.0.1:8080 0.0.0.0:*\n",
            }
            return subprocess.CompletedProcess(argv, 0, payloads[tuple(argv)], b"")

        records, gap, state = collect_process_listeners(
            source,
            {"explicitClock": "2026-08-28T00:00:00Z"},
            runner=runner,
        )
        self.assertEqual("completed", state)
        self.assertIsNone(gap)
        self.assertEqual({"process-summary", "listener"}, {item["resourceKind"] for item in records})


if __name__ == "__main__":
    unittest.main()
