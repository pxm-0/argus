from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import io
import json
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_cloudflare_activation as activation  # noqa: E402
import argus_common  # noqa: E402
from argus_cloudflare_allowlist import (  # noqa: E402
    AllowlistError,
    IngressError,
    allowlisted_hostnames,
    effective_blockers,
    has_stage_evidence,
    ingress_problems,
    is_allowlisted,
    parse_ingress,
    provider_ready,
    public_allowlist,
)


WORKLOAD = "site-production"
HOST = "site.example.com"
ALLOWED = SimpleNamespace(allowed=True, decision_code="allowed", as_dict=lambda: {"allowed": True})


def exposure(*, enabled: bool = True, allowlist: list | None = None, quick: bool = False) -> dict:
    return {
        "providers": {
            "tailscale": {"funnel": {"observedEnabled": False}},
            "cloudflare": {
                "enabled": enabled,
                "provisioned": enabled,
                "allowNamedTunnels": enabled,
                "allowQuickTunnels": quick,
                "activationConfigPath": "/nonexistent/argus-test/cloudflared.yml",
                "publicAllowlist": [{"workloadId": WORKLOAD, "hostnames": [HOST, "www." + HOST]}] if allowlist is None else allowlist,
            },
        }
    }


def evidence(mode: str, *, workload_id: str = WORKLOAD, hostname: str = HOST, recorded: str = "2026-11-01T00:00:00Z") -> dict:
    probe = {"status": 302, "accessBlocked": True} if mode == "protected" else {"status": 200, "accessBlocked": False}
    payload = {
        "ok": True, "workloadId": workload_id, "mode": mode, "hostname": hostname, "hostnames": [hostname],
        "validation": {"ok": True}, "unauthenticatedProbes": {hostname: probe}, "recordedAt": recorded,
    }
    return {**payload, "authenticatedConfirmed": True} if mode == "protected" else payload


def rolled_back(recorded: str, *, workload_id: str = WORKLOAD) -> dict:
    return {"ok": True, "workloadId": workload_id, "mode": "rolledBack", "hostnames": [HOST], "recordedAt": recorded}


INGRESS_OK = f'ingress:\n  - hostname: "{HOST}"\n    service: "http://127.0.0.1:9"\n  - service: http_status:404\n'


class AllowlistShapeTests(unittest.TestCase):
    def test_shipped_exposure_config_has_an_empty_allowlist_and_provider_off(self) -> None:
        config = json.loads((ROOT / "config" / "exposure.json").read_text())
        cloudflare = config["providers"]["cloudflare"]
        self.assertEqual([], cloudflare["publicAllowlist"])
        self.assertEqual({}, public_allowlist(config))
        self.assertFalse(cloudflare["enabled"] or cloudflare["provisioned"] or cloudflare["allowNamedTunnels"] or cloudflare["allowQuickTunnels"])

    def test_malformed_entries_are_rejected_and_allow_nothing(self) -> None:
        bad_lists = [
            "nodens",
            [{"workloadId": WORKLOAD}],
            [{"workloadId": WORKLOAD, "hostnames": []}],
            [{"workloadId": WORKLOAD, "hostnames": ["*.example.com"]}],
            [{"workloadId": WORKLOAD, "hostnames": ["Site.Example.com"]}],
            [{"workloadId": WORKLOAD, "hostnames": ["demo.invalid"]}],
            [{"workloadId": WORKLOAD, "hostnames": [HOST, HOST]}],
            [{"workloadId": WORKLOAD, "hostnames": [HOST]}, {"workloadId": WORKLOAD, "hostnames": ["b.example.com"]}],
            [{"workloadId": WORKLOAD, "hostnames": [HOST], "extra": True}],
        ]
        for bad in bad_lists:
            with self.subTest(bad=bad):
                with self.assertRaises(AllowlistError):
                    public_allowlist(exposure(allowlist=bad))
                self.assertFalse(is_allowlisted(exposure(allowlist=bad), WORKLOAD, HOST))

    def test_allowlist_matches_exact_workload_and_hostname_only(self) -> None:
        config = exposure()
        self.assertTrue(is_allowlisted(config, WORKLOAD, HOST))
        self.assertTrue(is_allowlisted(config, WORKLOAD, "www." + HOST))
        self.assertFalse(is_allowlisted(config, "other-workload", HOST))
        self.assertFalse(is_allowlisted(config, WORKLOAD, "staging." + HOST))
        self.assertFalse(is_allowlisted(config, WORKLOAD, ""))
        self.assertFalse(is_allowlisted(exposure(allowlist=[]), WORKLOAD, HOST))

    def test_provider_ready_needs_every_flag_and_no_quick_tunnels(self) -> None:
        self.assertTrue(provider_ready(exposure()))
        self.assertFalse(provider_ready(exposure(enabled=False)))
        self.assertFalse(provider_ready(exposure(quick=True)))


class IngressTests(unittest.TestCase):
    def test_parses_generated_plan_with_comments(self) -> None:
        text = "# Generated plan only.\ningress:\n  - hostname: a.example.com\n    service: http://127.0.0.1:1\n    # Access required.\n  - service: http_status:404\n"
        self.assertEqual([{"hostname": "a.example.com", "service": "http://127.0.0.1:1"}, {"service": "http_status:404"}], parse_ingress(text))

    def test_allowlisted_ingress_with_catch_all_passes(self) -> None:
        self.assertEqual([], ingress_problems(INGRESS_OK, exposure()))
        self.assertEqual([], ingress_problems(INGRESS_OK, exposure(), {HOST: WORKLOAD}))

    def test_missing_catch_all_fails(self) -> None:
        text = f"ingress:\n  - hostname: {HOST}\n    service: http://127.0.0.1:9\n"
        self.assertIn("ingress does not end in an http_status:404 catch-all", ingress_problems(text, exposure()))
        self.assertTrue(ingress_problems("tunnel: x\n", exposure()))

    def test_non_allowlisted_hostname_fails(self) -> None:
        text = INGRESS_OK.replace(HOST, "admin.example.com")
        self.assertEqual(["ingress hostname is not allowlisted: admin.example.com"], ingress_problems(text, exposure()))

    def test_hostname_allowlisted_for_another_workload_fails(self) -> None:
        problems = ingress_problems(INGRESS_OK, exposure(), {HOST: "other-workload"})
        self.assertEqual([f"ingress hostname is not allowlisted for its workload: {HOST}"], problems)

    def test_nested_or_unknown_keys_fail_closed(self) -> None:
        nested = 'ingress:\n  - hostname: evil.example.org\n    service: http://127.0.0.1:9000\n    originRequest:\n      hostname: site.example.com\n  - service: http_status:404\n'
        deeper = INGRESS_OK.replace('    service: "http://127.0.0.1:9"', '      hostname: "evil.example.org"\n    service: "http://127.0.0.1:9"')
        repeated = INGRESS_OK.replace('    service:', '    hostname: "evil.example.org"\n    service:')
        indented = 'ingress:\n  - service: http://127.0.0.1:9000\n      hostname: site.example.com\n  - service: http_status:404\n'
        for text in (nested, deeper, repeated, indented):
            with self.subTest(text=text):
                with self.assertRaises(IngressError):
                    parse_ingress(text)
                problems = ingress_problems(text, exposure())
                self.assertEqual(1, len(problems))
                self.assertIn("ingress", problems[0])
                self.assertTrue(ingress_problems(text, exposure(), {HOST: WORKLOAD, "evil.example.org": WORKLOAD}))

    def test_catch_all_rule_before_the_end_fails(self) -> None:
        text = "ingress:\n  - service: http://127.0.0.1:9\n  - service: http_status:404\n"
        self.assertIn("ingress has a rule without a hostname before the catch-all", ingress_problems(text, exposure()))


