from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_cli_format as fmt  # noqa: E402
from argus_alerting import iso  # noqa: E402
from argus_cli import run  # noqa: E402
from argus_operations import OperationLedger  # noqa: E402


class HumanFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "config" / "argus").mkdir(parents=True)
        (self.root / "workloads" / "demo").mkdir(parents=True)
        fixtures = {
            "config/workloads.json": {"workloads": [{"id": "demo", "name": "Demo", "kind": "web-app", "lifecycle": "active", "migration": {"status": "planned"}}]},
            "config/privacy.json": {"workloads": {"demo": {"privacy": "personal"}}},
            "config/access.json": {"workloads": {"demo": {"desired": "tailnet", "effective": "tailnet"}}},
            "config/argus/workload-classification.json": {"workloads": {"demo": {"trustDomain": "personal-sandbox"}}},
            "workloads/demo/manifest.json": {"operations": {"logs": {"allowed": True}, "restart": {"allowed": False}}},
        }
        for relative, payload in fixtures.items():
            (self.root / relative).write_text(json.dumps(payload))

    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run(argv, repo=self.root, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def human_and_json(self, argv: list[str]) -> tuple[str, dict]:
        code, human, _ = self.invoke(argv)
        json_code, raw, _ = self.invoke([*argv, "--json"])
        self.assertEqual(code, json_code)
        self.assertNotIn("{", human)
        payload = json.loads(raw)
        self.assertEqual(raw, json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        return human, payload

    def test_age_and_table_helpers(self) -> None:
        self.assertEqual(["-", "59s", "2m", "3h", "4d"], [fmt.age(value) for value in (None, 59, 120, 3 * 3600 + 5, 4 * 86400)])
        out = io.StringIO()
        fmt.table([["A", "LONGER"], ["value\x1b[31m", None]], out)
        self.assertEqual("A              LONGER\nvalue\\x1b[31m  -\n", out.getvalue())

    def test_workload_list_and_show(self) -> None:
        human, _ = self.human_and_json(["workload", "list"])
        self.assertRegex(human, r"^ID\s+TRUST_DOMAIN\s+MIGRATION\s+LIFECYCLE\s+ACCESS\s+PRIVACY\n")
        self.assertRegex(human, r"(?m)^demo\s+personal-sandbox\s+planned\s+active\s+tailnet\s+personal$")
        human, _ = self.human_and_json(["workload", "show", "demo"])
        self.assertIn("trustDomain       personal-sandbox", human)
        self.assertIn("capabilities      logs allowed; restart denied", human)

    def test_estate_status_and_coverage(self) -> None:
        human, payload = self.human_and_json(["estate", "status"])
        self.assertIn("COVERAGE 0/8 sources fresh (incomplete)", human)
        self.assertIn("REFRESH never-run", human)
        self.assertIn("NEXT " + payload["data"]["nextAction"], human)
        human, _ = self.human_and_json(["estate", "coverage"])
        self.assertIn("COVERAGE 0/8", human)

    def test_alerts_smoke_and_backup(self) -> None:
        now = time.time()
        (self.root / "runtime" / "alerts").mkdir(parents=True)
        alerts = [{"id": "unit-failed:x.service", "severity": "page", "since": iso(now - 600), "detail": "x failed", "acked": False}]
        (self.root / "runtime" / "alerts" / "state.json").write_text(json.dumps({"generatedAt": iso(now), "alerts": alerts}))
        human, _ = self.human_and_json(["alerts"])
        self.assertRegex(human, r"(?m)^ALERTS 1 open, 1 page; state age \d+s$")
        self.assertRegex(human, r"(?m)^unit-failed:x\.service\s+page\s+" + iso(now - 600) + r"\s+no\s+x failed$")

        smoke = self.root / "runtime" / "smoke"
        smoke.mkdir(parents=True)
        (smoke / "latest.json").write_text(json.dumps({"ok": True, "timestamp": iso(now - 7200)}))
        (smoke / "smoke-history.jsonl").write_text(json.dumps({"timestamp": iso(now - 7200), "ok": False, "failedChecks": ["FAIL a", "FAIL b"]}) + "\n")
        human, _ = self.human_and_json(["smoke", "status"])
        self.assertIn("SMOKE latest passed; age 2h", human)
        self.assertRegex(human, r"(?m)^" + iso(now - 7200) + r"\s+failed\s+FAIL a; FAIL b$")

        pull = self.root / "pull"
        pull.mkdir()
        (pull / "a.tar.age").write_text("x")
        env = {"ARGUS_SNAPSHOT_PULL_DIR": str(pull), "ARGUS_SNAPSHOT_LAST": str(self.root / "absent"), "ARGUS_BACKUP_STATUS": str(self.root / "absent")}
        with mock.patch.dict(os.environ, env):
            human, _ = self.human_and_json(["backup", "freshness"])
        self.assertIn("BACKUP all fresh: no", human)
        self.assertRegex(human, r"(?m)^snapshot-last\s+unavailable\s+-\s+\d+[dh]$")

    def test_operation_list_and_show(self) -> None:
        ledger = self.root / "operations.sqlite3"
        operation, _ = OperationLedger(ledger).create(
            workload_id="demo", trust_domain="personal-sandbox", operation_type="health.refresh",
            requested_by="operator@example.com", parameters={}, preview_digest="p", expected_revision="r",
            policy_version="1", idempotency_key="format",
        )
        with mock.patch.dict(os.environ, {"ARGUS_OPERATIONS_DB": str(ledger)}):
            human, _ = self.human_and_json(["operation", "list"])
            self.assertRegex(human, r"^ID\s+WORKLOAD\s+TYPE\s+STATE\s+CREATED\s+FINISHED\n")
            self.assertRegex(human, rf"(?m)^{operation['operation_id']}\s+demo\s+health.refresh\s+queued\s+\S+Z\s+-$")
            human, _ = self.human_and_json(["operation", "show", operation["operation_id"]])
        self.assertIn("state             queued", human)
        self.assertIn("finished_at       -", human)


if __name__ == "__main__":
    unittest.main()
