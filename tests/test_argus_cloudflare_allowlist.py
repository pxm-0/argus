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


def evidence(mode: str, *, workload_id: str = WORKLOAD, hostname: str = HOST) -> dict:
    probe = {"status": 403, "blocked": True} if mode == "protected" else {"status": 200, "blocked": False}
    return {"ok": True, "workloadId": workload_id, "mode": mode, "hostname": hostname, "validation": {"ok": True}, "unauthenticatedProbe": probe}


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
        self.assertFalse(has_stage_evidence([{**evidence("protected"), "unauthenticatedProbe": {"status": 200, "blocked": False}}], WORKLOAD, "protected"))
        self.assertFalse(has_stage_evidence([{**evidence("public"), "unauthenticatedProbe": {"status": 403, "blocked": True}}], WORKLOAD, "public"))
        self.assertFalse(has_stage_evidence([evidence("protected", hostname="old.example.com")], WORKLOAD, "protected", HOST))
        self.assertFalse(has_stage_evidence([{**evidence("protected"), "validation": {"ok": False}}], WORKLOAD, "protected"))


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

    def test_allowlisted_verified_route_becomes_effective(self) -> None:
        decision = self.decide("cloudflare-public", exposure(), [evidence("protected"), evidence("public")])
        self.assertEqual(("cloudflare-public", False, "publish publicly"), (decision["effective"], decision["plannedOnly"], decision["confirmationPhrase"]))
        protected = self.decide("cloudflare-protected", exposure(), [evidence("protected")])
        self.assertEqual(("cloudflare-protected", False), (protected["effective"], protected["plannedOnly"]))

    def test_unverified_or_unlisted_routes_stay_planned_only(self) -> None:
        proof = [evidence("protected"), evidence("public")]
        cases = {
            "empty allowlist": (exposure(allowlist=[]), proof, HOST),
            "hostname not allowlisted": (exposure(), proof, "other.example.com"),
            "provider disabled": (exposure(enabled=False), proof, HOST),
            "public without protected evidence": (exposure(), [evidence("public")], HOST),
        }
        for name, (config, stage_proof, hostname) in cases.items():
            with self.subTest(name):
                decision = self.decide("cloudflare-public", config, stage_proof, hostname=hostname)
                self.assertEqual(("tailnet", True, "public exposure planned only in P0"), (decision["effective"], decision["plannedOnly"], decision["reason"]))


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
        blocked_probe = {**evidence("public"), "unauthenticatedProbe": {"status": 403, "blocked": True}}
        self.assertIn("effective cloudflare-public: no recorded public-stage activation evidence", self.reconcile(files, [evidence("protected"), blocked_probe]))
        files = config_files(exposure(), desired="cloudflare-public", effective="cloudflare-public", requires_auth=True)
        self.assertIn("effective cloudflare-public but route still requires auth", self.reconcile(files, [evidence("protected"), evidence("public")]))

    def test_reconcile_protected_mode_keeps_the_401_403_rule(self) -> None:
        files = config_files(exposure(), desired="cloudflare-protected", effective="cloudflare-protected", mode="protected", requires_auth=True)
        self.assertEqual([], self.reconcile(files, [evidence("protected")]))
        open_probe = {**evidence("protected"), "unauthenticatedProbe": {"status": 200, "blocked": False}}
        self.assertIn("effective cloudflare-protected: no recorded protected-stage activation evidence", self.reconcile(files, [open_probe]))

    def test_reconcile_fails_unlisted_public_and_disabled_provider(self) -> None:
        files = config_files(exposure(allowlist=[]), desired="cloudflare-public", effective="tailnet")
        self.assertIn("cloudflare-public is allowed only for allowlisted routes", self.reconcile(files, []))
        files = config_files(exposure(enabled=False), desired="cloudflare-public", effective="cloudflare-public")
        failures = self.reconcile(files, [evidence("protected"), evidence("public")])
        self.assertIn("effective cloudflare-public: Cloudflare provider is not enabled, provisioned and limited to named tunnels", failures)


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