class EffectiveGateTests(unittest.TestCase):
    def test_protected_allowed_with_allowlist_provider_and_evidence(self) -> None:
        self.assertEqual([], effective_blockers(exposure(), WORKLOAD, HOST, "cloudflare-protected", [evidence("protected")]))

    def test_public_needs_protected_then_public_evidence(self) -> None:
        self.assertEqual(
            ["no recorded protected-stage activation evidence"],
            effective_blockers(exposure(), WORKLOAD, HOST, "cloudflare-public", [evidence("public")]),
        )
        self.assertEqual(
            ["no recorded public-stage activation evidence"],
            effective_blockers(exposure(), WORKLOAD, HOST, "cloudflare-public", [evidence("protected")]),
        )
        self.assertEqual([], effective_blockers(exposure(), WORKLOAD, HOST, "cloudflare-public", [evidence("protected"), evidence("public")]))

    def test_denied_branches(self) -> None:
        proof = [evidence("protected"), evidence("public")]
        self.assertIn(
            "workload and hostname are not in cloudflare.publicAllowlist",
            effective_blockers(exposure(), "other-workload", HOST, "cloudflare-public", proof),
        )
        self.assertIn(
            "workload and hostname are not in cloudflare.publicAllowlist",
            effective_blockers(exposure(), WORKLOAD, "other.example.com", "cloudflare-protected", proof),
        )
        self.assertIn(
            "Cloudflare provider is not enabled, provisioned and limited to named tunnels",
            effective_blockers(exposure(enabled=False), WORKLOAD, HOST, "cloudflare-public", proof),
        )
        self.assertEqual(["not a Cloudflare access state: tailnet"], effective_blockers(exposure(), WORKLOAD, HOST, "tailnet", proof))

    def test_stage_evidence_must_match_mode_probe_and_hostname(self) -> None:
        open_probes = {HOST: {"status": 200, "accessBlocked": False}}
        self.assertFalse(has_stage_evidence([{**evidence("protected"), "unauthenticatedProbes": open_probes}], WORKLOAD, "protected"))
        self.assertFalse(has_stage_evidence([{**evidence("public"), "unauthenticatedProbes": {HOST: {"status": 403, "accessBlocked": True}}}], WORKLOAD, "public"))
        self.assertFalse(has_stage_evidence([evidence("protected", hostname="old.example.com")], WORKLOAD, "protected", HOST))
        self.assertFalse(has_stage_evidence([{**evidence("protected"), "validation": {"ok": False}}], WORKLOAD, "protected"))

    def test_protected_evidence_needs_access_block_operator_confirmation_and_every_hostname(self) -> None:
        self.assertTrue(has_stage_evidence([evidence("protected")], WORKLOAD, "protected", HOST))
        origin_403 = {HOST: {"status": 403, "accessBlocked": False}}
        self.assertFalse(has_stage_evidence([{**evidence("protected"), "unauthenticatedProbes": origin_403}], WORKLOAD, "protected"))
        unconfirmed = {key: value for key, value in evidence("protected").items() if key != "authenticatedConfirmed"}
        self.assertFalse(has_stage_evidence([unconfirmed], WORKLOAD, "protected"))
        partial = {**evidence("protected"), "hostnames": [HOST, "www." + HOST]}
        self.assertFalse(has_stage_evidence([partial], WORKLOAD, "protected", HOST))

    def test_evidence_without_mode_or_timestamp_is_not_evidence(self) -> None:
        for key in ("mode", "recordedAt"):
            with self.subTest(key=key):
                legacy = {name: value for name, value in evidence("protected").items() if name != key}
                self.assertFalse(has_stage_evidence([legacy], WORKLOAD, "protected"))

    def test_rollback_supersedes_earlier_evidence_only(self) -> None:
        old = [evidence("protected", recorded="2026-11-01T00:00:00Z"), evidence("public", recorded="2026-11-02T00:00:00Z")]
        after_rollback = [*old, rolled_back("2026-11-03T00:00:00Z")]
        self.assertFalse(has_stage_evidence(after_rollback, WORKLOAD, "protected", HOST))
        self.assertIn("no recorded protected-stage activation evidence", effective_blockers(exposure(), WORKLOAD, HOST, "cloudflare-public", after_rollback))
        self.assertTrue(has_stage_evidence([*after_rollback, evidence("protected", recorded="2026-11-04T00:00:00Z")], WORKLOAD, "protected", HOST))
        self.assertTrue(has_stage_evidence([*old, rolled_back("2026-11-03T00:00:00Z", workload_id="other")], WORKLOAD, "protected", HOST))


