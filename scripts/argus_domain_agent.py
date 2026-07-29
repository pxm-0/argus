from __future__ import annotations

import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from argus_actions import (
    backup_apply,
    logs_preview,
    migration_preflight,
    restart_apply,
    wait_for_health,
)
from argus_access_runtime import apply_tailscale_access, route_contract
from argus_canonical import canonical_policy_version, canonical_revision
from argus_capabilities import (
    Ed25519Verifier,
    ReplayStore,
    validate_envelope,
)
from argus_common import by_id, load_manifest, now, policy_decision, regenerate_dashboard
from argus_ipc import receive_frame, request as ipc_request, send_frame
from argus_m1 import access_writer
from argus_operations import (
    OperationLedger,
    canonical_json,
    digest,
    operation_result_failure,
    validate_typed_parameters,
)

DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class AgentService:
    def __init__(
        self,
        root: Path,
        runtime: Path,
        domain: str,
        public_keys: list[Path],
        *,
        issuer_socket: Path | None = None,
        replay_db: Path | None = None,
    ) -> None:
        self.root = root
        self.domain = domain
        operations_db = Path(
            os.environ.get(
                "ARGUS_OPERATIONS_DB",
                runtime / "operations.sqlite3",
            )
        )
        self.ledger = OperationLedger(
            operations_db,
            require_existing=os.environ.get("ARGUS_LEDGER_REQUIRE_EXISTING") == "1",
            migrate_schema=os.environ.get("ARGUS_LEDGER_REQUIRE_EXISTING") != "1",
        )
        self.verifier = Ed25519Verifier(public_keys)
        self.issuer_socket = issuer_socket or Path(
            os.environ.get(
                "ARGUS_ISSUER_SOCKET",
                "/run/argus/capability-issuer.sock",
            )
        )
        self.replay = ReplayStore(
            replay_db
            or Path(
                os.environ.get(
                    "ARGUS_CAPABILITY_REPLAY_DB",
                    f"/var/lib/argus/{domain}/capabilities.sqlite3",
                )
            )
        )
        self.active_operations: set[str] = set()
        self.active_lock = threading.Lock()
        if domain != "legacy-rootful":
            os.environ["DOCKER_HOST"] = f"unix:///var/lib/argus/{domain}/docker.sock"

    def policy_check(self, workload_id: str, operation_type: str, parameters: dict[str, Any]) -> tuple[bool, str]:
        item = by_id().get(workload_id)
        if item is None:
            return False, "unknown workload"
        manifest = load_manifest(workload_id)
        operations = manifest.get("operations", {})
        if operation_type == "health.refresh":
            if item.get("actions", {}).get("sandboxReconcileOnly") is True:
                return False, "health refresh disabled by workload policy"
            runtime = manifest.get("runtime", item.get("runtime", {}))
            allowed = bool(item.get("health", {}).get("enabled", False)) or (
                self.domain != "legacy-rootful" and runtime.get("type") == "docker-compose"
            )
            return allowed, "health check not configured"
        if operation_type == "logs.preview":
            return bool(operations.get("logsAllowed") or operations.get("logs", {}).get("allowed")), "logs disabled by manifest"
        if operation_type == "migration.preflight":
            preview = migration_preflight(workload_id, record_audit=False)
            allowed = bool(preview.get("allowed"))
            return allowed, (
                "migration preflight enabled by manifest"
                if allowed
                else str(preview.get("reason", "migration preflight disabled by manifest"))
            )
        if operation_type == "workload.restart":
            return bool(operations.get("restartAllowed") or operations.get("restart", {}).get("allowed")), "restart disabled by manifest"
        if operation_type == "backup.create":
            return bool(operations.get("backupAllowed") or operations.get("backup", {}).get("allowed") or manifest.get("backup", {}).get("backupAllowed")), "backup disabled by manifest"
        if operation_type == "access.apply":
            if item.get("actions", {}).get("sandboxReconcileOnly") is True:
                return False, "access mutation disabled by workload policy"
            desired = str(parameters.get("desired", ""))
            if desired not in {"none", "local", "tailnet"}:
                return False, "Phase 1 access state must be none, local, or tailnet"
            if desired == "tailnet":
                _, route_reason = route_contract(self.root, item, workload_id)
                if route_reason:
                    return False, route_reason
            decision = policy_decision(workload_id, desired)
            return bool(decision.get("allowed")), str(decision.get("reason", "access policy denied"))
        return False, "unsupported typed operation"

    def compose_command(self, workload_id: str, *arguments: str) -> list[str]:
        item = by_id()[workload_id]
        manifest = load_manifest(workload_id)
        runtime = dict(item.get("runtime", {}))
        runtime.update(manifest.get("runtime", {}))
        if runtime.get("type") != "docker-compose":
            raise ValueError("typed Compose operation requires docker-compose runtime")
        compose_path = str(runtime.get("composePath", ""))
        compose_project = str(runtime.get("composeProject", ""))
        if not compose_path.startswith(f"/srv/argus/workloads/{workload_id}/") or not compose_project:
            raise ValueError("Compose runtime is outside the canonical workload root")
        command = ["docker", "compose", "-f", compose_path, "-p", compose_project, *arguments]
        return command

    def compose_service(self, workload_id: str) -> str:
        item = by_id()[workload_id]
        manifest = load_manifest(workload_id)
        return str(manifest.get("runtime", {}).get("service") or item.get("runtime", {}).get("service") or "")

    def domain_health(self, workload_id: str) -> dict[str, Any]:
        command = self.compose_command(workload_id, "ps", "--format", "json")
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=8)
        if result.returncode != 0:
            return {"ok": False, "status": "unavailable", "detail": "typed runtime health command failed"}
        try:
            stripped = result.stdout.strip()
            decoded = json.loads(stripped) if stripped.startswith(("[", "{")) else [json.loads(line) for line in stripped.splitlines() if line]
            payload = decoded if isinstance(decoded, list) else [decoded]
        except json.JSONDecodeError:
            return {"ok": False, "status": "invalid", "detail": "typed runtime health output was invalid"}
        service = self.compose_service(workload_id)
        rows = [row for row in payload if not service or row.get("Service") == service]
        healthy = bool(rows) and all(
            str(row.get("State", "")).lower() == "running"
            and str(row.get("Health", "")).lower() in {"", "healthy"}
            for row in rows
        )
        return {
            "ok": healthy,
            "status": "healthy" if healthy else "unhealthy",
            "detail": f"{len(rows)} approved service(s) observed",
        }

    def execute_typed(self, operation_type: str, workload_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if operation_type == "health.refresh":
            item = by_id().get(workload_id)
            if not item:
                raise ValueError("unknown workload")
            if self.domain != "legacy-rootful":
                return {"summary": "Domain-local runtime health evidence refreshed.", "health": self.domain_health(workload_id)}
            return {"summary": "Health evidence refreshed.", "health": wait_for_health(item, float(parameters.get("timeoutSeconds", 5)))}
        if operation_type == "logs.preview":
            return logs_preview(workload_id, max_lines=int(parameters.get("maxLines", 100)))
        if operation_type == "migration.preflight":
            return migration_preflight(
                workload_id,
                actor=str(parameters.get("_operator", "domain-agent")),
            )
        if operation_type == "workload.restart":
            if self.domain != "legacy-rootful":
                restart_arguments = ["restart"]
                service = self.compose_service(workload_id)
                if service:
                    restart_arguments.append(service)
                result = subprocess.run(
                    self.compose_command(workload_id, *restart_arguments),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30,
                )
                if result.returncode != 0:
                    raise RuntimeError("typed restart failed")
                health = self.domain_health(workload_id)
                if not health["ok"]:
                    raise RuntimeError("post-restart domain health failed")
                return {"summary": "Restart applied and domain-local health verified.", "health": health}
            return restart_apply(workload_id, confirmation=workload_id)
        if operation_type == "backup.create":
            return backup_apply(workload_id, confirmation=workload_id)
        if operation_type == "access.apply":
            desired = str(parameters["desired"])
            decision = policy_decision(workload_id, desired)
            workload = by_id()[workload_id]
            route_result = apply_tailscale_access(self.root, workload, workload_id, desired)
            try:
                result = access_writer().apply(
                    workload_id=workload_id, desired=desired, decision=decision,
                    actor=str(parameters.get("_operator", "domain-agent")), timestamp=now(),
                )
            except Exception:
                rollback_state = "tailnet" if route_result["previousTailnet"] else "local"
                apply_tailscale_access(self.root, workload, workload_id, rollback_state)
                raise
            regenerate_dashboard()
            return {"summary": f"{route_result['summary']} Effective state is {result['effective']}."}
        raise ValueError("unsupported typed operation")

    def run_operation(self, operation_id: str) -> dict[str, Any]:
        operation = self.ledger.get(operation_id)
        if not operation:
            raise ValueError("unknown operation")
        if operation["trust_domain"] != self.domain:
            raise ValueError("wrong operation domain")
        if operation["state"] != "running":
            raise ValueError("operation is not worker-claimed")
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(5):
                if not self.ledger.heartbeat(operation_id):
                    return

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        try:
            issued = ipc_request(
                str(self.issuer_socket),
                {
                    "method": "capability.issue",
                    "operationId": operation_id,
                    "trustDomain": self.domain,
                },
            )
            if set(issued) != {"ok", "signedCapability"} or issued["ok"] is not True:
                raise ValueError("capability issuer rejected operation")
            envelope = self.verifier.verify(dict(issued["signedCapability"]))
            validate_envelope(
                envelope,
                operation,
                trust_domain=self.domain,
            )
            workload_id = str(operation["workload_id"])
            if canonical_revision(self.root, workload_id) != operation["expected_revision"]:
                raise ValueError("stale canonical revision")
            if (
                canonical_policy_version(self.root, workload_id)
                != operation["policy_version"]
            ):
                raise ValueError("stale policy version")
            preview = {
                "workloadId": operation["workload_id"],
                "trustDomain": operation["trust_domain"],
                "operationType": operation["operation_type"],
                "parameters": operation["parameters"],
                "expectedRevision": operation["expected_revision"],
                "policyVersion": operation["policy_version"],
            }
            if digest(preview) != operation["preview_digest"]:
                raise ValueError("preview digest mismatch")
            validate_typed_parameters(
                str(operation["operation_type"]),
                dict(operation["parameters"]),
            )
            allowed, reason = self.policy_check(
                workload_id,
                str(operation["operation_type"]),
                dict(operation["parameters"]),
            )
            if not allowed:
                raise PermissionError(reason)
            if not self.replay.consume(
                str(envelope["capabilityId"]),
                str(envelope["nonce"]),
                str(envelope["expiresAt"]),
            ):
                raise ValueError("replayed capability")
            execution_parameters = dict(operation["parameters"])
            execution_parameters["_operator"] = str(operation["requested_by"])
            result = self.execute_typed(
                str(operation["operation_type"]),
                workload_id,
                execution_parameters,
            )
            failure = operation_result_failure(str(operation["operation_type"]), result)
            if failure:
                error_class, summary = failure
                return self.ledger.transition(
                    operation_id, {"running"}, "failed", finished_at=int(time.time()),
                    error_class=error_class, redacted_summary=summary,
                    redacted_result_json=canonical_json(result),
                )
            return self.ledger.transition(
                operation_id, {"running"}, "succeeded", finished_at=int(time.time()),
                redacted_summary=str(result.get("summary", "Operation succeeded."))[:1000],
                redacted_result_json=canonical_json(result),
            )
        except PermissionError as exc:
            return self.ledger.transition(
                operation_id, {"running"}, "failed", finished_at=int(time.time()),
                error_class="policy-denied", redacted_summary=str(exc)[:1000],
            )
        except Exception as exc:  # noqa: BLE001
            self.ledger.transition(
                operation_id, {"running"}, "failed", finished_at=int(time.time()),
                error_class=exc.__class__.__name__, redacted_summary="Domain agent rejected or failed the operation.",
            )
            raise
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)

    def accept_operation(self, operation_id: str) -> None:
        operation = self.ledger.get(operation_id)
        if not operation:
            raise ValueError("unknown operation")
        if operation["trust_domain"] != self.domain:
            raise ValueError("wrong operation domain")
        if operation["state"] != "running":
            raise ValueError("operation is not worker-claimed")
        with self.active_lock:
            if operation_id in self.active_operations:
                raise ValueError("operation is already active")
            self.active_operations.add(operation_id)

        def execute() -> None:
            try:
                self.run_operation(operation_id)
            except Exception:
                # run_operation has already persisted a safe terminal outcome
                # whenever the ledger still permits one.
                pass
            finally:
                with self.active_lock:
                    self.active_operations.discard(operation_id)

        threading.Thread(target=execute, daemon=True).start()


class AgentRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            request = receive_frame(self.request)
            if request == {"method": "agent.status"}:
                payload = {
                    "ok": True,
                    "status": "available",
                    "trustDomain": self.server.service.domain,  # type: ignore[attr-defined]
                }
            else:
                if set(request) != {"method", "operationId"}:
                    raise ValueError("only typed operation IDs are accepted")
                if request["method"] != "operation.execute":
                    raise ValueError("unsupported agent method")
                self.server.service.accept_operation(  # type: ignore[attr-defined]
                    str(request["operationId"])
                )
                payload = {"accepted": True, "ok": True}
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": exc.__class__.__name__}
        send_frame(self.request, payload)


def main() -> int:
    root = Path(os.environ.get("ARGUS_ROOT", Path(__file__).resolve().parents[1])).resolve()
    runtime = Path(os.environ.get("ARGUS_RUNTIME", root / "runtime" / "argus" / "m5"))
    domain = os.environ.get("ARGUS_TRUST_DOMAIN", "").strip()
    public_key = Path(os.environ.get("ARGUS_ISSUER_PUBLIC_KEY", ""))
    previous_public_key_value = os.environ.get(
        "ARGUS_ISSUER_PREVIOUS_PUBLIC_KEY",
        "",
    )
    public_keys = [
        public_key,
        *(
            [Path(previous_public_key_value)]
            if previous_public_key_value
            else []
        ),
    ]
    if not DOMAIN_ID.fullmatch(domain) or not public_key.is_file():
        raise SystemExit("domain and issuer public key are required")
    socket_path = Path(
        os.environ.get(
            "ARGUS_AGENT_SOCKET",
            f"/run/argus/domains/{domain}/agent.sock",
        )
    )
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    service = AgentService(root, runtime, domain, public_keys)
    with socketserver.ThreadingUnixStreamServer(str(socket_path), AgentRequestHandler) as server:
        server.service = service  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o660)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
