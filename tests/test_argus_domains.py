"""D030: config/argus/domains.json is the one list of trust domains; every other list must agree."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_domains  # noqa: E402
from argus_host_guard import HOST_EGRESS  # noqa: E402
from argus_sudoers import rootless_domains  # noqa: E402
import argus_sandbox_firewall  # noqa: E402

DOMAIN_NAME = re.compile(r"\b(?:legacy-rootful|(?:personal|work)-(?:sandbox|managed))\b")
WORKLOAD = set(argus_domains.ids(kind="workload"))
ROOTLESS = set(argus_domains.ids(rootless=True))


def entry(**overrides: object) -> dict[str, object]:
    return {"id": "cell", "kind": "workload", "role": "sandbox", "rootless": True, **overrides}


def names_in(text: str) -> set[str]:
    return set(DOMAIN_NAME.findall(text))


class RegistryTest(unittest.TestCase):
    def test_roles_map_to_the_d030_cells(self) -> None:
        self.assertEqual("sandbox (work-sandbox)", argus_domains.label("work-sandbox"))
        self.assertEqual("staging (personal-sandbox)", argus_domains.label("personal-sandbox"))
        self.assertEqual("prod (personal-managed)", argus_domains.label("personal-managed"))
        self.assertEqual("quarantine (legacy-rootful)", argus_domains.label("legacy-rootful"))
        self.assertEqual("management", argus_domains.label("management"))

    def test_only_staging_to_prod_promotes(self) -> None:
        self.assertIsNone(argus_domains.promotion_refusal("personal-sandbox", "personal-managed"))
        domains = argus_domains.ids()
        allowed = [(a, b) for a in domains for b in domains if argus_domains.promotion_refusal(a, b) is None]
        self.assertEqual([("personal-sandbox", "personal-managed")], allowed)
        self.assertIn("unknown trust domain", argus_domains.promotion_refusal("personal-sandbox", "elsewhere"))

    def test_malformed_registries_are_refused(self) -> None:
        cases = {
            "wrong version": {"schemaVersion": 2, "domains": []},
            "extra field": {"schemaVersion": 1, "domains": [entry(extra=1)]},
            "unknown kind": {"schemaVersion": 1, "domains": [entry(kind="lab")]},
            "unknown role": {"schemaVersion": 1, "domains": [entry(role="dev")]},
            "duplicate id": {"schemaVersion": 1, "domains": [entry(role=None), entry(role=None)]},
            "duplicate role": {"schemaVersion": 1, "domains": [entry(), entry(id="other")]},
            "rootless legacy": {"schemaVersion": 1, "domains": [entry(kind="legacy")]},
            "bad id": {"schemaVersion": 1, "domains": [entry(id="../cell")]},
        }
        for name, payload in cases.items():
            with self.subTest(name), self.assertRaises(argus_domains.DomainRegistryError):
                argus_domains.parse(payload)


class DriftTest(unittest.TestCase):
    """Lists that cannot import the registry (shell, schemas, policy maps) must still match it."""

    def test_rootless_cells_match_the_observation_sources(self) -> None:
        self.assertEqual(ROOTLESS, set(rootless_domains(ROOT)))

    def test_policy_maps_cover_exactly_the_workload_cells(self) -> None:
        self.assertEqual(WORKLOAD, set(HOST_EGRESS))
        self.assertEqual(WORKLOAD, argus_sandbox_firewall.DOMAINS)

    def test_shell_bootstrap_guards_match(self) -> None:
        for script in ("argus-m4-personal-sandbox-bootstrap", "argus-m5-sandbox-bootstrap"):
            text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            guard = re.search(r"\[\[ \"\$\w+\" == [^{]*\]\]", text, re.S)
            self.assertIsNotNone(guard, script)
            self.assertEqual(WORKLOAD, names_in(guard.group(0)), script)

    def test_server_sim_provisions_the_rootless_cells(self) -> None:
        text = (ROOT / "infra" / "server-sim" / "provision").read_text(encoding="utf-8")
        line = re.search(r"^readonly DOMAINS=\((.*)\)$", text, re.M)
        self.assertIsNotNone(line)
        self.assertEqual(ROOTLESS, set(line.group(1).split()))

    def test_schemas_match(self) -> None:
        manifest = json.loads((ROOT / "config/schemas/workload-manifest.schema.json").read_text(encoding="utf-8"))
        migration = manifest["properties"]["migration"]["properties"]
        self.assertEqual(WORKLOAD, set(migration["targetTrustDomain"]["enum"]))
        self.assertEqual(WORKLOAD | set(argus_domains.ids(kind="legacy")), set(migration["runtimeTrustDomain"]["enum"]))
        plan = (ROOT / "config/schemas/workload-onboarding-plan.schema.json").read_text(encoding="utf-8")
        self.assertEqual(WORKLOAD, names_in(plan))

    def test_registered_workloads_sit_in_registered_cells(self) -> None:
        workloads = json.loads((ROOT / "config/workloads.json").read_text(encoding="utf-8"))["workloads"]
        for item in workloads:
            self.assertIn(item["migration"]["targetTrustDomain"], WORKLOAD, item["id"])
        classification = json.loads((ROOT / "config/argus/workload-classification.json").read_text(encoding="utf-8"))
        for workload_id, item in classification["workloads"].items():
            self.assertIn(item["trustDomain"], WORKLOAD, workload_id)

    def test_dev_runs_target_the_sandbox_cell(self) -> None:
        self.assertEqual("work-sandbox", argus_domains.cell("sandbox"))
        self.assertEqual(argus_domains.cell("sandbox"), argus_sandbox_firewall.DEV_DOMAIN)
        dev_sandbox = (ROOT / "scripts" / "argus-dev-sandbox").read_text(encoding="utf-8")
        self.assertIn('DOMAIN = argus_domains.cell("sandbox")', dev_sandbox)
        with self.assertRaises(argus_domains.DomainRegistryError):
            argus_domains.cell("dev")


if __name__ == "__main__":
    unittest.main()