class PolicyDecisionTests(unittest.TestCase):
    def decide(self, desired: str, config: dict, proof: list[dict], *, hostname: str = HOST) -> dict:
        data = {
            "privacy.json": {"workloads": {WORKLOAD: {"privacy": "personal"}}},
            "policy.json": json.loads((ROOT / "config" / "policy.json").read_text()),
            "access.json": {"states": ["none", "local", "tailnet", "cloudflare-protected", "cloudflare-public"], "workloads": {WORKLOAD: {"desired": "tailnet", "effective": "tailnet"}}},
            "routes.json": {"workloadRoutes": {WORKLOAD: {"cloudflare": {"enabled": True, "hostname": hostname}}}},
            "exposure.json": config,
        }
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "runtime" / "cloudflare-activation"
            evidence_dir.mkdir(parents=True)
            for index, payload in enumerate(proof):
                (evidence_dir / f"{index}.json").write_text(json.dumps(payload))
            with (
                patch("argus_admission.evaluate_current", return_value=ALLOWED),
                patch.object(argus_common, "load_json", side_effect=lambda name: copy.deepcopy(data[name])),
                patch.object(argus_common, "by_id", return_value={WORKLOAD: {"id": WORKLOAD, "actions": {}}}),
                patch.object(argus_common, "root", return_value=Path(directory)),
            ):
                return argus_common.policy_decision(WORKLOAD, desired)

    def test_policy_never_makes_cloudflare_effective_even_with_evidence(self) -> None:
        # Intentional change: only argus-cloudflare-activate promotes a Cloudflare state, so stale
        # evidence can never let argus-access-apply skip the probe and confirmations.
        proof = [evidence("protected"), evidence("public")]
        for desired, reason in (("cloudflare-public", "public exposure planned only in P0"), ("cloudflare-protected", "Cloudflare exposure planned only in P0")):
            with self.subTest(desired=desired):
                decision = self.decide(desired, exposure(), proof)
                self.assertEqual((True, "tailnet", True, reason), (decision["allowed"], decision["effective"], decision["plannedOnly"], decision["reason"]))
        self.assertEqual("publish publicly", self.decide("cloudflare-public", exposure(), proof)["confirmationPhrase"])

    def test_allowlisted_but_unready_routes_stay_planned_only(self) -> None:
        cases = {
            "provider disabled": (exposure(enabled=False), [evidence("protected"), evidence("public")]),
            "no evidence": (exposure(), []),
            "public without protected evidence": (exposure(), [evidence("public")]),
        }
        for desired in ("cloudflare-public", "cloudflare-protected"):
            for name, (config, proof) in cases.items():
                with self.subTest(desired=desired, case=name):
                    decision = self.decide(desired, config, proof)
                    self.assertEqual(("tailnet", True), (decision["effective"], decision["plannedOnly"]))

    def test_unlisted_routes_are_denied_for_both_cloudflare_states(self) -> None:
        proof = [evidence("protected"), evidence("public")]
        cases = {
            "empty allowlist": (exposure(allowlist=[]), HOST),
            "hostname not allowlisted": (exposure(), "other.example.com"),
            "malformed allowlist": (exposure(allowlist=[{"workloadId": WORKLOAD}]), HOST),
        }
        for desired in ("cloudflare-public", "cloudflare-protected"):
            for name, (config, hostname) in cases.items():
                with self.subTest(desired=desired, case=name):
                    decision = self.decide(desired, config, proof, hostname=hostname)
                    self.assertEqual(
                        (False, None, False, "workload and hostname are not in cloudflare.publicAllowlist"),
                        (decision["allowed"], decision["effective"], decision["plannedOnly"], decision["reason"]),
                    )


