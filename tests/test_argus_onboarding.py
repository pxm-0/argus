from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
TEMP_ROOT = Path("/tmp") if Path("/tmp").is_dir() else None

from argus_admission import current_request, evaluate  # noqa: E402
from argus_admission_doctor import FINDING_CODES, report  # noqa: E402
from argus_observations import ObservationRepository, load_registry  # noqa: E402
from argus_onboarding import (  # noqa: E402
    OnboardingError,
    OnboardingManager,
    digest_bytes,
    digest_value,
    json_bytes,
)


ONBOARDING = {
    "workload_id": "reviewed-demo",
    "name": "Reviewed Demo",
    "kind": "web-app",
    "runtime": "docker-compose",
    "compose_project": "reviewed-demo",
    "realm": "personal",
    "zone": "sandbox",
    "stage": "none",
    "trust_domain": "personal-sandbox",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OnboardingManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.root = Path(self.directory.name) / "repo"
        shutil.copytree(ROOT / "config", self.root / "config")
        shutil.copytree(ROOT / "workloads", self.root / "workloads")
        (self.root / "runtime").mkdir(mode=0o770)
        (self.root / "runtime").chmod(0o770)
        self.runtime = Path(self.directory.name) / "runtime"
        self.manager = OnboardingManager(self.root, self.runtime)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def canonical_snapshot(self) -> dict[str, bytes | None]:
        paths = [
            "config/workloads.json",
            "config/privacy.json",
            "config/access.json",
            "config/routes.json",
            "config/argus/workload-classification.json",
            "workloads/reviewed-demo/manifest.json",
        ]
        return {
            relative: (self.root / relative).read_bytes() if (self.root / relative).exists() else None
            for relative in paths
        }

    def test_preview_is_exact_default_deny_and_writes_no_canonical_state(self) -> None:
        for schema_name in ("workload-onboarding-plan.schema.json", "admission-doctor.schema.json"):
            schema = json.loads((ROOT / "config" / "schemas" / schema_name).read_text())
            self.assertEqual("object", schema["type"])
            self.assertFalse(schema["additionalProperties"])
        plan_schema = json.loads((ROOT / "config/schemas/workload-onboarding-plan.schema.json").read_text())
        self.assertEqual(4, len(plan_schema["properties"]["inputs"]["allOf"]))
        self.assertEqual(6, len(plan_schema["properties"]["files"]["prefixItems"]))
        self.assertFalse(plan_schema["properties"]["files"]["items"])
        before = self.canonical_snapshot()
        plan = self.manager.preview(**ONBOARDING)
        self.assertEqual(before, self.canonical_snapshot())
        self.assertEqual(0o770, (self.root / "runtime").stat().st_mode & 0o777)
        self.assertTrue(plan["planDigest"].startswith("sha256:"))
        self.assertEqual(6, len(plan["files"]))
        self.assertEqual(
            {"access": "none", "admission": "denied", "publicExposure": False},
            plan["defaults"],
        )
        after = {item["key"]: item["after"] for item in plan["files"]}
        self.assertEqual("none", after["access"]["workloads"]["reviewed-demo"]["desired"])
        self.assertEqual("none", after["access"]["workloads"]["reviewed-demo"]["effective"])
        self.assertEqual("denied", after["classification"]["workloads"]["reviewed-demo"]["admission"])
        self.assertFalse(after["route"]["workloadRoutes"]["reviewed-demo"]["tailnet"]["enabled"])
        self.assertFalse(after["route"]["workloadRoutes"]["reviewed-demo"]["cloudflare"]["enabled"])
        self.assertTrue(all(not permission["allowed"] for permission in after["manifest"]["operations"].values()))
        self.assertTrue((self.runtime / "plans" / f"{plan['planDigest'][7:]}.json").is_file())

    def test_apply_is_atomic_backed_up_valid_and_idempotent(self) -> None:
        before = self.canonical_snapshot()
        access_metadata = (self.root / "config/access.json").stat()
        workloads_metadata = (self.root / "workloads").stat()
        plan = self.manager.preview(**ONBOARDING)
        result = self.manager.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")
        repeated = self.manager.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")
        self.assertEqual(result, repeated)
        self.assertEqual("completed", result["status"])
        self.assertEqual(64, len(result["revision"]))
        classification = json.loads((self.root / "config/argus/workload-classification.json").read_text())
        self.assertEqual("denied", classification["workloads"]["reviewed-demo"]["admission"])
        decision = evaluate(self.root, current_request(self.root, "reviewed-demo", "workload.restart"))
        self.assertFalse(decision.allowed)
        self.assertEqual("operation-not-capable", decision.decision_code)
        applied_access_metadata = (self.root / "config/access.json").stat()
        candidate_directory_metadata = (self.root / "workloads/reviewed-demo").stat()
        self.assertEqual(
            (access_metadata.st_uid, access_metadata.st_gid, access_metadata.st_mode & 0o777),
            (applied_access_metadata.st_uid, applied_access_metadata.st_gid, applied_access_metadata.st_mode & 0o777),
        )
        self.assertEqual(
            (workloads_metadata.st_uid, workloads_metadata.st_gid, workloads_metadata.st_mode & 0o777),
            (candidate_directory_metadata.st_uid, candidate_directory_metadata.st_gid, candidate_directory_metadata.st_mode & 0o777),
        )

        validation = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate-manifests"), "--root", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)
        backup = self.runtime / "backups" / plan["planDigest"][7:]
        self.assertTrue((backup / "backup-index.json").is_file())
        for key in ("workload", "privacy", "access", "route", "classification"):
            self.assertEqual(0o600, os.stat(backup / f"{key}.json").st_mode & 0o777)
        self.assertEqual(b"absent\n", (backup / "manifest.absent").read_bytes())
        for relative, value in before.items():
            if value is not None:
                key = {
                    "config/workloads.json": "workload",
                    "config/privacy.json": "privacy",
                    "config/access.json": "access",
                    "config/routes.json": "route",
                    "config/argus/workload-classification.json": "classification",
                }[relative]
                self.assertEqual(value, (backup / f"{key}.json").read_bytes())

    def test_stale_confirmation_collision_and_adoption_are_refused(self) -> None:
        plan = self.manager.preview(**ONBOARDING)
        with self.assertRaisesRegex(OnboardingError, "confirmation"):
            self.manager.apply(plan_digest=plan["planDigest"], confirm="different")
        access_path = self.root / "config/access.json"
        access_path.write_bytes(access_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(OnboardingError, "changed after preview"):
            self.manager.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")

        second = dict(ONBOARDING, workload_id="another-demo", name="Another Demo", compose_project="hello-nginx")
        with self.assertRaisesRegex(OnboardingError, "Compose project already exists"):
            self.manager.preview(**second)
        adopted = self.root / "workloads" / "existing-source"
        adopted.mkdir()
        (adopted / "compose.yml").write_text("services: {}\n")
        with self.assertRaisesRegex(OnboardingError, "refusing to adopt"):
            self.manager.preview(**dict(ONBOARDING, workload_id="existing-source", name="Existing Source", compose_project="existing-source"))
        with self.assertRaisesRegex(OnboardingError, "trust domain"):
            self.manager.preview(**dict(ONBOARDING, workload_id="bad-domain", compose_project="bad-domain", trust_domain="legacy-rootful"))
        with self.assertRaisesRegex(OnboardingError, "outside tracked"):
            OnboardingManager(self.root, self.root / "config" / "onboarding-runtime")

    def test_self_hashed_plan_cannot_change_unrelated_canonical_state(self) -> None:
        plan = self.manager.preview(**ONBOARDING)
        access = next(item for item in plan["files"] if item["key"] == "access")
        access["after"]["workloads"]["hastur"]["desired"] = "none"
        access["afterDigest"] = digest_bytes(json_bytes(access["after"]))
        unsigned = {key: value for key, value in plan.items() if key != "planDigest"}
        forged_digest = digest_value(unsigned)
        plan["planDigest"] = forged_digest
        path = self.runtime / "plans" / f"{forged_digest[7:]}.json"
        path.write_bytes(json_bytes(plan))
        with self.assertRaisesRegex(OnboardingError, "default-deny transformation"):
            self.manager.apply(plan_digest=forged_digest, confirm="reviewed-demo")

    def test_self_hashed_before_state_cannot_authorize_unrelated_changes(self) -> None:
        plan = self.manager.preview(**ONBOARDING)
        access = next(item for item in plan["files"] if item["key"] == "access")
        access["before"]["workloads"]["hastur"]["desired"] = "none"
        access["after"]["workloads"]["hastur"]["desired"] = "none"
        access["afterDigest"] = digest_bytes(json_bytes(access["after"]))
        unsigned = {key: value for key, value in plan.items() if key != "planDigest"}
        forged_digest = digest_value(unsigned)
        plan["planDigest"] = forged_digest
        (self.runtime / "plans" / f"{forged_digest[7:]}.json").write_bytes(json_bytes(plan))
        with self.assertRaisesRegex(OnboardingError, "reviewed before state"):
            self.manager.apply(plan_digest=forged_digest, confirm="reviewed-demo")

    def test_policy_change_stales_plan_without_canonical_mutation(self) -> None:
        before = self.canonical_snapshot()
        plan = self.manager.preview(**ONBOARDING)
        policy_path = self.root / "config/policy.json"
        policy = json.loads(policy_path.read_text())
        policy["version"] = policy["version"] + 1
        policy_path.write_text(json.dumps(policy, indent=2) + "\n")
        with self.assertRaisesRegex(OnboardingError, "policy dependency changed"):
            self.manager.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")
        self.assertEqual(before, self.canonical_snapshot())

    def test_handled_write_error_rolls_back_before_returning(self) -> None:
        before = self.canonical_snapshot()
        plan = self.manager.preview(**ONBOARDING)

        def fail(boundary: str) -> None:
            if boundary == "after-write:privacy":
                raise OSError("simulated write error")

        with self.assertRaisesRegex(OnboardingError, "was rolled back"):
            OnboardingManager(self.root, self.runtime, fault_hook=fail).apply(
                plan_digest=plan["planDigest"], confirm="reviewed-demo"
            )
        self.assertEqual(before, self.canonical_snapshot())
        self.assertEqual([], self.manager.recover())

    def test_runtime_override_cannot_change_the_repository_lock(self) -> None:
        alternate = Path(self.directory.name) / "alternate-runtime"
        second = OnboardingManager(self.root, alternate)
        self.assertEqual(self.manager.lock_root, second.lock_root)

    def test_symlinked_lock_ancestor_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT / "config", root / "config")
            shutil.copytree(ROOT / "workloads", root / "workloads")
            (root / "runtime").mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / "runtime" / "argus").symlink_to(outside, target_is_directory=True)
            manager = OnboardingManager(root, Path(directory) / "evidence")
            with self.assertRaisesRegex(OnboardingError, "ancestor"):
                manager.preview(**ONBOARDING)

    def test_onboarding_cli_preview_apply_and_invalid_root_are_machine_readable(self) -> None:
        command = [
            str(ROOT / "scripts/argus-workload-onboard"),
            "--root", str(self.root),
            "--runtime-root", str(self.runtime),
            "preview",
            "--id", "reviewed-demo", "--name", "Reviewed Demo", "--kind", "web-app",
            "--runtime", "docker-compose", "--compose-project", "reviewed-demo",
            "--realm", "personal", "--zone", "sandbox", "--stage", "none",
            "--trust-domain", "personal-sandbox",
        ]
        preview = subprocess.run(command, text=True, capture_output=True, check=False)
        preview_payload = json.loads(preview.stdout)
        self.assertEqual(0, preview.returncode)
        self.assertTrue(preview_payload["ok"])
        apply = subprocess.run([
            str(ROOT / "scripts/argus-workload-onboard"),
            "--root", str(self.root),
            "--runtime-root", str(self.runtime),
            "apply", "--plan-digest", preview_payload["planDigest"], "--confirm", "reviewed-demo",
        ], text=True, capture_output=True, check=False)
        self.assertEqual(0, apply.returncode, apply.stdout + apply.stderr)
        self.assertTrue(json.loads(apply.stdout)["ok"])

        invalid = subprocess.run([
            str(ROOT / "scripts/argus-workload-onboard"),
            "--root", str(self.root),
            "--runtime-root", str(self.root / "config/onboarding"),
            "preview",
            "--id", "invalid-root", "--name", "Invalid Root", "--kind", "web-app",
            "--runtime", "docker-compose", "--compose-project", "invalid-root",
            "--realm", "personal", "--zone", "sandbox", "--stage", "none",
            "--trust-domain", "personal-sandbox",
        ], text=True, capture_output=True, check=False)
        self.assertEqual(2, invalid.returncode)
        self.assertEqual("onboarding-refused", json.loads(invalid.stdout)["error"]["code"])

    def test_every_partial_file_boundary_recovers_without_mixed_state(self) -> None:
        boundaries = ["workload", "privacy", "access", "route", "classification", "manifest"]
        for key in boundaries:
            with self.subTest(boundary=key), tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
                root = Path(directory) / "repo"
                shutil.copytree(ROOT / "config", root / "config")
                shutil.copytree(ROOT / "workloads", root / "workloads")
                runtime = Path(directory) / "runtime"
                baseline_manager = OnboardingManager(root, runtime)
                baseline = {
                    relative: (root / relative).read_bytes() if (root / relative).exists() else None
                    for relative in [
                        "config/workloads.json",
                        "config/privacy.json",
                        "config/access.json",
                        "config/routes.json",
                        "config/argus/workload-classification.json",
                        "workloads/reviewed-demo/manifest.json",
                    ]
                }
                plan = baseline_manager.preview(**ONBOARDING)

                def fail(boundary: str, target: str = f"after-write:{key}") -> None:
                    if boundary == target:
                        raise RuntimeError("simulated crash")

                crashing = OnboardingManager(root, runtime, fault_hook=fail)
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    crashing.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")
                recovered = OnboardingManager(root, runtime)
                outcomes = recovered.recover()
                if key == "manifest":
                    self.assertEqual("committed", outcomes[0]["outcome"])
                else:
                    self.assertEqual("rolled-back", outcomes[0]["outcome"])
                    current = {
                        relative: (root / relative).read_bytes() if (root / relative).exists() else None
                        for relative in baseline
                    }
                    self.assertEqual(baseline, current)
                result = recovered.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")
                self.assertEqual("completed", result["status"])

    def test_prepared_validation_and_committed_crash_boundaries_recover(self) -> None:
        expected = {
            "after-prepared": "rolled-back",
            "after-validation": "committed",
            "after-committed": None,
        }
        for target, expected_outcome in expected.items():
            with self.subTest(boundary=target), tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
                root = Path(directory) / "repo"
                shutil.copytree(ROOT / "config", root / "config")
                shutil.copytree(ROOT / "workloads", root / "workloads")
                runtime = Path(directory) / "evidence"
                manager = OnboardingManager(root, runtime)
                plan = manager.preview(**ONBOARDING)

                def fail(boundary: str) -> None:
                    if boundary == target:
                        raise RuntimeError("simulated crash")

                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    OnboardingManager(root, runtime, fault_hook=fail).apply(
                        plan_digest=plan["planDigest"], confirm="reviewed-demo"
                    )
                recovered = OnboardingManager(root, runtime)
                outcomes = recovered.recover()
                if expected_outcome is None:
                    self.assertEqual([], outcomes)
                else:
                    self.assertEqual(expected_outcome, outcomes[0]["outcome"])
                self.assertEqual(
                    "completed",
                    recovered.apply(plan_digest=plan["planDigest"], confirm="reviewed-demo")["status"],
                )

    def test_divergent_interrupted_state_refuses_automatic_recovery(self) -> None:
        plan = self.manager.preview(**ONBOARDING)

        def fail(boundary: str) -> None:
            if boundary == "after-write:workload":
                raise RuntimeError("simulated crash")

        with self.assertRaises(RuntimeError):
            OnboardingManager(self.root, self.runtime, fault_hook=fail).apply(
                plan_digest=plan["planDigest"], confirm="reviewed-demo"
            )
        privacy = json.loads((self.root / "config/privacy.json").read_text())
        privacy["unexpected"] = True
        (self.root / "config/privacy.json").write_text(json.dumps(privacy) + "\n")
        with self.assertRaisesRegex(OnboardingError, "divergent"):
            self.manager.recover()
        cli = subprocess.run([
            str(ROOT / "scripts/argus-workload-onboard"),
            "--root", str(self.root),
            "--runtime-root", str(self.runtime),
            "apply", "--plan-digest", plan["planDigest"], "--confirm", "reviewed-demo",
        ], text=True, capture_output=True, check=False)
        self.assertEqual(3, cli.returncode)
        self.assertEqual("onboarding-recovery-required", json.loads(cli.stdout)["error"]["code"])
        self.assertEqual("recovery-required", json.loads(cli.stdout)["canonicalState"])


