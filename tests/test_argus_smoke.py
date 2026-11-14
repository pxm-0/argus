from __future__ import annotations

import contextlib
import io
import importlib.machinery
import importlib.util
import http.server
import json
import threading
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "smoke-test"
loader = importlib.machinery.SourceFileLoader("argus_smoke", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class LatestBackupArtifactSmokeTests(unittest.TestCase):
    def write_workload(self, root: Path, *, backup_allowed: bool) -> None:
        (root / "config").mkdir()
        (root / "config" / "workloads.json").write_text(
            json.dumps({"workloads": [{"id": "candidate"}]}),
            encoding="utf-8",
        )
        manifest = root / "workloads" / "candidate" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "operations": {"backupAllowed": backup_allowed},
                    "backup": {
                        "backupAllowed": backup_allowed,
                        "destination": str(root / "backups" / "candidate"),
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_no_active_backup_enabled_is_a_passing_no_op(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.write_workload(root, backup_allowed=False)
            smoke = module.Smoke()
            with contextlib.redirect_stdout(io.StringIO()):
                module.check_latest_backup_artifact(root, smoke, offline=False)
        self.assertEqual([], smoke.failures)

    def test_enabled_backup_still_requires_an_artifact(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.write_workload(root, backup_allowed=True)
            smoke = module.Smoke()
            with contextlib.redirect_stdout(io.StringIO()):
                module.check_latest_backup_artifact(root, smoke, offline=False)
        self.assertEqual(["candidate latest approved backup artifact exists"], smoke.failures)


class ActiveWorkloadEvidenceTests(unittest.TestCase):
    def build(self, root: Path, *, health: dict, backup: dict, route_url: str = "") -> None:
        (root / "config").mkdir()
        (root / "config" / "workloads.json").write_text(
            json.dumps({"workloads": [{"id": "w", "lifecycle": "active", "health": health}]}), encoding="utf-8"
        )
        routes = {"w": {"tailnet": {"enabled": bool(route_url), "url": route_url}}}
        (root / "config" / "routes.json").write_text(json.dumps({"workloadRoutes": routes}), encoding="utf-8")
        manifest = root / "workloads" / "w" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        self.write_compose(root, "services:\n  a:\n    image: x\n")
        manifest.write_text(json.dumps({"backup": backup, "runtime": self.runtime}), encoding="utf-8")

    runtime = {"compose": {"path": "/srv/argus/workloads/w/source/compose.yml"}}

    def write_compose(self, root: Path, text: str) -> None:
        compose = root / "workloads" / "w" / "source" / "compose.yml"
        compose.parent.mkdir(parents=True, exist_ok=True)
        compose.write_text(text, encoding="utf-8")

    def run_check(self, root: Path, offline: bool = True) -> list[str]:
        smoke = module.Smoke()
        with contextlib.redirect_stdout(io.StringIO()):
            module.check_active_workload_evidence(root, smoke, offline)
        return smoke.failures

    def test_real_repo_active_workloads_have_health_and_pass(self) -> None:
        for workload_id, item in module.workload_map(ROOT).items():
            if item.get("lifecycle") == "active" or item["id"].startswith("nodens-"):
                self.assertTrue(item["health"]["enabled"], workload_id)
                self.assertTrue(item["health"]["url"].strip(), workload_id)
        self.assertEqual([], self.run_check(ROOT))

    def test_stateless_status_is_a_valid_backup_status(self) -> None:
        self.assertIn("stateless-by-design", module.BACKUP_STATUSES)
        schema = json.loads((ROOT / "config/schemas/workload-manifest.schema.json").read_text())
        self.assertIn("stateless-by-design", schema["properties"]["backup"]["properties"]["status"]["enum"])
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate-manifests")], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout)

    def test_disabled_health_or_empty_url_fails(self) -> None:
        for health in ({"enabled": False, "url": "http://x/"}, {"enabled": True, "url": ""}):
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                root = Path(directory)
                self.build(root, health=health, backup={"status": "stateless-by-design"})
                self.assertEqual(["w active or typed-deploy workload has health probe enabled with url"], self.run_check(root))

    def test_typed_deploy_workload_is_covered_without_active_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.build(root, health={"enabled": False, "url": ""}, backup={"status": "stateless-by-design"})
            (root / "config" / "workloads.json").write_text(
                json.dumps({"workloads": [{"id": "w", "lifecycle": "discovered", "health": {"enabled": False, "url": ""}}]}),
                encoding="utf-8",
            )
            (root / "workloads" / "w" / "manifest.json").write_text(
                json.dumps({"backup": {"status": "stateless-by-design"}, "runtime": self.runtime, "operations": {"deploy": {"allowed": True}}}),
                encoding="utf-8",
            )
            self.assertEqual(["w active or typed-deploy workload has health probe enabled with url"], self.run_check(root))

    def test_missing_backup_plan_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.build(root, health={"enabled": True, "url": "http://x/"}, backup={})
            self.assertEqual(["w active or typed-deploy workload has backup plan"], self.run_check(root))

    def test_stateless_claim_with_volumes_or_bind_mounts_fails(self) -> None:
        for extra in ({"namedVolumes": ["data"]}, {"bindMounts": ["/srv/data"]}):
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                root = Path(directory)
                self.build(root, health={"enabled": True, "url": "http://x/"}, backup={"status": "stateless-by-design", **extra})
                self.assertEqual(["w stateless workload has no volumes or bind mounts"], self.run_check(root))

    def test_planned_or_disabled_backup_does_not_count_as_a_plan(self) -> None:
        for status in ("planned", "disabled", "needs-discovery", "blocked"):
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                root = Path(directory)
                self.build(root, health={"enabled": True, "url": "http://x/"}, backup={"status": status})
                manifest = root / "workloads" / "w" / "manifest.json"
                manifest.write_text(
                    json.dumps({"backup": {"status": status}, "runtime": self.runtime, "operations": {"deploy": {"allowed": True}}}),
                    encoding="utf-8",
                )
                self.assertEqual(["w active or typed-deploy workload has backup plan"], self.run_check(root))

    def test_stateless_claim_is_checked_against_the_compose_file(self) -> None:
        stateless = {"status": "stateless-by-design", "namedVolumes": [], "bindMounts": []}
        bad = (
            "services:\n  a:\n    volumes:\n      - type: bind\n        source: /srv/data\n        target: /d\n",
            "services:\n  a:\n    volumes:\n      - data:/d\nvolumes:\n  data:\n",
            "services:\n  a:\n    volumes:\n      - /var/lib/argus/other/x:/d\n",
        )
        for compose in bad:
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                root = Path(directory)
                self.build(root, health={"enabled": True, "url": "http://x/"}, backup=stateless)
                self.write_compose(root, compose)
                self.assertEqual(["w stateless workload has no volumes or bind mounts"], self.run_check(root), compose)
        ingress = "services:\n  a:\n    volumes:\n      - type: bind\n        source: /var/lib/argus/sandbox-ingress/w\n        target: /run/x\nnetworks:\n  n: {}\n"
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.build(root, health={"enabled": True, "url": "http://x/"}, backup=stateless)
            self.write_compose(root, ingress)
            self.assertEqual([], self.run_check(root))

    def test_live_health_and_route_must_return_expected_status(self) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200 if self.path == "/" else 503)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            self.build(root, health={"enabled": True, "url": base + "/", "timeoutSeconds": 2}, backup={"status": "stateless-by-design"}, route_url=base + "/")
            self.assertEqual([], self.run_check(root, offline=False))
            self.build_route_down(root, base)
            self.assertEqual(["w route returns 200"], self.run_check(root, offline=False))

    def build_route_down(self, root: Path, base: str) -> None:
        routes = {"w": {"tailnet": {"enabled": True, "url": base + "/down"}}}
        (root / "config" / "routes.json").write_text(json.dumps({"workloadRoutes": routes}), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