def load_script(name: str):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(ROOT / "scripts" / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def config_files(config: dict, *, desired: str, effective: str, hostname: str = HOST, mode: str = "public", requires_auth: bool = False) -> dict[str, dict]:
    return {
        "access.json": {"workloads": {WORKLOAD: {"desired": desired, "effective": effective, "urls": {}}}},
        "routes.json": {
            "api": {"bind": "127.0.0.1", "public": False},
            "workloadRoutes": {WORKLOAD: {"tailnet": {"enabled": True}, "cloudflare": {"enabled": True, "hostname": hostname, "mode": mode, "requiresAuth": requires_auth}}},
        },
        "exposure.json": config,
        "policy.json": {"rules": {"allowFunnelInP0": False}},
        "privacy.json": {"workloads": {WORKLOAD: {"privacy": "personal"}}},
        "workloads.json": {"workloads": [{"id": WORKLOAD, "kind": "website"}]},
    }


class DoctorAndReconcileTests(unittest.TestCase):
    def run_with(self, files: dict[str, dict], proof: list[dict], call):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "runtime" / "cloudflare-activation"
            evidence_dir.mkdir(parents=True)
            for index, payload in enumerate(proof):
                (evidence_dir / f"{index}.json").write_text(json.dumps(payload))
            return call(lambda name: copy.deepcopy(files[name]), Path(directory))

    def doctor(self, files: dict[str, dict], proof: list[dict]) -> dict[str, bool]:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
        globals_ = namespace["exposure_checks"].__globals__

        def call(loader, directory: Path) -> dict[str, bool]:
            checks: list[dict] = []
            with patch.dict(globals_, {"load_json": loader, "root": lambda: directory}):
                globals_["exposure_checks"](checks)
                globals_["cloudflare_ingress_checks"](checks)
            return {check["message"]: check["ok"] for check in checks}

        return self.run_with(files, proof, call)

    def reconcile(self, files: dict[str, dict], proof: list[dict]) -> list[str]:
        module = load_script("argus-access-reconcile")

        def call(loader, directory: Path) -> list[str]:
            with patch.object(module, "load_json", loader), patch.object(module, "root", lambda: directory):
                result = module.reconcile(offline=True)
            return [item["message"] for item in result["findings"] if item["level"] == "fail"]

        return self.run_with(files, proof, call)

    def test_doctor_allows_verified_allowlisted_public_route(self) -> None:
        checks = self.doctor(config_files(exposure(), desired="cloudflare-public", effective="cloudflare-public"), [evidence("protected"), evidence("public")])
        self.assertTrue(checks["cloudflare-public only for allowlisted routes"])
        self.assertTrue(checks["Cloudflare effective access is allowlisted, provider-ready and evidenced"])
        self.assertTrue(checks["Cloudflare public allowlist is well-formed"])

    def test_doctor_fails_public_for_unlisted_workload_or_hostname(self) -> None:
        for config, hostname in ((exposure(allowlist=[]), HOST), (exposure(), "other.example.com")):
            with self.subTest(hostname=hostname):
                checks = self.doctor(config_files(config, desired="cloudflare-public", effective="tailnet", hostname=hostname), [])
                self.assertFalse(checks["cloudflare-public only for allowlisted routes"])

    def test_doctor_fails_effective_public_without_provider_or_evidence(self) -> None:
        checks = self.doctor(config_files(exposure(enabled=False), desired="cloudflare-public", effective="cloudflare-public"), [evidence("protected"), evidence("public")])
        self.assertFalse(checks["Cloudflare effective access is allowlisted, provider-ready and evidenced"])
        checks = self.doctor(config_files(exposure(), desired="cloudflare-public", effective="cloudflare-public"), [evidence("public")])
        self.assertFalse(checks["Cloudflare effective access is allowlisted, provider-ready and evidenced"])

    def test_doctor_fails_planned_ingress_outside_allowlist_or_without_catch_all(self) -> None:
        files = config_files(exposure(), desired="cloudflare-protected", effective="tailnet", mode="protected", requires_auth=True)
        for text, ok in ((INGRESS_OK, True), (INGRESS_OK.replace("  - service: http_status:404\n", ""), False), (INGRESS_OK.replace(HOST, "www." + HOST), False)):
            with self.subTest(text=text):
                namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
                globals_ = namespace["cloudflare_ingress_checks"].__globals__
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory) / "cloudflare").mkdir()
                    (Path(directory) / "cloudflare" / "planned-ingress.yml").write_text(text)
                    checks: list[dict] = []
                    with patch.dict(globals_, {"load_json": lambda name: copy.deepcopy(files[name]), "root": lambda: Path(directory)}):
                        globals_["cloudflare_ingress_checks"](checks)
                result = {check["message"]: check["ok"] for check in checks}
                self.assertEqual(ok, result["planned Cloudflare ingress names only allowlisted hostnames and ends in a 404 catch-all"])

    def test_reconcile_accepts_verified_public_mode(self) -> None:
        files = config_files(exposure(), desired="cloudflare-public", effective="cloudflare-public")
        self.assertEqual([], self.reconcile(files, [evidence("protected"), evidence("public")]))

    def test_reconcile_public_mode_requires_a_200_probe_and_no_auth(self) -> None:
        files = config_files(exposure(), desired="cloudflare-public", effective="cloudflare-public")
        blocked_probe = {**evidence("public"), "unauthenticatedProbes": {HOST: {"status": 403, "accessBlocked": True}}}
        self.assertIn("effective cloudflare-public: no recorded public-stage activation evidence", self.reconcile(files, [evidence("protected"), blocked_probe]))
        files = config_files(exposure(), desired="cloudflare-public", effective="cloudflare-public", requires_auth=True)
        self.assertIn("effective cloudflare-public but route still requires auth", self.reconcile(files, [evidence("protected"), evidence("public")]))

    def test_reconcile_protected_mode_keeps_the_401_403_rule(self) -> None:
        files = config_files(exposure(), desired="cloudflare-protected", effective="cloudflare-protected", mode="protected", requires_auth=True)
        self.assertEqual([], self.reconcile(files, [evidence("protected")]))
        open_probe = {**evidence("protected"), "unauthenticatedProbes": {HOST: {"status": 200, "accessBlocked": False}}}
        self.assertIn("effective cloudflare-protected: no recorded protected-stage activation evidence", self.reconcile(files, [open_probe]))

    def test_reconcile_fails_unlisted_public_and_disabled_provider(self) -> None:
        files = config_files(exposure(allowlist=[]), desired="cloudflare-public", effective="tailnet")
        self.assertIn("cloudflare-public is allowed only for allowlisted routes", self.reconcile(files, []))
        files = config_files(exposure(enabled=False), desired="cloudflare-public", effective="cloudflare-public")
        failures = self.reconcile(files, [evidence("protected"), evidence("public")])
        self.assertIn("effective cloudflare-public: Cloudflare provider is not enabled, provisioned and limited to named tunnels", failures)


    def test_reconcile_accepts_the_protected_to_public_transition_for_allowlisted_routes(self) -> None:
        files = config_files(exposure(), desired="cloudflare-public", effective="cloudflare-protected", mode="public")
        self.assertEqual([], self.reconcile(files, [evidence("protected")]))
        unlisted = config_files(exposure(allowlist=[]), desired="cloudflare-public", effective="cloudflare-protected", mode="public")
        self.assertIn("effective cloudflare-protected but route mode is not protected", self.reconcile(unlisted, [evidence("protected")]))
        not_moving = config_files(exposure(), desired="cloudflare-protected", effective="cloudflare-protected", mode="public")
        self.assertIn("effective cloudflare-protected but route mode is not protected", self.reconcile(not_moving, [evidence("protected")]))

    def test_reconcile_flags_an_enabled_public_route_without_cloudflare_effective(self) -> None:
        files = config_files(exposure(), desired="cloudflare-public", effective="tailnet", mode="public")
        self.assertIn("Cloudflare route enabled while effective access is not Cloudflare", self.reconcile(files, []))

    def test_apply_lowering_lowers_drifted_public_state_to_local(self) -> None:
        module = load_script("argus-access-reconcile")
        files = config_files(exposure(enabled=False), desired="cloudflare-public", effective="cloudflare-public")
        saved: dict = {}
        with tempfile.TemporaryDirectory() as directory, (
            patch.object(module, "load_json", lambda name: copy.deepcopy(files[name]))
        ), patch.object(module, "root", lambda: Path(directory)), patch.object(module, "save_json", lambda name, data: saved.update({name: data})), (
            patch.object(module, "regenerate_dashboard", lambda quiet=False: None)
        ), patch.object(module, "audit", lambda *args, **kwargs: None):
            result = module.reconcile(offline=True)
            self.assertFalse(result["ok"])
            self.assertEqual({"changed": [WORKLOAD]}, module.apply_lowering(result))
        item = saved["access.json"]["workloads"][WORKLOAD]
        self.assertEqual("local", item["effective"])
        self.assertTrue(item["lastError"])


class SmokeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.smoke_module = load_script("smoke-test")

    def plan_check(self, config: dict, provider_enabled: bool) -> list[str]:
        module = self.smoke_module
        smoke = module.Smoke()
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "config").mkdir()
            (repo / "cloudflare").mkdir()
            (repo / "config" / "exposure.json").write_text(json.dumps(config))
            (repo / "cloudflare" / "planned-ingress.yml").write_text("ingress:\n  - service: http_status:404\n")
            result = SimpleNamespace(returncode=0, stdout=json.dumps({"providerEnabled": provider_enabled}))
            with patch.object(module, "run", return_value=result), redirect_stdout(io.StringIO()):
                module.check_cloudflare_plan(repo, smoke)
        return smoke.failures

    def test_provider_enabled_requires_a_non_empty_allowlist(self) -> None:
        self.assertEqual([], self.plan_check(exposure(enabled=False, allowlist=[]), False))
        self.assertEqual([], self.plan_check(exposure(), True))
        self.assertEqual(["Cloudflare provider enabled only with a non-empty public allowlist"], self.plan_check(exposure(allowlist=[]), True))

    def test_active_cloudflared_is_allowed_only_for_enabled_allowlisted_ingress(self) -> None:
        problems = self.smoke_module.cloudflared_problems
        self.assertEqual([], problems(exposure(), "tunnel: abc\n" + INGRESS_OK))
        self.assertEqual(["cloudflared is active while the Cloudflare provider is disabled"], problems(exposure(enabled=False), INGRESS_OK))
        self.assertEqual(["active cloudflared config is unreadable"], problems(exposure(), None))
        self.assertEqual(["ingress hostname is not allowlisted: other.example.com"], problems(exposure(), INGRESS_OK.replace(HOST, "other.example.com")))
        self.assertEqual(sorted({HOST, "www." + HOST}), sorted(allowlisted_hostnames(exposure())))


    def test_cloudflared_unit_must_run_the_checked_config_without_a_token(self) -> None:
        problems = self.smoke_module.cloudflared_unit_problems
        path = "/nonexistent/argus-test/cloudflared.yml"
        good = f"{{ path=/usr/bin/cloudflared ; argv[]=/usr/bin/cloudflared --no-autoupdate --config {path} tunnel run ; }}"
        self.assertEqual([], problems(exposure(), good))
        self.assertEqual([], problems(exposure(), f"argv[]=/usr/bin/cloudflared --config={path} tunnel run"))
        self.assertEqual([f"cloudflared unit does not run --config {path}"], problems(exposure(), "argv[]=/usr/bin/cloudflared --config /etc/cloudflared/config.yml tunnel run"))
        self.assertIn("cloudflared unit runs a token (remotely managed) tunnel", problems(exposure(), good.replace("tunnel run", "tunnel run --token abc")))
        self.assertEqual(2, len(problems(exposure(), "argv[]=/usr/bin/cloudflared tunnel run --token=abc")))

    def test_check_cloudflared_fails_on_a_foreign_unit_config(self) -> None:
        module = self.smoke_module
        smoke = module.Smoke()
        outputs = {"is-active": "active\n", "show": "argv[]=/usr/bin/cloudflared tunnel run --token abc"}
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "config").mkdir()
            (repo / "config" / "exposure.json").write_text(json.dumps(exposure()))
            with patch.object(module, "run", lambda args, cwd: SimpleNamespace(returncode=0, stdout=outputs[args[1]])), (
                patch.object(module.shutil, "which", return_value="/bin/systemctl")
            ), patch.object(module, "read_cloudflared_config", return_value=INGRESS_OK), redirect_stdout(io.StringIO()):
                module.check_cloudflared(repo, smoke, offline=False)
        self.assertEqual(1, len(smoke.failures))
        self.assertIn("token", smoke.failures[0])


class ActivationTests(unittest.TestCase):
    def plan(
        self,
        mode: str,
        *,
        config: dict | None = None,
        route: dict | None = None,
        proof: list[dict] | None = None,
        desired: str | None = None,
        privacy: str = "personal",
        kind: str = "website",
        public_allowed: bool = True,
        config_inside_root: bool = False,
    ) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            settings = config or exposure()
            if config_inside_root:
                settings = copy.deepcopy(settings)
                settings["providers"]["cloudflare"]["activationConfigPath"] = str(repo / "cloudflared.yml")
            data = {
                "exposure.json": settings,
                "routes.json": {"workloadRoutes": {WORKLOAD: {"cloudflare": route or {"enabled": True, "hostname": HOST, "mode": mode, "requiresAuth": mode == "protected"}}}},
                "access.json": {"workloads": {WORKLOAD: {"desired": desired or activation.MODES[mode], "urls": {"local": "http://127.0.0.1:9"}}}},
                "privacy.json": {"workloads": {WORKLOAD: {"privacy": privacy}}},
            }
            evidence_dir = repo / "runtime" / "cloudflare-activation"
            evidence_dir.mkdir(parents=True)
            for index, payload in enumerate(proof or []):
                (evidence_dir / f"{index}.json").write_text(json.dumps(payload))
            with (
                patch.object(activation, "evaluate_current", return_value=ALLOWED),
                patch.object(activation, "load_json", side_effect=lambda name: copy.deepcopy(data[name])),
                patch.object(activation, "by_id", return_value={WORKLOAD: {"id": WORKLOAD, "kind": kind}}),
                patch.object(activation, "load_manifest", return_value={"security": {"publicAllowed": public_allowed}}),
                patch.object(activation, "root", return_value=repo),
            ):
                return activation.activation_plan(WORKLOAD, mode)

    def test_protected_plan_is_ready_for_an_allowlisted_route(self) -> None:
        plan = self.plan("protected")
        self.assertEqual([], plan["blockers"])
        self.assertEqual([HOST, "www." + HOST], plan["hostnames"])

    def test_public_plan_requires_protected_stage_evidence(self) -> None:
        self.assertIn("public mode requires recorded protected-stage evidence first (D027)", self.plan("public")["blockers"])
        self.assertEqual([], self.plan("public", proof=[evidence("protected")])["blockers"])
        stale = [evidence("protected"), rolled_back("2026-11-05T00:00:00Z")]
        self.assertIn("public mode requires recorded protected-stage evidence first (D027)", self.plan("public", proof=stale)["blockers"])

    def test_plan_refuses_unlisted_workload_hostname_and_disabled_provider(self) -> None:
        self.assertIn("workload is not in cloudflare.publicAllowlist", self.plan("protected", config=exposure(allowlist=[]))["blockers"])
        other_route = {"enabled": True, "hostname": "other.example.com", "mode": "protected", "requiresAuth": True}
        self.assertIn("route hostname is not in cloudflare.publicAllowlist for this workload", self.plan("protected", route=other_route)["blockers"])
        self.assertIn("Cloudflare provider is disabled", self.plan("protected", config=exposure(enabled=False))["blockers"])
        self.assertIn("quick tunnels must remain disabled", self.plan("protected", config=exposure(quick=True))["blockers"])
        self.assertIn("desired access is not cloudflare-public", self.plan("public", proof=[evidence("protected")], desired="cloudflare-protected")["blockers"])

    def test_plan_safety_blockers(self) -> None:
        proof = [evidence("protected")]
        no_auth = {"enabled": True, "hostname": HOST, "mode": "protected", "requiresAuth": False}
        cases = {
            "blocked workload kind: database": self.plan("protected", kind="database"),
            "blocked workload kind: admin-tool": self.plan("protected", kind="admin-tool"),
            "privacy classification is not allowed for public Cloudflare activation: internal": self.plan("public", proof=proof, privacy="internal"),
            "privacy classification is not allowed for protected Cloudflare activation: sensitive": self.plan("protected", privacy="sensitive"),
            "workload manifest does not allow public exposure": self.plan("public", proof=proof, public_allowed=False),
            "protected mode requires Cloudflare Access auth on the route": self.plan("protected", route=no_auth),
            "activation config path must be outside the Git repository": self.plan("protected", config_inside_root=True),
        }
        for blocker, plan in cases.items():
            with self.subTest(blocker=blocker):
                self.assertIn(blocker, plan["blockers"])
                self.assertFalse(plan["ok"])
        self.assertEqual([], self.plan("protected", privacy="internal")["blockers"])

    def test_config_rewrite_keeps_tunnel_settings_and_other_workload_rules(self) -> None:
        existing = 'tunnel: abc\ncredentials-file: "/x/abc.json"\ningress:\n  - hostname: "other.example.com"\n    service: "http://127.0.0.1:2"\n  - hostname: "old.example.com"\n    service: "http://127.0.0.1:3"\n  - service: http_status:404\n'
        written = activation.config_with_hostnames(existing, (HOST, "old.example.com"), (HOST,), "http://127.0.0.1:9")
        self.assertTrue(written.startswith('tunnel: abc\ncredentials-file: "/x/abc.json"\ningress:\n'))
        rules = parse_ingress(written)
        self.assertEqual(["other.example.com", HOST, None], [rule.get("hostname") for rule in rules])
        self.assertEqual("http_status:404", rules[-1]["service"])
        rolled_back_text = activation.config_with_hostnames(written, (HOST,), (), "")
        self.assertEqual(["other.example.com", None], [rule.get("hostname") for rule in parse_ingress(rolled_back_text)])
        self.assertEqual('tunnel: abc\ncredentials-file: "/x/abc.json"\ningress:\n  - service: http_status:404\n', activation.catch_all_config(written))


