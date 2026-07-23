from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


Run = Callable[[list[str]], subprocess.CompletedProcess[str]]


def route_contract(root: Path, workload: dict[str, Any], workload_id: str) -> tuple[dict[str, Any] | None, str]:
    routes = json.loads((root / "config" / "routes.json").read_text())
    route = routes.get("workloadRoutes", {}).get(workload_id, {}).get("tailnet", {})
    if not route.get("enabled") or route.get("mode") != "tailscale-serve":
        return None, "workload has no approved Tailscale Serve route"
    public_url = urlparse(str(route.get("url", "")))
    local_url = urlparse(str(workload.get("network", {}).get("localUrl", "")))
    if public_url.scheme != "https" or not public_url.hostname or not public_url.port:
        return None, "approved tailnet URL is incomplete"
    if local_url.scheme != "http" or local_url.hostname != "127.0.0.1" or not local_url.port:
        return None, "workload target is not loopback-only"
    return {
        "host": public_url.hostname,
        "port": public_url.port,
        "target": f"http://127.0.0.1:{local_url.port}",
    }, ""


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=10)


def _mapping(run: Run, host: str, port: int) -> tuple[str, str]:
    result = run(["tailscale", "serve", "status", "--json"])
    if result.returncode != 0:
        return "", "Tailscale Serve status unavailable"
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "", "Tailscale Serve status was invalid"
    handler = status.get("Web", {}).get(f"{host}:{port}", {}).get("Handlers", {}).get("/", {})
    return str(handler.get("Proxy", "")), ""


def apply_tailscale_access(
    root: Path, workload: dict[str, Any], workload_id: str, desired: str, *, run: Run = _run,
) -> dict[str, Any]:
    contract, reason = route_contract(root, workload, workload_id)
    if contract is None:
        if desired == "tailnet":
            raise PermissionError(reason)
        return {"changed": False, "previousTailnet": False, "summary": f"Access changed to {desired}; no tailnet route was configured."}
    host, port, target = str(contract["host"]), int(contract["port"]), str(contract["target"])
    existing, error = _mapping(run, host, port)
    if error:
        raise RuntimeError(error)
    if existing and existing != target:
        raise PermissionError("approved tailnet port is already mapped to a different target")
    if desired == "tailnet":
        if existing != target:
            result = run(["tailscale", "serve", "--bg", "--yes", f"--https={port}", target])
            if result.returncode != 0:
                raise RuntimeError("Tailscale Serve apply failed")
        observed, error = _mapping(run, host, port)
        if error or observed != target:
            raise RuntimeError("Tailscale Serve verification failed")
        return {"changed": existing != target, "previousTailnet": existing == target, "summary": "Tailnet access applied and verified."}
    if desired in {"none", "local"}:
        if existing == target:
            result = run(["tailscale", "serve", "--yes", f"--https={port}", "off"])
            if result.returncode != 0:
                raise RuntimeError("Tailscale Serve removal failed")
        observed, error = _mapping(run, host, port)
        if error or observed:
            raise RuntimeError("Tailscale Serve removal verification failed")
        return {"changed": existing == target, "previousTailnet": existing == target, "summary": f"Tailnet route removed; access is {desired}."}
    raise ValueError("unsupported Phase 1 access state")
