from __future__ import annotations

import http.server
import os
import shutil
import socketserver
import threading
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_domain_agent import AgentService, probe_ingress  # noqa: E402
from argus_capabilities import Ed25519Signer, build_envelope  # noqa: E402
from argus_canonical import canonical_policy_version, canonical_revision  # noqa: E402
from argus_operations import digest  # noqa: E402


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def ingress_stub(socket_path: Path, status: int) -> _UnixHTTPServer:
    """An ingress Caddy stand-in on upstream.sock answering every request with `status`."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

        def address_string(self) -> str:
            return "ingress"

    server = _UnixHTTPServer(str(socket_path), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class DomainAgentServiceTests(unittest.TestCase):
    def service(
        self,
        directory: Path,
        *,
        repository: Path = ROOT,
    ) -> tuple[AgentService, Ed25519Signer]:
        private_key = directory / "issuer.key"
        public_key = directory / "issuer.pub"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "ED25519",
                "-out",
                str(private_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        service = AgentService(
            repository,
            directory / "runtime",
            "personal-sandbox",
            [public_key],
            issuer_socket=directory / "issuer.sock",
            replay_db=directory / "capabilities.sqlite3",
        )
        return service, Ed25519Signer(private_key)

    def run_health_result(self, result: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            service, signer = self.service(root)
            revision = canonical_revision(ROOT, "hastur")
            policy = canonical_policy_version(ROOT, "hastur")
            preview = {
                "workloadId": "hastur",
                "trustDomain": "personal-sandbox",
                "operationType": "health.refresh",
                "parameters": {},
                "expectedRevision": revision,
                "policyVersion": policy,
            }
            operation, _ = service.ledger.create(
                workload_id="hastur",
                trust_domain="personal-sandbox",
                operation_type="health.refresh",
                requested_by="operator@example.com",
                parameters={},
                preview_digest=digest(preview),
                expected_revision=revision,
                policy_version=policy,
                idempotency_key="health-result",
            )
            claimed = service.ledger.claim(str(operation["operation_id"]))
            self.assertIsNotNone(claimed)
            signed = signer.sign(build_envelope(claimed))
            with (
                patch(
                    "argus_domain_agent.ipc_request",
                    return_value={
                        "ok": True,
                        "signedCapability": signed,
                    },
                ),
                patch(
                    "argus_domain_agent.evaluate_current",
                    return_value=Mock(allowed=True, decision_code="allowed"),
                ),
                patch.object(
                    service,
                    "policy_check",
                    return_value=(True, "admission allowed"),
                ),
                patch.object(service, "execute_typed", return_value=result),
            ):
                return service.run_operation(str(operation["operation_id"]))

    def test_personal_sandbox_uses_rootless_socket_and_manifest_policy(self) -> None:
        previous = os.environ.get("DOCKER_HOST")
        try:
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                service, _signer = self.service(Path(directory))
                self.assertNotIn("DOCKER_HOST", os.environ)
                self.assertEqual(
                    service.compose_command("hastur", "ps")[:3],
                    ["docker", "--host", "unix:///var/lib/argus/personal-sandbox/docker.sock"],
                )
                self.assertEqual(
                    service.policy_check("hastur", "logs.preview", {}),
                    (False, "operation-not-capable"),
                )
                self.assertEqual(
                    service.policy_check("hastur", "workload.restart", {}),
                    (False, "operation-not-capable"),
                )
                self.assertEqual(
                    service.policy_check("hastur", "migration.preflight", {}),
                    (False, "migration status migrated is not a migration candidate"),
                )
                self.assertEqual(
                    service.policy_check("hastur", "access.apply", {"desired": "none"}),
                    (False, "operation-not-capable"),
                )
                self.assertEqual(
                    service.policy_check("hastur", "health.refresh", {}),
                    (False, "operation-not-capable"),
                )
                preflight = service.execute_typed(
                    "migration.preflight",
                    "hastur",
                    {},
                )
                self.assertFalse(preflight["allowed"])
                self.assertIn("not a migration candidate", preflight["reason"])
                with patch(
                    "argus_domain_agent.migration_preflight",
                    return_value={"allowed": True},
                ) as migration_preflight:
                    service.execute_typed(
                        "migration.preflight",
                        "hastur",
                        {"_operator": "oreo@example.test"},
                    )
                migration_preflight.assert_called_once_with(
                    "hastur",
                    actor="oreo@example.test",
                )
                command = service.compose_command("hastur", "restart", "hastur")
                self.assertEqual(command[-2:], ["restart", "hastur"])
                self.assertNotIn("/var/run/docker.sock", " ".join(command))
        finally:
            if previous is None:
                os.environ.pop("DOCKER_HOST", None)
            else:
                os.environ["DOCKER_HOST"] = previous

    def test_domain_agent_cannot_mutate_the_promotion_owned_tailnet_route(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            allowed, reason = service.policy_check("hastur", "access.apply", {"desired": "tailnet"})
            self.assertFalse(allowed)
            self.assertEqual("operation-not-capable", reason)

    def test_agent_shares_dependency_unavailable_denial(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            base = Path(directory)
            repository = base / "repository"
            shutil.copytree(ROOT / "config", repository / "config")
            shutil.copytree(ROOT / "workloads", repository / "workloads")
            (
                repository
                / "config"
                / "argus"
                / "workload-classification.json"
            ).write_text("{", encoding="utf-8")
            service, _signer = self.service(base, repository=repository)
            self.assertEqual(
                (False, "dependency-unavailable"),
                service.policy_check("hastur", "workload.restart", {}),
            )

    def test_unavailable_health_evidence_fails_operation_and_is_preserved(self) -> None:
        result = {
            "summary": "Domain-local runtime health evidence refreshed.",
            "health": {"ok": False, "status": "unavailable", "detail": "typed runtime health command failed"},
        }
        operation = self.run_health_result(result)
        self.assertEqual(operation["state"], "failed")
        self.assertEqual(operation["error_class"], "health-evidence-unavailable")
        self.assertEqual(operation["redactedResult"], result)

    def test_observed_unhealthy_workload_remains_completed_evidence(self) -> None:
        result = {
            "summary": "Domain-local runtime health evidence refreshed.",
            "health": {"ok": False, "status": "unhealthy", "detail": "1 approved service(s) observed"},
        }
        operation = self.run_health_result(result)
        self.assertEqual(operation["state"], "succeeded")
        self.assertIsNone(operation["error_class"])
        self.assertEqual(operation["redactedResult"], result)

    def test_lifecycle_waits_for_starting_healthcheck(self) -> None:
        starting = subprocess.CompletedProcess([], 0, stdout='{"Service":"nodens","State":"running","Health":"starting"}')
        healthy = subprocess.CompletedProcess([], 0, stdout='{"Service":"nodens","State":"running","Health":"healthy"}')
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            with (
                patch.object(service, "run_compose", return_value=subprocess.CompletedProcess([], 0, stdout="")),
                patch.object(service, "compose_service", return_value="nodens"),
                patch("argus_domain_agent.subprocess.run", side_effect=[starting, starting, healthy]) as ps,
                patch("argus_domain_agent.time.sleep"),
            ):
                result = service.execute_typed("workload.start", "hastur", {})
        self.assertEqual(ps.call_count, 3)
        self.assertIn("completed", result["summary"])


    def test_multi_container_compose_ps_ndjson_is_healthy(self) -> None:
        # app plus caddy ingress: `compose ps --format json` prints one object per line
        two = subprocess.CompletedProcess([], 0, stdout=(
            '{"Service":"argus-ingress","State":"running","Health":""}\n'
            '{"Service":"nodens","State":"running","Health":"healthy"}\n'
        ))
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            with (
                patch.object(service, "compose_service", return_value="nodens"),
                patch("argus_domain_agent.subprocess.run", return_value=two),
            ):
                health = service.domain_health("hastur")
        self.assertTrue(health["ok"], health)
        self.assertEqual("healthy", health["status"])

    def test_crash_looping_sidecar_fails_domain_health(self) -> None:
        # nodens-production: app healthy but the ingress sidecar restarting must not count as a successful deploy
        rows = {
            "restarting": '{"Service":"argus-ingress","State":"restarting","Health":"","ExitCode":255}',
            "exited-error": '{"Service":"argus-ingress","State":"exited","Health":"","ExitCode":1}',
        }
        app = '{"Service":"nodens","State":"running","Health":"healthy"}'
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            for label, sidecar in rows.items():
                with self.subTest(label), (
                    patch.object(service, "compose_service", return_value="nodens")
                ), patch("argus_domain_agent.subprocess.run",
                         return_value=subprocess.CompletedProcess([], 0, stdout=sidecar + "\n" + app + "\n")):
                    health = service.domain_health("hastur")
                self.assertFalse(health["ok"], (label, health))

    def test_deploy_result_carries_domain_health_and_image_id(self) -> None:
        image = "sha256:" + "c" * 64
        config = subprocess.CompletedProcess([], 0, stdout="sha256:target\n")
        up = subprocess.CompletedProcess([], 0, stdout="")
        ps = subprocess.CompletedProcess([], 0, stdout='{"ID":"' + "ab" * 6 + '","Service":"nodens","State":"running","Health":"healthy"}\n')
        inspected = subprocess.CompletedProcess([], 0, stdout=image + "\n")
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            with (
                patch.object(service, "run_compose", side_effect=[config, up]),
                patch.object(service, "compose_service", return_value="nodens"),
                patch("argus_domain_agent.subprocess.run", side_effect=[ps, ps, inspected]) as run,
            ):
                result = service.execute_typed("workload.deploy", "hastur", {"targetRevision": "sha256:target"})
        self.assertTrue(result["domain_health"]["ok"])
        self.assertEqual(image, result["imageId"])
        self.assertIn("inspect", run.call_args_list[-1].args[0])
        self.assertIn("completed", result["summary"])

    def test_typed_workloads_resolve_their_domain_ingress_socket(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            self.assertEqual(
                Path("/var/lib/argus/sandbox-ingress/nodens-staging/upstream.sock"),
                service.ingress_socket("nodens-staging"),
            )
            service.domain = "personal-managed"
            self.assertEqual(
                Path("/var/lib/argus/managed-ingress/nodens-production/upstream.sock"),
                service.ingress_socket("nodens-production"),
            )
            # Cutover workloads have no typed bridge and keep container-only health.
            self.assertIsNone(service.ingress_socket("hastur"))

    def test_probe_ingress_fails_on_502_and_missing_socket(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            for status, expected in ((200, True), (404, True), (502, False)):
                path = Path(directory) / f"{status}.sock"
                server = ingress_stub(path, status)
                try:
                    self.assertEqual(expected, probe_ingress(path), status)
                finally:
                    server.shutdown()
                    server.server_close()
            self.assertFalse(probe_ingress(Path(directory) / "absent.sock"))

    def test_deploy_with_running_containers_but_broken_ingress_fails(self) -> None:
        # Sim rehearsal: nodens and its ingress ran, but the domain firewall dropped ingress->app, so upstream.sock 502'd.
        config = subprocess.CompletedProcess([], 0, stdout="sha256:target\n")
        up = subprocess.CompletedProcess([], 0, stdout="")
        ps = subprocess.CompletedProcess([], 0, stdout=(
            '{"Service":"argus-ingress","State":"running","Health":""}\n'
            '{"Service":"nodens","State":"running","Health":"healthy"}\n'
        ))
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            socket_path = Path(directory) / "upstream.sock"
            server = ingress_stub(socket_path, 502)
            try:
                with (
                    patch.object(service, "run_compose", side_effect=[config, up]),
                    patch.object(service, "compose_service", return_value="nodens"),
                    patch.object(service, "ingress_socket", return_value=socket_path),
                    patch("argus_domain_agent.subprocess.run", return_value=ps),
                    patch("argus_domain_agent.time.sleep"),
                    patch("argus_domain_agent.time.monotonic", side_effect=[0.0, 0.0, 61.0]),
                ):
                    health = service.domain_health("nodens-staging")
                    with self.assertRaisesRegex(RuntimeError, "domain health failed"):
                        service.execute_typed("workload.deploy", "nodens-staging", {"targetRevision": "sha256:target"})
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual("degraded", health["status"])
        self.assertFalse(health["ok"])
        self.assertIn("ingress", health["detail"])

    def test_unreadable_image_id_is_empty_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            service, _signer = self.service(Path(directory))
            with patch("argus_domain_agent.subprocess.run", return_value=subprocess.CompletedProcess([], 1, stdout="")):
                self.assertEqual("", service.image_id("hastur"))


if __name__ == "__main__":
    unittest.main()
