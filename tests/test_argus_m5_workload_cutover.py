import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-m5-workload-cutover"
loader = importlib.machinery.SourceFileLoader(
    "argus_m5_workload_cutover", str(SCRIPT)
)
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class WorkloadCutoverTests(unittest.TestCase):
    def test_reviewed_domain_and_tailnet_mapping(self) -> None:
        self.assertEqual("personal-sandbox", module.SPECS["hastur"]["domain"])
        self.assertEqual("personal-sandbox", module.SPECS["locigraph"]["domain"])
        self.assertEqual("work-sandbox", module.SPECS["intake-os"]["domain"])
        self.assertEqual(443, module.SPECS["locigraph"]["tail_port"])
        self.assertEqual(8443, module.SPECS["kadath"]["tail_port"])
        self.assertEqual(8444, module.SPECS["nodens"]["tail_port"])
        self.assertEqual(8445, module.SPECS["hastur"]["tail_port"])
        self.assertEqual(8446, module.SPECS["intake-os"]["tail_port"])

    def test_firewall_allows_only_sandbox_bridge_forwarding(self) -> None:
        rules = module.firewall_text("personal-sandbox")
        self.assertIn('iifname "br-*" oifname "br-*" accept', rules)
        self.assertIn("chain input", rules)
        self.assertIn("chain output", rules)
        self.assertGreaterEqual(rules.count("policy drop"), 3)
        self.assertNotIn("tap0", rules)

    def test_previous_proxy_is_scoped_to_selected_port(self) -> None:
        status = {
            "Web": {
                "host.example:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8090"}}
                },
                "host.example:8448": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8088"}}
                },
            }
        }
        self.assertEqual(
            "http://127.0.0.1:8090", module.previous_proxy(status, 443)
        )
        self.assertIsNone(module.previous_proxy(status, 8445))

    def test_restoring_an_already_absent_route_is_idempotent(self) -> None:
        original_status = module.serve_status
        original_run = module.run
        calls = []
        module.serve_status = lambda: {"Web": {}}
        module.run = lambda command, **_kwargs: calls.append(command)
        try:
            module.restore_private_route(8445, None)
        finally:
            module.serve_status = original_status
            module.run = original_run
        self.assertEqual([], calls)

    def test_cutover_contract_has_no_public_exposure_commands(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("unix:/", script)
        self.assertIn('"publishedPorts": False', script)
        self.assertIn('"publicRoute": False', script)
        self.assertIn('"tailscale", "funnel", "status"', script)
        self.assertNotIn('"tailscale", "funnel", "--bg"', script)
        self.assertNotIn("cloudflared", script)
        self.assertNotIn("docker compose down -v", script)
        self.assertIn("stateful post-cutover rollback requires reviewed", script)
        self.assertIn("O_NOFOLLOW", script)
        self.assertIn("authority-committed", script)
        self.assertIn("sourceRestartPolicies", script)
        self.assertIn("require_target_absent", script)
        self.assertIn("verified_stage_compose", script)
        self.assertIn("install_persistence_unit", script)
        self.assertIn("--reconcile", script)
        self.assertIn("OnUnitInactiveSec=60s", script)
        self.assertIn("wait_target_socket", script)
        self.assertIn("rendered_firewall_rules", script)
        self.assertIn("cutover.recovered-before-acceptance", script)
        self.assertNotIn("shutil.rmtree", script)

    def test_all_stateful_writers_are_explicit(self) -> None:
        self.assertEqual(("hastur",), module.SPECS["hastur"]["writers"])
        self.assertEqual(("api", "web"), module.SPECS["kadath"]["writers"])
        self.assertEqual(
            ("backend", "caddy", "frontend", "worker"),
            module.SPECS["locigraph"]["writers"],
        )
        self.assertEqual(
            ("api", "local-proxy", "web"),
            module.SPECS["intake-os"]["writers"],
        )

    def test_cron_source_resurrection_detection_is_secret_safe_and_scoped(self) -> None:
        source = "/home/oreo/intake-os"
        crontab = """
        # docker compose up -d in /home/oreo/intake-os
        */5 * * * * cd /home/oreo/intake-os && /usr/bin/docker compose -f docker-compose.server.yml up -d
        @reboot cd /home/oreo/intake-os && docker-compose start
        */5 * * * * cd /home/oreo/other && docker compose up -d
        0 1 * * * cd /home/oreo/intake-os && docker compose ps
        """
        self.assertEqual(
            2,
            module.cron_source_resurrection_count(source, crontab),
        )

    def test_crontab_inspection_exit_one_fails_closed_unless_explicitly_empty(self) -> None:
        original_run = module.run
        with tempfile.TemporaryDirectory() as source:
            spec = {"source": source}
            try:
                module.run = lambda command, **kwargs: subprocess.CompletedProcess(
                    command,
                    1,
                    b"",
                    b"permission denied",
                )
                with self.assertRaisesRegex(
                    module.CutoverError,
                    "could not be inspected safely",
                ):
                    module.scheduled_source_resurrections(spec)

                module.run = lambda command, **kwargs: subprocess.CompletedProcess(
                    command,
                    1,
                    b"",
                    b"no crontab for operator",
                )
                self.assertEqual(0, module.scheduled_source_resurrections(spec))
            finally:
                module.run = original_run

    def test_runtime_socket_path_fits_linux_sun_path(self) -> None:
        for workload, workload_spec in module.SPECS.items():
            stage_id = f"{workload}-20260729t123700z-d13f99e7"
            socket_path = (
                module.runtime_directory(workload, workload_spec, stage_id)
                / "ingress"
                / "upstream.sock"
            )
            self.assertLess(
                len(module.os.fsencode(socket_path)),
                module.UNIX_SOCKET_PATH_LIMIT,
            )

    def test_build_and_reconcile_share_runtime_directory_derivation(self) -> None:
        script = SCRIPT.read_text()
        self.assertEqual(2, script.count("runtime_directory(") - 1)
        expected = (
            module.RUNTIME_ROOT
            / "personal-sandbox"
            / "nodens"
            / module.hashlib.sha256(b"stage-id").hexdigest()[:16]
        )
        self.assertEqual(
            expected,
            module.runtime_directory(
                "nodens", module.SPECS["nodens"], "stage-id"
            ),
        )

    def test_source_recovery_starts_existing_dependencies_before_writers(self) -> None:
        original_records = module.source_container_records
        original_run = module.run
        original_wait_dependencies = module.wait_source_containers_ready
        original_wait_source = module.wait_source_ready
        calls = []
        module.source_container_records = lambda _spec: [
            {
                "name": "project-api-1",
                "service": "api",
                "state": {"Status": "exited"},
            },
            {
                "name": "project-postgres-1",
                "service": "postgres",
                "state": {"Status": "exited"},
            },
        ]
        module.run = lambda command, **_kwargs: calls.append(command)
        module.wait_source_containers_ready = (
            lambda names: calls.append(["wait-dependencies", *names])
        )
        module.wait_source_ready = (
            lambda workload: calls.append(["wait-source", workload])
        )
        try:
            spec = {**module.SPECS["kadath"], "writers": ("api",)}
            module.source_up("kadath", spec)
        finally:
            module.source_container_records = original_records
            module.run = original_run
            module.wait_source_containers_ready = original_wait_dependencies
            module.wait_source_ready = original_wait_source
        self.assertEqual(
            [
                ["docker", "start", "project-postgres-1"],
                ["wait-dependencies", "project-postgres-1"],
                ["docker", "start", "project-api-1"],
                ["wait-source", "kadath"],
            ],
            calls,
        )

    def test_source_recovery_accepts_already_running_dependencies(self) -> None:
        original_records = module.source_container_records
        original_run = module.run
        original_wait_dependencies = module.wait_source_containers_ready
        original_wait_source = module.wait_source_ready
        calls = []
        module.source_container_records = lambda _spec: [
            {
                "name": "project-api-1",
                "service": "api",
                "state": {"Status": "exited"},
            },
            {
                "name": "project-postgres-1",
                "service": "postgres",
                "state": {"Status": "running"},
            },
        ]
        module.run = lambda command, **_kwargs: calls.append(command)
        module.wait_source_containers_ready = (
            lambda names: calls.append(["wait-dependencies", *names])
        )
        module.wait_source_ready = (
            lambda workload: calls.append(["wait-source", workload])
        )
        try:
            spec = {**module.SPECS["kadath"], "writers": ("api",)}
            module.source_up("kadath", spec)
        finally:
            module.source_container_records = original_records
            module.run = original_run
            module.wait_source_containers_ready = original_wait_dependencies
            module.wait_source_ready = original_wait_source
        self.assertEqual(
            [
                ["wait-dependencies", "project-postgres-1"],
                ["docker", "start", "project-api-1"],
                ["wait-source", "kadath"],
            ],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