class AdmissionDoctorTests(unittest.TestCase):
    SOURCE = "oreochiserver.reference-compose"

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.root = Path(self.directory.name) / "repo"
        (self.root / "config/argus").mkdir(parents=True)
        (self.root / "workloads/demo").mkdir(parents=True)
        self.registry_path = self.root / "config/argus/observation-sources.json"
        shutil.copy(ROOT / "tests/fixtures/observation/reference-registry.json", self.registry_path)
        (self.root / "config/argus/legacy-classification.json").write_text(json.dumps({"trustDomain": "personal-sandbox"}))
        (self.root / "config/argus/workload-classification.json").write_text(json.dumps({
            "schemaVersion": 1,
            "workloads": {"demo": {
                "realm": "personal", "zone": "sandbox", "stage": "none",
                "trustDomain": "personal-sandbox", "status": "classified", "admission": "allowed",
            }},
        }))
        runtime = {
            "type": "docker-compose",
            "composePath": "/srv/argus/workloads/demo/source/compose.yml",
            "composeProject": "demo",
            "service": "web",
        }
        (self.root / "config/workloads.json").write_text(json.dumps({
            "version": 1,
            "workloads": [{
                "id": "demo",
                "runtime": runtime,
                "migration": {"targetTrustDomain": "personal-sandbox"},
            }],
        }))
        (self.root / "config/privacy.json").write_text(json.dumps({"version": 1, "workloads": {"demo": {"privacy": "internal"}}}))
        (self.root / "config/access.json").write_text(json.dumps({"version": 1, "workloads": {"demo": {"desired": "none", "effective": "none"}}}))
        (self.root / "config/routes.json").write_text(json.dumps({"version": 1, "workloadRoutes": {"demo": {}}}))
        (self.root / "config/policy.json").write_text(json.dumps({"version": 1}))
        self.manifest_path = self.root / "workloads/demo/manifest.json"
        self.manifest_path.write_text(json.dumps({
            "id": "demo", "name": "Demo", "schemaVersion": 1,
            "canonicalRoot": "/srv/argus/workloads/demo",
            "sourcePath": "/srv/argus/workloads/demo/source",
            "runtime": {"type": "docker-compose", "compose": {
                "path": "/srv/argus/workloads/demo/source/compose.yml", "project": "demo", "service": "web",
            }},
            "health": {}, "migration": {"targetTrustDomain": "personal-sandbox"},
            "operations": {}, "backup": {"backupAllowed": False, "restoreAllowed": False},
            "security": {"publicAllowed": False},
        }))
        self.database = Path(self.directory.name) / "observations.sqlite3"
        self.ingest([self.record("demo")])

    def tearDown(self) -> None:
        self.directory.cleanup()

    def record(self, project: str, native_id: str = "container-1") -> dict:
        return {
            "schemaVersion": 1,
            "resourceKind": "container",
            "nativeId": native_id,
            "observedAt": "2026-08-05T00:00:01Z",
            "attributes": {"lifecycle": "running", "name": project, "project": project},
            "provenance": {"adapter": "fixture", "adapterVersion": "1", "ordinal": 0},
        }

    def ingest(self, records: list[dict]) -> None:
        if self.database.exists():
            self.database.unlink()
        registry = load_registry(self.registry_path, self.root)
        with ObservationRepository(self.database) as repository:
            repository.sync_registry(registry, explicit_clock="2026-08-05T00:00:00Z")
            repository.ingest(
                registry,
                run_id="run-1",
                source_id=self.SOURCE,
                sequence=1,
                state="completed",
                started_at="2026-08-05T00:00:00Z",
                terminal_at="2026-08-05T00:00:01Z",
                records=records,
            )

    def run_doctor(self) -> dict:
        return report(self.root, self.database, self.registry_path, clock="2026-08-05T00:01:00Z")

    def run_legacy_doctor(self, containers: list[dict] | None = None, gaps: list[str] | None = None) -> dict:
        return report(
            self.root,
            clock="2026-08-05T00:01:00Z",
            legacy_collector=lambda: (containers or [], gaps or []),
        )

    def test_clean_report_is_read_only_and_has_no_mutation_authority(self) -> None:
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        database_before = (digest(self.database), self.database.stat().st_mtime_ns)
        value = self.run_doctor()
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        database_after = (digest(self.database), self.database.stat().st_mtime_ns)
        self.assertTrue(value["ok"])
        self.assertEqual([], value["findings"])
        self.assertEqual("none", value["mutationAuthority"])
        self.assertFalse(value["adoptionPerformed"])
        self.assertEqual([], value["actionsTaken"])
        self.assertEqual(before, after)
        self.assertEqual(database_before, database_after)

    def test_default_server_source_is_synchronous_legacy_inventory(self) -> None:
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        value = self.run_legacy_doctor()
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertTrue(value["ok"])
        self.assertEqual("complete", value["observationState"]["status"])
        self.assertEqual(1, value["observationState"]["configuredSources"])
        self.assertEqual(1, value["observationState"]["freshSources"])
        self.assertEqual(before, after)

    def test_legacy_inventory_reports_unknown_and_wrong_domain_projects(self) -> None:
        value = self.run_legacy_doctor([
            {"composeProject": "unknown-project"},
            {"composeProject": "demo"},
            {"composeProject": ""},
        ])
        codes = {item["code"] for item in value["findings"]}
        self.assertIn("unknown-runtime", codes)
        self.assertIn("classification-drift", codes)
        self.assertTrue(any(
            item["code"] == "classification-drift"
            and item.get("observedTrustDomains") == ["legacy-rootful"]
            for item in value["findings"]
        ))

    def test_legacy_inventory_gap_fails_closed(self) -> None:
        value = self.run_legacy_doctor(gaps=["docker-container-inventory-unavailable"])
        self.assertFalse(value["ok"])
        self.assertEqual("incomplete", value["observationState"]["status"])
        self.assertIn("observation-unavailable", {item["code"] for item in value["findings"]})

    def test_explicit_registry_without_database_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires an explicit database"):
            report(self.root, None, self.registry_path, clock="2026-08-05T00:01:00Z")

    def test_repository_baseline_has_no_canonical_admission_drift(self) -> None:
        missing = Path(self.directory.name) / "missing-current-repository.sqlite3"
        value = report(
            ROOT,
            missing,
            ROOT / "config/argus/observation-sources.json",
            clock="2026-08-21T00:00:00Z",
        )
        self.assertEqual([{"code": "observation-unavailable"}], value["findings"])

    def test_all_required_drift_categories_are_reported(self) -> None:
        self.ingest([self.record("unknown-project")])
        missing_unknown = {item["code"] for item in self.run_doctor()["findings"]}
        self.assertIn("unknown-runtime", missing_unknown)
        self.assertIn("missing-runtime", missing_unknown)

        manifest = json.loads(self.manifest_path.read_text())
        manifest["runtime"]["compose"]["project"] = "manifest-project"
        manifest["runtime"]["compose"]["service"] = "changed"
        manifest["id"] = "wrong-id"
        manifest["migration"]["targetTrustDomain"] = "work-sandbox"
        self.manifest_path.write_text(json.dumps(manifest))
        codes = {item["code"] for item in self.run_doctor()["findings"]}
        self.assertIn("project-name-drift", codes)
        self.assertIn("revision-drift", codes)
        self.assertIn("classification-drift", codes)
        self.assertEqual(
            {
                "unknown-runtime", "missing-runtime", "project-name-drift",
                "revision-drift", "classification-drift", "observation-unavailable",
            },
            FINDING_CODES,
        )

    def test_missing_repository_is_reported_without_creating_it(self) -> None:
        self.database.unlink()
        value = self.run_doctor()
        self.assertFalse(value["ok"])
        self.assertIn("observation-unavailable", {item["code"] for item in value["findings"]})
        self.assertFalse(self.database.exists())

    def test_registered_runtime_with_missing_manifest_is_not_reported_as_unknown(self) -> None:
        self.manifest_path.unlink()
        value = self.run_doctor()
        codes = {item["code"] for item in value["findings"]}
        self.assertIn("revision-drift", codes)
        self.assertNotIn("unknown-runtime", codes)

    def test_invalid_explicit_clock_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical UTC"):
            report(self.root, self.database, self.registry_path, clock="not-a-clock")

    def test_workload_registry_target_drift_is_reported(self) -> None:
        workloads_path = self.root / "config/workloads.json"
        workloads = json.loads(workloads_path.read_text())
        workloads["workloads"][0]["migration"] = {"targetTrustDomain": "work-sandbox"}
        workloads_path.write_text(json.dumps(workloads))
        findings = self.run_doctor()["findings"]
        self.assertTrue(any(
            item["code"] == "classification-drift" and item.get("workloadTrustDomain") == "work-sandbox"
            for item in findings
        ))

    def test_realm_binding_and_missing_manifest_target_are_classification_drift(self) -> None:
        classification_path = self.root / "config/argus/workload-classification.json"
        classification = json.loads(classification_path.read_text())
        classification["workloads"]["demo"]["realm"] = "work"
        classification_path.write_text(json.dumps(classification))
        manifest = json.loads(self.manifest_path.read_text())
        manifest["migration"].pop("targetTrustDomain")
        self.manifest_path.write_text(json.dumps(manifest))
        findings = self.run_doctor()["findings"]
        fields = {
            field
            for item in findings
            if item["code"] == "classification-drift"
            for field in item.get("fields", [])
        }
        self.assertIn("trustDomainBinding", fields)
        self.assertTrue(any(
            item["code"] == "classification-drift" and item.get("manifestTrustDomain") == ""
            for item in findings
        ))

    def test_stale_container_evidence_cannot_create_runtime_drift_findings(self) -> None:
        self.ingest([self.record("unknown-project")])
        value = report(self.root, self.database, self.registry_path, clock="2026-08-05T01:00:00Z")
        codes = {item["code"] for item in value["findings"]}
        self.assertIn("observation-unavailable", codes)
        self.assertNotIn("unknown-runtime", codes)
        self.assertNotIn("missing-runtime", codes)

    def test_clock_before_observation_fails_closed(self) -> None:
        value = report(self.root, self.database, self.registry_path, clock="2020-01-01T00:00:00Z")
        codes = {item["code"] for item in value["findings"]}
        self.assertIn("observation-unavailable", codes)
        self.assertFalse(value["ok"])
        self.assertEqual("2020-01-01T00:00:00Z", value["evaluatedAt"])

    def test_unrelated_unobserved_source_does_not_block_complete_docker_evidence(self) -> None:
        registry = json.loads(self.registry_path.read_text())
        unrelated = copy.deepcopy(registry["sources"][0])
        unrelated["sourceId"] = "oreochiserver.reference-schedules"
        unrelated["scope"] = "fixture-only schedule evidence"
        unrelated["minimization"] = {
            "resourceKinds": ["schedule"],
            "attributeAllowlist": {"schedule": ["unit", "scope"]},
        }
        registry["hostSources"].append(unrelated["sourceId"])
        registry["sources"].append(unrelated)
        self.registry_path.write_text(json.dumps(registry))
        self.ingest([self.record("demo")])
        value = self.run_doctor()
        self.assertTrue(value["ok"])
        self.assertEqual("complete", value["observationState"]["status"])
        self.assertEqual(1, value["observationState"]["configuredSources"])

    def test_coverage_and_snapshots_share_one_read_transaction(self) -> None:
        original = ObservationRepository.current_snapshot

        def assert_pinned(repository: ObservationRepository, source_id: str):
            self.assertTrue(repository.connection.in_transaction)
            return original(repository, source_id)

        with patch.object(ObservationRepository, "current_snapshot", assert_pinned):
            self.assertTrue(self.run_doctor()["ok"])

    def test_doctor_cli_exit_status_distinguishes_clean_and_drift(self) -> None:
        command = [
            str(ROOT / "scripts/argus-admission-doctor"),
            "--root", str(self.root),
            "--database", str(self.database),
            "--registry", str(self.registry_path),
            "--clock", "2026-08-05T00:01:00Z",
            "--json",
        ]
        clean = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(0, clean.returncode)
        self.assertTrue(json.loads(clean.stdout)["ok"])
        self.ingest([self.record("unknown-project")])
        drift = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(1, drift.returncode)
        self.assertFalse(json.loads(drift.stdout)["ok"])

    def test_server_smoke_requires_clean_doctor_and_offline_smoke_is_report_only(self) -> None:
        smoke = (ROOT / "scripts/smoke-test").read_text()
        self.assertIn('payload.get("ok") is True', smoke)
        self.assertIn('payload.get("findings") == []', smoke)
        self.assertIn("if offline:", smoke)


if __name__ == "__main__":
    unittest.main()