class ActivationTests(unittest.TestCase):
    def plan(self, mode: str, *, config: dict | None = None, route: dict | None = None, proof: list[dict] | None = None, desired: str | None = None) -> dict:
        data = {
            "exposure.json": config or exposure(),
            "routes.json": {"workloadRoutes": {WORKLOAD: {"cloudflare": route or {"enabled": True, "hostname": HOST, "mode": mode, "requiresAuth": mode == "protected"}}}},
            "access.json": {"workloads": {WORKLOAD: {"desired": desired or activation.MODES[mode], "urls": {"local": "http://127.0.0.1:9"}}}},
            "privacy.json": {"workloads": {WORKLOAD: {"privacy": "personal"}}},
        }
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "runtime" / "cloudflare-activation"
            evidence_dir.mkdir(parents=True)
            for index, payload in enumerate(proof or []):
                (evidence_dir / f"{index}.json").write_text(json.dumps(payload))
            with (
                patch.object(activation, "evaluate_current", return_value=ALLOWED),
                patch.object(activation, "load_json", side_effect=lambda name: copy.deepcopy(data[name])),
                patch.object(activation, "by_id", return_value={WORKLOAD: {"id": WORKLOAD, "kind": "website"}}),
                patch.object(activation, "load_manifest", return_value={"security": {"publicAllowed": True}}),
                patch.object(activation, "root", return_value=Path(directory)),
            ):
                return activation.activation_plan(WORKLOAD, mode)

    def test_protected_plan_is_ready_for_an_allowlisted_route(self) -> None:
        plan = self.plan("protected")
        self.assertEqual([], plan["blockers"])
        self.assertEqual([HOST, "www." + HOST], plan["hostnames"])

    def test_public_plan_requires_protected_stage_evidence(self) -> None:
        self.assertIn("public mode requires recorded protected-stage evidence first (D027)", self.plan("public")["blockers"])
        self.assertEqual([], self.plan("public", proof=[evidence("protected")])["blockers"])

    def test_plan_refuses_unlisted_workload_hostname_and_disabled_provider(self) -> None:
        self.assertIn("workload is not in cloudflare.publicAllowlist", self.plan("protected", config=exposure(allowlist=[]))["blockers"])
        other_route = {"enabled": True, "hostname": "other.example.com", "mode": "protected", "requiresAuth": True}
        self.assertIn("route hostname is not in cloudflare.publicAllowlist for this workload", self.plan("protected", route=other_route)["blockers"])
        self.assertIn("Cloudflare provider is disabled", self.plan("protected", config=exposure(enabled=False))["blockers"])
        self.assertIn("quick tunnels must remain disabled", self.plan("protected", config=exposure(quick=True))["blockers"])
        self.assertIn("desired access is not cloudflare-public", self.plan("public", proof=[evidence("protected")], desired="cloudflare-protected")["blockers"])

    def test_config_rewrite_keeps_tunnel_settings_and_other_workload_rules(self) -> None:
        existing = 'tunnel: abc\ncredentials-file: "/x/abc.json"\ningress:\n  - hostname: "other.example.com"\n    service: "http://127.0.0.1:2"\n  - hostname: "old.example.com"\n    service: "http://127.0.0.1:3"\n  - service: http_status:404\n'
        written = activation.config_with_hostnames(existing, (HOST, "old.example.com"), (HOST,), "http://127.0.0.1:9")
        self.assertTrue(written.startswith('tunnel: abc\ncredentials-file: "/x/abc.json"\ningress:\n'))
        rules = parse_ingress(written)
        self.assertEqual(["other.example.com", HOST, None], [rule.get("hostname") for rule in rules])
        self.assertEqual("http_status:404", rules[-1]["service"])
        rolled_back = activation.config_with_hostnames(written, (HOST,), (), "")
        self.assertEqual(["other.example.com", None], [rule.get("hostname") for rule in parse_ingress(rolled_back)])


class ActivateScriptTests(unittest.TestCase):
    def run_main(self, argv: list[str], *, probe: dict, plan_blockers: list[str] | None = None) -> tuple[int, dict, list]:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-cloudflare-activate"))
        globals_ = namespace["main"].__globals__
        installs: list[str] = []
        applied: list[tuple] = []
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "cloudflared.yml"
            config_path.write_text("tunnel: abc\ningress:\n  - service: http_status:404\n")
            plan = {
                "ok": not plan_blockers, "blockers": plan_blockers or [], "hostname": HOST, "hostnames": [HOST],
                "service": "http://127.0.0.1:9", "configPath": str(config_path), "targetState": "cloudflare-protected",
            }

            def install(path: Path, text: str) -> dict:
                installs.append(text)
                path.write_text(text)
                return {"ok": True}

            replacements = {
                "activation_plan": lambda workload_id, mode: dict(plan),
                "evaluate_current": lambda *args, **kwargs: ALLOWED,
                "load_json": lambda name: exposure(),
                "install_config": install,
                "reload_cloudflared": lambda: {"ok": True},
                "external_probe": lambda url: probe,
                "write_evidence": lambda payload: Path(directory) / "evidence.json",
                "set_effective": lambda *args: applied.append(args),
                "regenerate_dashboard": lambda quiet=False: None,
                "audit": lambda *args, **kwargs: None,
            }
            with patch.dict(globals_, replacements), patch.object(sys, "argv", ["argus-cloudflare-activate", *argv]), redirect_stdout(io.StringIO()) as out:
                code = globals_["main"]()
            final = config_path.read_text()
        return code, {"output": json.loads(out.getvalue()), "installs": installs, "final": final}, applied

    ARGS = [WORKLOAD, "--mode", "protected", "--confirm-workload", WORKLOAD, "--confirm-hostname", HOST, "--confirm-phrase", activation.ACCESS_CONFIRMATION]

    def test_successful_protected_activation_records_evidence_and_applies_state(self) -> None:
        code, result, applied = self.run_main(self.ARGS, probe={"status": 403, "blocked": True})
        self.assertEqual(0, code)
        self.assertEqual([(WORKLOAD, "cloudflare-protected", "argus-cloudflare-activate")], applied)
        self.assertIn(HOST, result["final"])

    def test_open_probe_in_protected_mode_restores_previous_ingress(self) -> None:
        code, result, applied = self.run_main(self.ARGS, probe={"status": 200, "blocked": False})
        self.assertEqual(2, code)
        self.assertEqual([], applied)
        self.assertEqual("tunnel: abc\ningress:\n  - service: http_status:404\n", result["final"])

    def test_wrong_phrase_or_plan_blocker_refuses_before_touching_config(self) -> None:
        args = [*self.ARGS[:-1], "publish publicly"]
        code, result, applied = self.run_main(args, probe={"status": 403, "blocked": True})
        self.assertEqual((2, [], []), (code, result["installs"], applied))
        self.assertIn("protected confirmation phrase did not match", result["output"]["blockers"])
        code, result, _ = self.run_main(self.ARGS, probe={"status": 403, "blocked": True}, plan_blockers=["workload is not in cloudflare.publicAllowlist"])
        self.assertEqual((2, []), (code, result["installs"]))


if __name__ == "__main__":
    unittest.main()