class AccessStateTests(unittest.TestCase):
    def run_set_effective(self, *, admission=ALLOWED, decision: dict | None = None, config: dict | None = None, pending: dict | None = None) -> list[dict]:
        writes: list[dict] = []
        writer = SimpleNamespace(apply=lambda **kwargs: writes.append(kwargs) or kwargs)
        data = {"exposure.json": config or exposure(), "routes.json": {"workloadRoutes": {WORKLOAD: {"cloudflare": {"hostname": HOST}}}}}
        planned = {"allowed": True, "plannedOnly": True, "effective": "tailnet", "reason": "Cloudflare exposure planned only in P0"}
        with tempfile.TemporaryDirectory() as directory, (
            patch.object(activation, "evaluate_current", return_value=admission)
        ), patch.object(activation, "policy_decision", return_value=decision or planned), patch.object(activation, "access_writer", return_value=writer), (
            patch.object(activation, "load_json", side_effect=lambda name: copy.deepcopy(data[name]))
        ), patch.object(activation, "root", return_value=Path(directory)):
            activation.set_effective(WORKLOAD, "cloudflare-protected", "test", evidence("protected") if pending is None else pending)
        return writes

    def test_set_effective_promotes_only_with_allowlist_provider_and_evidence(self) -> None:
        writes = self.run_set_effective()
        self.assertEqual(1, len(writes))
        self.assertEqual(("cloudflare-protected", False, "cloudflare-protected"), (writes[0]["decision"]["effective"], writes[0]["decision"]["plannedOnly"], writes[0]["desired"]))

    def test_set_effective_refusals_never_write(self) -> None:
        denied = SimpleNamespace(allowed=False, decision_code="admission-denied", as_dict=lambda: {})
        cases = {
            "admission denied": {"admission": denied},
            "policy denied": {"decision": {"allowed": False, "reason": "workload and hostname are not in cloudflare.publicAllowlist"}},
            "empty allowlist": {"config": exposure(allowlist=[])},
            "provider disabled": {"config": exposure(enabled=False)},
            "no evidence": {"pending": {"ok": False}},
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                writes: list[dict] = []
                with self.assertRaises(PermissionError):
                    writes = self.run_set_effective(**kwargs)
                self.assertEqual([], writes)

    def test_lower_effective_targets_tailnet_only_when_its_route_is_enabled(self) -> None:
        for enabled, target in ((True, "tailnet"), (False, "local")):
            with self.subTest(enabled=enabled):
                writes: list[dict] = []
                writer = SimpleNamespace(apply=lambda **kwargs: writes.append(kwargs))
                routes = {"workloadRoutes": {WORKLOAD: {"tailnet": {"enabled": enabled}}}}
                with patch.object(activation, "evaluate_current", return_value=ALLOWED), patch.object(activation, "access_writer", return_value=writer), (
                    patch.object(activation, "load_json", return_value=routes)
                ):
                    activation.lower_effective(WORKLOAD, "test")
                self.assertEqual((target, target), (writes[0]["desired"], writes[0]["decision"]["effective"]))

    def test_rollback_record_supersedes_written_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(activation, "root", return_value=Path(directory)):
            (Path(directory) / "runtime" / "cloudflare-activation").mkdir(parents=True)
            (Path(directory) / "runtime" / "cloudflare-activation" / "old.json").write_text(json.dumps(evidence("protected", recorded="2026-01-01T00:00:00Z")))
            activation.write_rollback_record(WORKLOAD, (HOST,))
            self.assertFalse(has_stage_evidence(activation.load_evidence(activation.evidence_dir()), WORKLOAD, "protected", HOST))


class ProbeTests(unittest.TestCase):
    def test_only_cloudflare_access_counts_as_blocked(self) -> None:
        access_blocked = runpy.run_path(str(ROOT / "scripts" / "argus-cloudflare-activate"))["access_blocked"]
        self.assertTrue(access_blocked(302, {"Location": "https://team.cloudflareaccess.com/cdn-cgi/access/login/x"}))
        self.assertTrue(access_blocked(403, {"cf-access-domain": HOST}))
        self.assertFalse(access_blocked(302, {"Location": "https://login.example.com/"}))
        self.assertFalse(access_blocked(302, {"Location": "https://cloudflareaccess.com.evil.example/"}))
        self.assertFalse(access_blocked(403, {"Server": "cloudflare"}))
        self.assertFalse(access_blocked(401, {}))
        self.assertFalse(access_blocked(200, {"cf-access-domain": HOST}))


PROTECTED_PROBE = {"status": 302, "accessBlocked": True}
PUBLIC_PROBE = {"status": 200, "accessBlocked": False}
PREVIOUS = "tunnel: abc\ningress:\n  - service: http_status:404\n"


class ActivateScriptTests(unittest.TestCase):
    def run_main(
        self,
        argv: list[str],
        *,
        probe,
        plan_blockers: list[str] | None = None,
        mode: str = "protected",
        hostnames: tuple[str, ...] = (HOST,),
        overrides: dict | None = None,
        install_ok: list[bool] | None = None,
    ) -> tuple[int, dict, list]:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-cloudflare-activate"))
        globals_ = namespace["main"].__globals__
        installs: list[str] = []
        applied: list[tuple] = []
        calls: dict[str, list] = {"stop": [], "lower": [], "probes": [], "evidence": []}
        outcomes = list(install_ok or [])
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "cloudflared.yml"
            config_path.write_text(PREVIOUS)
            plan = {
                "ok": not plan_blockers, "blockers": plan_blockers or [], "hostname": HOST, "hostnames": list(hostnames),
                "service": "http://127.0.0.1:9", "configPath": str(config_path), "targetState": activation.MODES[mode],
            }

            def install(path: Path, text: str) -> dict:
                installs.append(text)
                ok = outcomes.pop(0) if outcomes else True
                if ok:
                    path.write_text(text)
                return {"ok": ok}

            def external_probe(url: str) -> dict:
                calls["probes"].append(url)
                return probe(url) if callable(probe) else probe

            replacements = {
                "activation_plan": lambda workload_id, mode: dict(plan),
                "evaluate_current": lambda *args, **kwargs: ALLOWED,
                "preflight_refusal": lambda *args: "",
                "load_json": lambda name: exposure(),
                "install_config": install,
                "reload_cloudflared": lambda: {"ok": True},
                "stop_cloudflared": lambda: calls["stop"].append(True) or {"ok": True},
                "external_probe": external_probe,
                "operator_confirms_authenticated": lambda hosts: True,
                "write_evidence": lambda payload: calls["evidence"].append(payload) or Path(directory) / "evidence.json",
                "set_effective": lambda *args: applied.append(args[:3]),
                "lower_effective": lambda *args: calls["lower"].append(args),
                "regenerate_dashboard": lambda quiet=False: None,
                "audit": lambda *args, **kwargs: None,
                **(overrides or {}),
            }
            with patch.dict(globals_, replacements), patch.object(sys, "argv", ["argus-cloudflare-activate", *argv]), redirect_stdout(io.StringIO()) as out:
                code = globals_["main"]()
            final = config_path.read_text()
        return code, {"output": json.loads(out.getvalue()), "installs": installs, "final": final, **calls}, applied

    ARGS = [WORKLOAD, "--mode", "protected", "--confirm-workload", WORKLOAD, "--confirm-hostname", HOST, "--confirm-phrase", activation.ACCESS_CONFIRMATION]
    PUBLIC_ARGS = [WORKLOAD, "--mode", "public", "--confirm-workload", WORKLOAD, "--confirm-hostname", HOST, "--confirm-phrase", "publish publicly"]

    def assert_refused_untouched(self, code: int, result: dict, applied: list, blocker: str) -> None:
        self.assertEqual((2, [], []), (code, result["installs"], applied))
        self.assertIn(blocker, result["output"]["blockers"])

    def test_successful_protected_activation_records_evidence_and_applies_state(self) -> None:
        code, result, applied = self.run_main(self.ARGS, probe=PROTECTED_PROBE)
        self.assertEqual(0, code)
        self.assertEqual([(WORKLOAD, "cloudflare-protected", "argus-cloudflare-activate")], applied)
        self.assertIn(HOST, result["final"])
        self.assertTrue(result["evidence"][0]["authenticatedConfirmed"])

    def test_open_probe_in_protected_mode_restores_previous_ingress(self) -> None:
        code, result, applied = self.run_main(self.ARGS, probe=PUBLIC_PROBE)
        self.assertEqual(2, code)
        self.assertEqual([], applied)
        self.assertEqual(PREVIOUS, result["final"])

    def test_every_published_hostname_is_probed(self) -> None:
        hosts = (HOST, "www." + HOST)
        half_open = lambda url: PUBLIC_PROBE if url.startswith("https://www.") else PROTECTED_PROBE  # noqa: E731
        code, result, applied = self.run_main(self.ARGS, probe=half_open, hostnames=hosts)
        self.assertEqual((2, []), (code, applied))
        self.assertEqual(sorted(f"https://{host}" for host in hosts), sorted(result["probes"]))
        self.assertEqual(PREVIOUS, result["final"])

    def test_operator_must_confirm_an_authenticated_200(self) -> None:
        code, result, applied = self.run_main(self.ARGS, probe=PROTECTED_PROBE, overrides={"operator_confirms_authenticated": lambda hosts: False})
        self.assertEqual((2, [], []), (code, applied, result["evidence"]))
        self.assertEqual(PREVIOUS, result["final"])

    def test_wrong_phrase_or_plan_blocker_refuses_before_touching_config(self) -> None:
        args = [*self.ARGS[:-1], "publish publicly"]
        code, result, applied = self.run_main(args, probe=PROTECTED_PROBE)
        self.assert_refused_untouched(code, result, applied, "protected confirmation phrase did not match")
        code, result, _ = self.run_main(self.ARGS, probe=PROTECTED_PROBE, plan_blockers=["workload is not in cloudflare.publicAllowlist"])
        self.assertEqual((2, []), (code, result["installs"]))

    def test_confirmation_admission_and_preflight_gates(self) -> None:
        denied = SimpleNamespace(allowed=False, decision_code="admission-denied", as_dict=lambda: {})
        wrong_host = [*self.ARGS[:6], "www." + HOST, *self.ARGS[7:]]
        wrong_workload = [*self.ARGS[:4], "other", *self.ARGS[5:]]
        cases = [
            (wrong_host, {}, "hostname confirmation did not match"),
            (wrong_workload, {}, "workload confirmation did not match"),
            (self.ARGS, {"evaluate_current": lambda *args, **kwargs: denied}, "admission-denied"),
            (self.ARGS, {"preflight_refusal": lambda *args: "access mutation disabled by workload policy"}, "effective state would be refused: access mutation disabled by workload policy"),
        ]
        for argv, overrides, blocker in cases:
            with self.subTest(blocker=blocker):
                code, result, applied = self.run_main(argv, probe=PROTECTED_PROBE, overrides=overrides)
                self.assert_refused_untouched(code, result, applied, blocker)

    def test_ingress_beyond_the_allowlist_or_nested_is_refused(self) -> None:
        code, result, applied = self.run_main(self.ARGS, probe=PROTECTED_PROBE, overrides={"load_json": lambda name: exposure(allowlist=[])})
        self.assertEqual((2, [], []), (code, result["installs"], applied))
        self.assertEqual("ingress would exceed the allowlist", result["output"]["reason"])

    def test_refused_state_after_a_good_probe_restores_ingress(self) -> None:
        def refuse_state(*args):
            raise PermissionError("policy refused")

        code, result, applied = self.run_main(self.ARGS, probe=PROTECTED_PROBE, overrides={"set_effective": refuse_state})
        self.assertEqual(2, code)
        self.assertIn("effective state not applied: policy refused", result["output"]["reason"])
        self.assertEqual(PREVIOUS, result["final"])
        self.assertEqual([], result["evidence"])

    def test_evidence_write_failure_lowers_state_and_restores_ingress(self) -> None:
        def no_disk(payload):
            raise OSError("disk full")

        code, result, applied = self.run_main(self.ARGS, probe=PROTECTED_PROBE, overrides={"write_evidence": no_disk})
        self.assertEqual(2, code)
        self.assertEqual(1, len(applied))
        self.assertEqual(1, len(result["lower"]))
        self.assertEqual(PREVIOUS, result["final"])

    def test_failed_restore_falls_back_to_catch_all_then_stops_cloudflared(self) -> None:
        code, result, _ = self.run_main(self.ARGS, probe=PUBLIC_PROBE, install_ok=[True, False, True])
        self.assertEqual(2, code)
        self.assertEqual("tunnel: abc\ningress:\n  - service: http_status:404\n", result["final"])
        self.assertTrue(result["output"]["cut"]["trafficCut"])
        self.assertEqual([], result["stop"])
        code, result, _ = self.run_main(self.ARGS, probe=PUBLIC_PROBE, install_ok=[True, False, False])
        self.assertEqual([True], result["stop"])
        self.assertTrue(result["output"]["cut"]["trafficCut"])
        code, result, _ = self.run_main(self.ARGS, probe=PUBLIC_PROBE, install_ok=[True, False, False], overrides={"stop_cloudflared": lambda: {"ok": False}})
        self.assertFalse(result["output"]["cut"]["trafficCut"])
        self.assertIn("ALERT: traffic not cut", result["output"]["reason"])

    def test_public_activation_needs_a_200_probe(self) -> None:
        code, result, applied = self.run_main(self.PUBLIC_ARGS, probe=PUBLIC_PROBE, mode="public")
        self.assertEqual(0, code)
        self.assertEqual([(WORKLOAD, "cloudflare-public", "argus-cloudflare-activate")], applied)
        self.assertFalse(result["evidence"][0]["authenticatedConfirmed"])
        code, result, applied = self.run_main(self.PUBLIC_ARGS, probe={"status": 403, "accessBlocked": True}, mode="public")
        self.assertEqual((2, []), (code, applied))
        self.assertEqual(PREVIOUS, result["final"])

    def test_public_activation_needs_the_policy_phrase(self) -> None:
        args = [*self.PUBLIC_ARGS[:-1], activation.ACCESS_CONFIRMATION]
        code, result, applied = self.run_main(args, probe=PUBLIC_PROBE, mode="public")
        self.assert_refused_untouched(code, result, applied, "public confirmation phrase did not match")


class RollbackScriptTests(unittest.TestCase):
    def run_main(self, argv: list[str], *, route_host: str = HOST, validation_ok: bool = True) -> tuple[int, dict]:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-cloudflare-rollback"))
        globals_ = namespace["main"].__globals__
        calls: dict[str, list] = {"installs": [], "lowered": [], "records": []}
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "cloudflared.yml"
            live = f'tunnel: abc\ningress:\n  - hostname: "{route_host}"\n    service: "http://127.0.0.1:9"\n  - hostname: "other.example.com"\n    service: "http://127.0.0.1:2"\n  - service: http_status:404\n'
            config_path.write_text(live)
            settings = exposure()
            settings["providers"]["cloudflare"]["activationConfigPath"] = str(config_path)
            files = {"exposure.json": settings, "routes.json": {"workloadRoutes": {WORKLOAD: {"cloudflare": {"hostname": route_host}}}}}

            def install(path: Path, text: str) -> dict:
                calls["installs"].append(text)
                if validation_ok:
                    path.write_text(text)
                return {"ok": validation_ok}

            replacements = {
                "load_json": lambda name: copy.deepcopy(files[name]),
                "install_config": install,
                "reload_cloudflared": lambda: {"ok": True},
                "rollback_target": lambda workload_id: "tailnet",
                "write_rollback_record": lambda workload_id, hosts: calls["records"].append(hosts) or Path(directory) / "r.json",
                "lower_effective": lambda *args: calls["lowered"].append(args),
                "regenerate_dashboard": lambda quiet=False: None,
                "audit": lambda *args, **kwargs: None,
            }
            with patch.dict(globals_, replacements), patch.object(sys, "argv", ["argus-cloudflare-rollback", *argv]), redirect_stdout(io.StringIO()) as out:
                code = globals_["main"]()
            final = config_path.read_text()
        return code, {"output": json.loads(out.getvalue()), "final": final, "live": live, **calls}

    def test_preview_changes_nothing(self) -> None:
        code, result = self.run_main([WORKLOAD])
        self.assertEqual((0, [], [], []), (code, result["installs"], result["lowered"], result["records"]))
        self.assertTrue(result["output"]["wouldSupersedeEvidence"])

    def test_apply_needs_the_workload_confirmation(self) -> None:
        code, result = self.run_main([WORKLOAD, "--apply", "--confirm-workload", "other"])
        self.assertEqual((2, [], []), (code, result["installs"], result["lowered"]))
        self.assertEqual(result["live"], result["final"])

    def test_apply_drops_route_hostname_even_if_no_longer_allowlisted(self) -> None:
        code, result = self.run_main([WORKLOAD, "--apply", "--confirm-workload", WORKLOAD, "--no-reload"], route_host="old.example.com")
        self.assertEqual(0, code)
        self.assertEqual(["other.example.com", None], [rule.get("hostname") for rule in parse_ingress(result["final"])])
        self.assertEqual([(WORKLOAD, "argus-cloudflare-rollback")], result["lowered"])
        self.assertIn("old.example.com", result["records"][0])

    def test_failed_validation_leaves_state_and_evidence_alone(self) -> None:
        code, result = self.run_main([WORKLOAD, "--apply", "--confirm-workload", WORKLOAD], validation_ok=False)
        self.assertEqual((2, [], []), (code, result["lowered"], result["records"]))
        self.assertEqual(result["live"], result["final"])


if __name__ == "__main__":
    unittest.main()
