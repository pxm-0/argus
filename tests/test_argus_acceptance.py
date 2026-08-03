from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_acceptance import (  # noqa: E402
    AcceptanceError,
    REASON_CODES,
    RESULT_REASON_CODES,
    RUN_KEYS,
    TOP_LEVEL_KEYS,
    render_markdown,
    validate,
)


def valid_payload() -> dict:
    return {
        "schemaVersion": 1,
        "issueId": 270,
        "phase": "baseline",
        "target": "oreochiserver",
        "checkId": "cross-project-reachability",
        "expectedRuns": 3,
        "sourceRevision": "abcdef1",
        "capturedAt": "2026-08-03T16:00:00Z",
        "evidenceId": "sha256:" + "a" * 64,
        "runs": [
            {"ordinal": 1, "result": "fail", "durationMs": 12, "reasonCode": "unexpected-reachability"},
            {"ordinal": 2, "result": "fail", "durationMs": 10, "reasonCode": "unexpected-reachability"},
            {"ordinal": 3, "result": "fail", "durationMs": 11, "reasonCode": "unexpected-reachability"},
        ],
    }


class AcceptanceSummaryTests(unittest.TestCase):
    def test_summary_is_deterministic_and_markdown_is_allowlisted(self) -> None:
        first = validate(valid_payload())
        second = validate(copy.deepcopy(valid_payload()))
        self.assertEqual(first, second)
        self.assertEqual("fail", first["result"])
        self.assertTrue(first["summaryDigest"].startswith("sha256:"))
        markdown = render_markdown(first)
        self.assertIn("| cross-project-reachability | baseline | oreochiserver | 3/3 | fail |", markdown)
        self.assertEqual(1, len(markdown.splitlines()))
        self.assertNotIn("unexpected-reachability", markdown)

    def test_unknown_fields_are_rejected_as_secret_hostile(self) -> None:
        for field in ("password", "token", "rawOutput", "address"):
            payload = valid_payload()
            payload[field] = "sensitive"
            with self.subTest(field=field), self.assertRaises(AcceptanceError) as raised:
                validate(payload)
            self.assertEqual("acceptance-field-forbidden", raised.exception.code)
            self.assertNotIn(field, str(raised.exception))

    def test_run_unknown_fields_and_wrong_count_are_rejected(self) -> None:
        payload = valid_payload()
        payload["runs"][0]["stdout"] = "private topology"
        with self.assertRaises(AcceptanceError) as raised:
            validate(payload)
        self.assertEqual("acceptance-field-forbidden", raised.exception.code)

        payload = valid_payload()
        payload["runs"].pop()
        with self.assertRaises(AcceptanceError) as raised:
            validate(payload)
        self.assertEqual("acceptance-run-count", raised.exception.code)

    def test_fail_takes_precedence_over_blocked(self) -> None:
        payload = valid_payload()
        payload["runs"][1] = {"ordinal": 2, "result": "blocked", "durationMs": 0, "reasonCode": "server-access-unavailable"}
        self.assertEqual("fail", validate(payload)["result"])

    def test_schema_integer_and_enum_types_are_enforced(self) -> None:
        mutations = (
            ("issueId", True),
            ("schemaVersion", True),
            ("expectedRuns", True),
            ("expectedRuns", 2),
            ("phase", ["baseline"]),
            ("target", ["oreochiserver"]),
        )
        for field, value in mutations:
            payload = valid_payload()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(AcceptanceError):
                validate(payload)
        payload = valid_payload()
        payload["runs"][0]["ordinal"] = True
        with self.assertRaises(AcceptanceError):
            validate(payload)
        payload = valid_payload()
        payload["runs"][0]["result"] = ["fail"]
        with self.assertRaises(AcceptanceError):
            validate(payload)

    def test_timestamp_must_exist_on_the_calendar(self) -> None:
        payload = valid_payload()
        payload["capturedAt"] = "2026-99-99T99:99:99Z"
        with self.assertRaises(AcceptanceError):
            validate(payload)

    def test_runtime_allowlists_match_the_checked_in_schema(self) -> None:
        schema = json.loads((ROOT / "config" / "schemas" / "acceptance-summary.schema.json").read_text())
        self.assertEqual(TOP_LEVEL_KEYS, set(schema["required"]))
        run_schema = schema["properties"]["runs"]["allOf"][0]["items"]
        self.assertEqual(RUN_KEYS, set(run_schema["required"]))
        self.assertEqual(REASON_CODES, set(run_schema["properties"]["reasonCode"]["enum"]))
        self.assertEqual(3, schema["properties"]["expectedRuns"]["const"])
        self.assertEqual(3, schema["properties"]["runs"]["minItems"])
        self.assertEqual(3, schema["properties"]["runs"]["maxItems"])
        self.assertEqual(
            RESULT_REASON_CODES["pass"],
            {run_schema["allOf"][0]["then"]["properties"]["reasonCode"]["const"]},
        )
        ordinal_contract = schema["properties"]["runs"]["allOf"][1]["prefixItems"]
        self.assertEqual([1, 2, 3], [item["properties"]["ordinal"]["const"] for item in ordinal_contract])

    def test_integral_json_numbers_are_canonically_normalized(self) -> None:
        payload = valid_payload()
        payload["schemaVersion"] = 1.0
        payload["issueId"] = 270.0
        payload["expectedRuns"] = 3.0
        payload["runs"][0]["ordinal"] = 1.0
        payload["runs"][0]["durationMs"] = 12.0
        summary = validate(payload)
        self.assertEqual(1, summary["schemaVersion"])
        self.assertEqual(270, summary["issueId"])
        self.assertEqual(1, summary["runs"][0]["ordinal"])
        self.assertEqual(12, summary["runs"][0]["durationMs"])

    def test_result_and_reason_code_must_agree(self) -> None:
        contradictory = (("pass", "check-failed"), ("fail", ""), ("blocked", "unexpected-reachability"))
        for result, reason in contradictory:
            payload = valid_payload()
            payload["runs"][0] = {"ordinal": 1, "result": result, "durationMs": 1, "reasonCode": reason}
            with self.subTest(result=result, reason=reason), self.assertRaises(AcceptanceError) as raised:
                validate(payload)
            self.assertEqual("acceptance-result-reason-conflict", raised.exception.code)

    def test_executable_help_json_markdown_and_unreadable_errors(self) -> None:
        executable = ROOT / "scripts" / "argus-acceptance-summary"
        help_result = subprocess.run([str(executable), "--help"], text=True, capture_output=True, check=False)
        self.assertEqual(0, help_result.returncode)
        for contract in ("Privilege: unprivileged, read-only", "Prerequisites:", "Side effects:", "Output:", "Example:", "Recovery:"):
            self.assertIn(contract, help_result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "summary.json"
            input_path.write_text(json.dumps(valid_payload()))
            for output_format in ("json", "markdown"):
                result = subprocess.run(
                    [str(executable), "--input", str(input_path), "--format", output_format],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                if output_format == "json":
                    envelope = json.loads(result.stdout)
                    self.assertTrue(envelope["ok"])
                    self.assertIn("summaryDigest", envelope["data"])
            unreadable = subprocess.run(
                [str(executable), "--input", directory, "--format", "markdown"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(4, unreadable.returncode)
            self.assertIn("ERROR acceptance-input-unreadable", unreadable.stderr)
            self.assertNotIn(directory, unreadable.stderr)
            oversized_path = Path(directory) / "oversized.json"
            oversized_path.write_bytes(b" " * 65537)
            oversized = subprocess.run(
                [str(executable), "--input", str(oversized_path), "--format", "markdown"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(3, oversized.returncode)
            self.assertIn("acceptance-input-oversized", oversized.stderr)
            duplicate_path = Path(directory) / "duplicate.json"
            duplicate_path.write_text('{"schemaVersion":1,"schemaVersion":1}')
            duplicate = subprocess.run(
                [str(executable), "--input", str(duplicate_path), "--format", "markdown"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(3, duplicate.returncode)
            self.assertIn("acceptance-json-duplicate", duplicate.stderr)

            missing = subprocess.run(
                [str(executable), "--input", str(Path(directory) / "missing.json"), "--format", "json"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(4, missing.returncode)
            self.assertEqual("", missing.stderr)
            self.assertEqual("acceptance-input-missing", json.loads(missing.stdout)["error"]["code"])

            nested_path = Path(directory) / "nested.json"
            nested_path.write_text("[" * 30000 + "]" * 30000)
            nested = subprocess.run(
                [str(executable), "--input", str(nested_path), "--format", "markdown"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(3, nested.returncode)
            self.assertIn("acceptance-json-invalid", nested.stderr)
            self.assertNotIn("Traceback", nested.stderr)

            large_integer_path = Path(directory) / "large-integer.json"
            large_integer_path.write_text("[" + "9" * 5000 + "]")
            large_integer = subprocess.run(
                [str(executable), "--input", str(large_integer_path), "--format", "json"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(3, large_integer.returncode)
            self.assertEqual("", large_integer.stderr)
            self.assertEqual("acceptance-json-invalid", json.loads(large_integer.stdout)["error"]["code"])
            self.assertNotIn("Traceback", large_integer.stdout)


if __name__ == "__main__":
    unittest.main()
