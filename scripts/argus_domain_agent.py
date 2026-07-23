from __future__ import annotations

import json
import os
import socketserver
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from argus_actions import backup_apply, logs_preview, restart_apply, wait_for_health
from argus_access_runtime import apply_tailscale_access, route_contract
from argus_common import by_id, load_manifest, now, policy_decision, regenerate_dashboard
from argus_m1 import access_writer
from argus_operations import CapabilityCodec, DomainAgent, OperationLedger, canonical_json, capability_claims


def canonical_revision(root: Path, workload_id: str) -> str:
    import hashlib

    inputs = []
    for path in (
        root / "config" / "workloads.json",
        root / "config" / "policy.json",
        root / "config" / "access.json",
        root / "workloads" / workload_id / "manifest.json",
    ):
        if path.exists():
            inputs.append(path.read_bytes())
    return hashlib.sha256(b"\0".join(inputs)).hexdigest()


class AgentService:
    def __init__(self, root: Path, runtime: Path, domain: str, key: bytes) -> None:
        self.root = root
        self.domain = domain
        self.ledger = OperationLedger(runtime / "operations.sqlite3", recover_on_init=False)
        self.codec = CapabilityCodec(key)
        if domain != "legacy-rootful":
            os.environ["DOCKER_HOST"] = f"unix:///var/lib/argus/{domain}/docker.sock"
        self.agent = DomainAgent(
            domain, self.ledger, self.codec, self.execute_typed, self.policy_check,
            lambda workload_id: canonical_revision(root, workload_id),
        )

    def policy_check(self, workload_id: str, operation_type: str, parameters: dict[str, Any]) -> tuple[bool, str]:
        item = by_id().get(workload_id)
        if item is None:
            return False, "unknown workload"
        manifest = load_manifest(workload_id)
        operations = manifest.get("operations", {})
        if operation_type == "health.refresh":
            runtime = manifest.get("runtime", item.get("runtime", {}))
            allowed = bool(item.get("health", {}).get("enabled", False)) or (
                self.domain != "legacy-rootful" and runtime.get("type") == "docker-compose"
            )
            return allowed, "health check not configured"
        if operation_type == "logs.preview":
            return bool(operations.get("logsAllowed") or operations.get("logs", {}).get("allowed")), "logs disabled by manifest"
        if operation_type == "workload.restart":
            return bool(operations.get("restartAllowed") or operations.get("restart", {}).get("allowed")), "restart disabled by manifest"
        if operation_type == "backup.create":
            return bool(operations.get("backupAllowed") or operations.get("backup", {}).get("allowed") or manifest.get("backup", {}).get("backupAllowed")), "backup disabled by manifest"
        if operation_type == "access.apply":
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
        if operation["state"] != "queued":
            raise ValueError("operation is not queued")
        claims = capability_claims(operation)
        capability = self.codec.issue(claims)
        self.ledger.transition(operation_id, {"queued"}, "running", started_at=int(time.time()))
        try:
            request = {
                key: operation[key]
                for key in ("workload_id", "trust_domain", "operation_type", "parameters", "expected_revision", "preview_digest", "policy_version", "idempotency_key")
            }
            request["capability"] = capability
            result = self.agent.execute(request)
            return self.ledger.transition(
                operation_id, {"running"}, "succeeded", finished_at=int(time.time()),
                redacted_summary=str(result.get("summary", "Operation succeeded."))[:1000],
                redacted_result_json=canonical_json(result),
            )
        except PermissionError as exc:
            return self.ledger.transition(
                operation_id, {"running"}, "denied", finished_at=int(time.time()),
                error_class="policy-denied", redacted_summary=str(exc)[:1000],
            )
        except Exception as exc:  # noqa: BLE001
            self.ledger.transition(
                operation_id, {"running"}, "failed", finished_at=int(time.time()),
                error_class=exc.__class__.__name__, redacted_summary="Domain agent rejected or failed the operation.",
            )
            raise


class AgentRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request = json.loads(self.rfile.readline(65537))
            if set(request) != {"operationId"}:
                raise ValueError("only typed operation IDs are accepted")
            response = self.server.service.run_operation(str(request["operationId"]))  # type: ignore[attr-defined]
            payload = {"ok": True, "operation": response}
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": exc.__class__.__name__}
        self.wfile.write((json.dumps(payload, sort_keys=True) + "\n").encode())


def main() -> int:
    root = Path(os.environ.get("ARGUS_ROOT", Path(__file__).resolve().parents[1])).resolve()
    runtime = Path(os.environ.get("ARGUS_RUNTIME", root / "runtime" / "argus" / "m5"))
    domain = os.environ.get("ARGUS_TRUST_DOMAIN", "").strip()
    key_file = Path(os.environ.get("ARGUS_CAPABILITY_KEY_FILE", ""))
    if not domain or not key_file.is_file():
        raise SystemExit("domain and private capability key are required")
    key = key_file.read_bytes().strip()
    socket_path = runtime / "agents" / f"{domain}.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    service = AgentService(root, runtime, domain, key)
    with socketserver.ThreadingUnixStreamServer(str(socket_path), AgentRequestHandler) as server:
        server.service = service  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o660)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
