from __future__ import annotations

import json
import os
import re
import socketserver
import subprocess
from pathlib import Path
from typing import Any

from argus_common import by_id, load_manifest
from argus_access_runtime import apply_tailscale_access
from argus_domain_agent import AgentService, IndeterminateOperation
from argus_ipc import receive_frame, send_frame
from argus_operations import PRIVILEGED_MUTATIONS

DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class LifecycleAgent(AgentService):
    def policy_check(self, workload_id: str, operation_type: str, parameters: dict[str, Any]) -> tuple[bool, str]:
        if operation_type not in PRIVILEGED_MUTATIONS:
            return False, "privileged broker only accepts fenced lifecycle mutations"
        return True, "capability, admission, dependency, and revision checks required"

    def domain_command(self, domain: str, workload_id: str, *arguments: str) -> list[str]:
        item = by_id()[workload_id]
        manifest = load_manifest(workload_id)
        runtime = dict(item.get("runtime", {}))
        runtime.update(manifest.get("runtime", {}))
        compose = str(runtime.get("composePath", ""))
        project = str(runtime.get("composeProject", ""))
        if not compose.startswith(f"/srv/argus/workloads/{workload_id}/") or not project:
            raise PermissionError("runtime is outside the canonical workload root")
        return ["docker", "--host", f"unix:///var/lib/argus/{domain}/docker.sock", "compose", "-f", compose, "-p", project, *arguments]

    def compose(self, domain: str, workload_id: str, *arguments: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(self.domain_command(domain, workload_id, *arguments), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise IndeterminateOperation("privileged lifecycle command timed out; reconcile without retry") from exc

    def require_private_target(self, domain: str, workload_id: str) -> None:
        result = self.compose(domain, workload_id, "config", "--format", "json", timeout=15)
        if result.returncode != 0:
            raise PermissionError("target Compose configuration is unavailable")
        config = json.loads(result.stdout)
        for service in config.get("services", {}).values():
            volumes = service.get("volumes", [])
            mounts = json.dumps(volumes)
            if not isinstance(volumes, list) or any(
                not isinstance(volume, dict) or volume.get("type") == "bind"
                for volume in volumes
            ):
                raise PermissionError("host-path or malformed target mount refused")
            ports = service.get("ports", [])
            if not isinstance(ports, list):
                raise PermissionError("target port configuration is malformed")
            if any(
                not isinstance(port, dict)
                or port.get("host_ip") not in {"127.0.0.1", "::1"}
                for port in ports
            ):
                raise PermissionError("target listeners must be loopback-only")
            if service.get("network_mode") == "host" or service.get("privileged") is True or "docker.sock" in mounts:
                raise PermissionError("public, host, privileged, or Docker-socket target refused")

    def running(self, domain: str, workload_id: str) -> bool:
        result = self.compose(domain, workload_id, "ps", "--status", "running", "--quiet", timeout=15)
        return result.returncode == 0 and bool(result.stdout.strip())

    def healthy(self, domain: str, workload_id: str) -> bool:
        result = self.compose(domain, workload_id, "ps", "--format", "json", timeout=15)
        if result.returncode != 0:
            return False
        try:
            rows = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        if isinstance(rows, dict):
            rows = [rows]
        return bool(rows) and all(
            isinstance(row, dict)
            and str(row.get("State", "")).lower() == "running"
            and str(row.get("Health", "")).lower() in {"", "healthy"}
            for row in rows
        )

    def promote_between_domains(
        self, source_domain: str, target_domain: str, workload_id: str, *,
        apply_private_route: bool = False,
    ) -> dict[str, Any]:
        if source_domain == target_domain:
            raise PermissionError("source and target trust domains must differ")
        self.require_private_target(target_domain, workload_id)
        stopped = self.compose(source_domain, workload_id, "stop")
        if stopped.returncode != 0 or self.running(source_domain, workload_id):
            raise RuntimeError("source fence could not be proven")
        started = self.compose(target_domain, workload_id, "up", "-d")
        target_ready = (
            started.returncode == 0
            and self.running(target_domain, workload_id)
            and self.healthy(target_domain, workload_id)
            and not self.running(source_domain, workload_id)
        )
        route_result: dict[str, Any] = {}
        if target_ready and apply_private_route:
            try:
                route_result = apply_tailscale_access(
                    self.root, by_id()[workload_id], workload_id, "tailnet"
                )
            except (KeyError, OSError, PermissionError, RuntimeError, ValueError):
                target_ready = False
        if target_ready:
            manifest = load_manifest(workload_id)
            return {
                "sourceTrustDomain": source_domain,
                "targetTrustDomain": target_domain,
                "composeProject": str(manifest.get("runtime", {}).get("composeProject", "")),
                "privateTailnetRoute": bool(
                    not apply_private_route or "Tailnet access" in str(route_result.get("summary", ""))
                ),
                "publicExposure": False,
            }
        self.compose(target_domain, workload_id, "down")
        restored = self.compose(source_domain, workload_id, "up", "-d")
        if (
            restored.returncode == 0
            and self.running(source_domain, workload_id)
            and self.healthy(source_domain, workload_id)
            and not self.running(target_domain, workload_id)
        ):
            raise RuntimeError("target start or health gate failed; source placement restored")
        raise IndeterminateOperation("target failed and one safe healthy placement could not be proven")

    def rollback_between_domains(
        self, source_domain: str, target_domain: str, workload_id: str
    ) -> dict[str, Any]:
        target_stop = self.compose(target_domain, workload_id, "down")
        source_start = self.compose(source_domain, workload_id, "up", "-d")
        if (
            target_stop.returncode == 0
            and source_start.returncode == 0
            and self.running(source_domain, workload_id)
            and self.healthy(source_domain, workload_id)
            and not self.running(target_domain, workload_id)
        ):
            manifest = load_manifest(workload_id)
            return {
                "sourceTrustDomain": source_domain,
                "targetTrustDomain": target_domain,
                "composeProject": str(manifest.get("runtime", {}).get("composeProject", "")),
                "publicExposure": False,
            }
        raise IndeterminateOperation("rollback could not prove exactly one healthy source placement")

    def execute_typed(self, operation_type: str, workload_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if operation_type in {"migration.cutover", "migration.rollback"}:
            field = "preflightOperationId" if operation_type == "migration.cutover" else "cutoverOperationId"
            evidence = self.ledger.get(str(parameters[field]))
            if evidence is None:
                raise PermissionError("migration evidence disappeared")
            if operation_type == "migration.cutover":
                source_domain = str(evidence["trust_domain"])
                target_domain = self.domain
                if source_domain != "legacy-rootful":
                    result = self.promote_between_domains(source_domain, target_domain, workload_id)
                    return {"summary": "Sealed-domain migration cut over after source fencing and target health.", **result}
                action, acknowledgement = "--apply", "--acknowledge-m5-workload-cutover"
            else:
                placement = evidence.get("redactedResult", {})
                source_domain = str(
                    placement.get("sourceTrustDomain", "legacy-rootful")
                )
                target_domain = str(
                    placement.get("targetTrustDomain", self.domain)
                )
                if source_domain and source_domain != "legacy-rootful":
                    result = self.rollback_between_domains(source_domain, target_domain, workload_id)
                    return {"summary": "Sealed-domain migration rollback restored the proven source.", **result}
                action, acknowledgement = "--rollback", "--acknowledge-m5-workload-cutover-rollback"
            try:
                helper = subprocess.run(
                    [str(self.root / "scripts" / "argus-m5-workload-cutover"), "--workload", workload_id, action, acknowledgement],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=600,
                )
            except subprocess.TimeoutExpired as exc:
                raise IndeterminateOperation("migration helper timed out; reconcile without retry") from exc
            if helper.returncode != 0:
                raise RuntimeError("fenced migration helper failed")
            return {
                "summary": f"{operation_type} completed through the fixed root helper.",
                "sourceTrustDomain": source_domain,
                "targetTrustDomain": target_domain,
                "publicExposure": False,
            }
        if operation_type == "production.promote":
            source = self.ledger.get(str(parameters["sourceOperationId"]))
            if source is None:
                raise PermissionError("promotion source disappeared")
            source_domain = str(source["trust_domain"])
            target_domain = str(parameters["targetTrustDomain"])
            result = self.promote_between_domains(
                source_domain, target_domain, workload_id, apply_private_route=True
            )
            return {"summary": "Private production target promoted after source fencing and health.", **result}
        if operation_type == "production.rollback":
            promotion = self.ledger.get(str(parameters["promotionOperationId"]))
            if promotion is None:
                raise PermissionError("promotion evidence disappeared")
            evidence = promotion.get("redactedResult", {})
            source_domain = str(evidence.get("sourceTrustDomain", ""))
            target_domain = str(evidence.get("targetTrustDomain", ""))
            if not source_domain or not target_domain:
                raise PermissionError("promotion placement evidence is incomplete")
            result = self.rollback_between_domains(source_domain, target_domain, workload_id)
            return {"summary": "Production promotion rolled back to the proven source placement.", **result}
        raise PermissionError("unsupported privileged lifecycle operation")


class Broker:
    def __init__(self, root: Path, runtime: Path) -> None:
        self.root, self.runtime = root, runtime

    def agent(self, domain: str) -> LifecycleAgent:
        if not DOMAIN_ID.fullmatch(domain):
            raise ValueError("invalid trust domain")
        key = Path(f"/etc/argus/domains/{domain}/issuer.pub")
        previous = Path(f"/etc/argus/domains/{domain}/issuer.previous.pub")
        keys = [key] + ([previous] if previous.is_file() else [])
        return LifecycleAgent(self.root, self.runtime, domain, keys, replay_db=Path(f"/var/lib/argus/{domain}/privileged-capabilities.sqlite3"))


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            request = receive_frame(self.request)
            if set(request) == {"method", "trustDomain"} and request["method"] == "agent.status":
                if not DOMAIN_ID.fullmatch(str(request["trustDomain"])):
                    raise ValueError("invalid trust domain")
                payload = {"ok": True, "status": "available", "trustDomain": request["trustDomain"]}
            elif set(request) == {"method", "operationId", "trustDomain"} and request["method"] == "operation.execute":
                self.server.broker.agent(str(request["trustDomain"])).accept_operation(str(request["operationId"]))  # type: ignore[attr-defined]
                payload = {"accepted": True, "ok": True}
            else:
                raise ValueError("only typed lifecycle operation IDs are accepted")
        except Exception as exc:
            payload = {"ok": False, "error": exc.__class__.__name__}
        send_frame(self.request, payload)


def main() -> int:
    root = Path(os.environ.get("ARGUS_ROOT", "/srv/argus")).resolve()
    runtime = Path(os.environ.get("ARGUS_RUNTIME", root / "runtime" / "argus" / "m5"))
    socket_path = Path(os.environ.get("ARGUS_PRIVILEGED_LIFECYCLE_SOCKET", "/run/argus/privileged-lifecycle/agent.sock"))
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(str(socket_path), Handler) as server:
        server.broker = Broker(root, runtime)  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o660)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
