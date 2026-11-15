#!/usr/bin/env python3
"""Allowlisted Cloudflare named-tunnel activation (D027): plan, config, evidence and access state."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from argus_admission import evaluate_current
from argus_cloudflare_allowlist import (
    CATCH_ALL_SERVICE,
    ROLLED_BACK,
    AllowlistError,
    cloudflare_provider,
    effective_blockers,
    has_stage_evidence,
    load_evidence,
    parse_ingress,
    public_allowlist,
)
from argus_common import audit, by_id, load_json, load_manifest, now, policy_decision, print_json, root
from argus_m1 import access_writer


ACCESS_CONFIRMATION = "cloudflare access protects this hostname"
MODES = {"protected": "cloudflare-protected", "public": "cloudflare-public"}
SAFE_PRIVACY = {"protected": {"unclassified", "personal", "internal"}, "public": {"unclassified", "personal"}}
BLOCKED_KINDS = {"admin-tool", "database"}
BLOCKED_MARKERS = ("postgres", "docker.sock", "docker-socket", "/.ssh", "host-ssh", "control-api")
DEFAULT_CONFIG_PATH = "/etc/cloudflared/argus.yml"


def evidence_dir() -> Path:
    return root() / "runtime" / "cloudflare-activation"


def _privacy(workload_id: str) -> str:
    data = load_json("privacy.json")
    return str(data.get("workloads", {}).get(workload_id, {}).get("privacy", data.get("defaultPrivacy", "")))


def _route(workload_id: str) -> dict[str, Any]:
    return dict(load_json("routes.json").get("workloadRoutes", {}).get(workload_id, {}).get("cloudflare", {}))


def _access_item(workload_id: str) -> dict[str, Any]:
    return dict(load_json("access.json").get("workloads", {}).get(workload_id, {}))


def _service_url(workload: dict[str, Any], access_item: dict[str, Any], route: dict[str, Any]) -> str:
    if route.get("service"):
        return str(route["service"])
    if access_item.get("urls", {}).get("local"):
        return str(access_item["urls"]["local"])
    if workload.get("network", {}).get("localUrl"):
        return str(workload["network"]["localUrl"])
    port = workload.get("network", {}).get("internalPort")
    return f"http://127.0.0.1:{port}" if port else ""


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(root())
    except ValueError:
        return False
    return True


def confirmation_phrase(mode: str) -> str:
    if mode == "public":
        return str(load_json("policy.json").get("confirmationPhrases", {}).get("cloudflare-public", ""))
    return ACCESS_CONFIRMATION


def render_config(preamble: list[str], rules: list[dict[str, str]]) -> str:
    """Render a cloudflared config: the untouched non-ingress lines, then hostname rules and the catch-all."""
    lines = [*preamble, "ingress:"]
    for rule in rules:
        lines.append(f"  - hostname: {json.dumps(rule['hostname'])}")
        lines.extend(f"    {key}: {json.dumps(value)}" for key, value in rule.items() if key != "hostname")
    lines.append(f"  - service: {CATCH_ALL_SERVICE}")
    return "\n".join(lines) + "\n"


def split_config(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Return (non-ingress lines, hostname rules) so tunnel and credentials settings survive a rewrite."""
    preamble: list[str] = []
    in_ingress = False
    for line in text.splitlines():
        if line and not line.startswith((" ", "-", "#")):
            in_ingress = line.strip() == "ingress:"
        if not in_ingress:
            preamble.append(line)
    rules = [rule for rule in parse_ingress(text) if rule.get("hostname")]
    return preamble, rules


def config_with_hostnames(existing: str, workload_hosts: tuple[str, ...], hostnames: tuple[str, ...], service: str) -> str:
    """Replace this workload's rules with `hostnames` (none on rollback) and keep every other rule."""
    preamble, rules = split_config(existing)
    others = [rule for rule in rules if rule.get("hostname") not in workload_hosts]
    return render_config(preamble, [*others, *({"hostname": host, "service": service} for host in hostnames)])


def catch_all_config(existing: str) -> str:
    """The existing tunnel settings with every hostname rule dropped: serves nothing but 404."""
    return render_config(split_config(existing)[0], [])


def activation_plan(workload_id: str, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unknown activation mode: {mode}")
    admission = evaluate_current(root(), workload_id, "access.cloudflare-protected.plan")
    exposure = load_json("exposure.json")
    provider = cloudflare_provider(exposure)
    workload = by_id().get(workload_id)
    route = _route(workload_id)
    access_item = _access_item(workload_id)
    privacy = _privacy(workload_id)
    hostname = str(route.get("hostname", ""))
    service = _service_url(workload or {}, access_item, route)
    config_path = Path(str(provider.get("activationConfigPath") or DEFAULT_CONFIG_PATH))
    blockers: list[str] = []
    warnings: list[str] = []
    workload_hosts: tuple[str, ...] = ()

    if not admission.allowed:
        blockers.append(admission.decision_code)
    try:
        workload_hosts = public_allowlist(exposure).get(workload_id, ())
    except AllowlistError as exc:
        blockers.append(f"Cloudflare public allowlist is malformed: {exc}")
    if not workload_hosts:
        blockers.append("workload is not in cloudflare.publicAllowlist")
    elif hostname not in workload_hosts:
        blockers.append("route hostname is not in cloudflare.publicAllowlist for this workload")
    if workload is None:
        blockers.append("unknown workload")
    else:
        haystack = json.dumps(workload, sort_keys=True).lower()
        if workload.get("kind") in BLOCKED_KINDS:
            blockers.append(f"blocked workload kind: {workload.get('kind')}")
        marker = next((item for item in BLOCKED_MARKERS if item in haystack), "")
        if marker:
            blockers.append(f"blocked target marker detected: {marker}")
    if privacy not in SAFE_PRIVACY[mode]:
        blockers.append(f"privacy classification is not allowed for {mode} Cloudflare activation: {privacy}")
    if access_item.get("desired") != MODES[mode]:
        blockers.append(f"desired access is not {MODES[mode]}")
    if not hostname or hostname.endswith(".invalid"):
        blockers.append("route needs a real Cloudflare hostname")
    if route.get("enabled") is not True:
        blockers.append("Cloudflare route is disabled")
    if route.get("mode") != mode:
        blockers.append(f"route mode is not {mode}: {route.get('mode')}")
    if mode == "protected" and route.get("requiresAuth") is not True:
        blockers.append("protected mode requires Cloudflare Access auth on the route")
    if mode == "public":
        if route.get("requiresAuth") is not False:
            blockers.append("public mode requires route requiresAuth=false")
        if workload is not None and load_manifest(workload_id).get("security", {}).get("publicAllowed") is not True:
            blockers.append("workload manifest does not allow public exposure")
        if not has_stage_evidence(load_evidence(evidence_dir()), workload_id, "protected", hostname):
            blockers.append("public mode requires recorded protected-stage evidence first (D027)")
    if not service:
        blockers.append("missing local service URL")
    if provider.get("enabled") is not True:
        blockers.append("Cloudflare provider is disabled")
    if provider.get("provisioned") is not True:
        blockers.append("Cloudflare provider is not provisioned")
    if provider.get("allowNamedTunnels") is not True:
        blockers.append("named tunnels are not allowed by exposure policy")
    if provider.get("allowQuickTunnels") is not False:
        blockers.append("quick tunnels must remain disabled")
    if _inside_repo(config_path):
        blockers.append("activation config path must be outside the Git repository")
    if not shutil.which("cloudflared"):
        warnings.append("cloudflared is not installed; ingress validation/start cannot run yet")

    return {
        "ok": not blockers,
        "workloadId": workload_id,
        "mode": mode,
        "targetState": MODES[mode],
        "hostname": hostname,
        "hostnames": list(workload_hosts),
        "service": service,
        "privacy": privacy,
        "providerEnabled": provider.get("enabled") is True,
        "allowQuickTunnels": bool(provider.get("allowQuickTunnels")),
        "configPath": str(config_path),
        "blockers": blockers,
        "warnings": warnings,
        "admission": admission.as_dict(),
        "manualChecks": [
            "Cloudflare named tunnel exists and credentials are stored outside Git.",
            "protected: a Cloudflare Access application limited to the operator covers every hostname."
            if mode == "protected"
            else "public: the Access application was removed only after the protected stage was verified.",
            "DNS for the hostnames points at the named tunnel only.",
        ],
    }


def validate_ingress(config_path: Path) -> dict[str, Any]:
    if not shutil.which("cloudflared"):
        return {"ok": False, "reason": "cloudflared unavailable"}
    result = subprocess.run(
        ["cloudflared", "tunnel", "--config", str(config_path), "ingress", "validate"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def reload_cloudflared() -> dict[str, Any]:
    return _systemctl("reload-or-restart")


def stop_cloudflared() -> dict[str, Any]:
    return _systemctl("stop")


def _systemctl(action: str) -> dict[str, Any]:
    result = subprocess.run(
        ["systemctl", action, "cloudflared"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def install_config(config_path: Path, text: str) -> dict[str, Any]:
    """Validate `text` as a sibling temp file, then atomically replace the live config."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp = config_path.with_name(f".{config_path.name}.argus-tmp")
    temp.write_text(text, encoding="utf-8")
    os.chmod(temp, config_path.stat().st_mode & 0o777 if config_path.exists() else 0o640)
    validation = validate_ingress(temp)
    if not validation["ok"]:
        temp.unlink(missing_ok=True)
        return validation
    os.replace(temp, config_path)
    return validation


def write_evidence(payload: dict[str, Any]) -> Path:
    directory = evidence_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now().replace(":", "").replace("-", "")
    path = directory / f"{stamp}-{payload['workloadId']}-{payload['mode']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def preflight_refusal(workload_id: str, state: str) -> str:
    """Why the effective state could not be applied even after a good probe; empty when it could."""
    admission = evaluate_current(root(), workload_id, "access.cloudflare-protected.apply")
    if not admission.allowed:
        return str(admission.decision_code)
    decision = policy_decision(workload_id, state)
    return "" if decision.get("allowed") else str(decision.get("reason", "policy denied"))


def set_effective(workload_id: str, state: str, actor: str, pending: dict[str, Any]) -> dict[str, Any]:
    """Make `state` effective. Policy only plans Cloudflare states; this is the one path that
    promotes one, and only when the allowlist, provider and evidence (including `pending`) agree."""
    refusal = preflight_refusal(workload_id, state)
    if refusal:
        raise PermissionError(refusal)
    hostname = str(_route(workload_id).get("hostname", ""))
    blockers = effective_blockers(load_json("exposure.json"), workload_id, hostname, state, [*load_evidence(evidence_dir()), pending])
    if blockers:
        raise PermissionError("; ".join(blockers))
    decision = {**policy_decision(workload_id, state), "effective": state, "plannedOnly": False, "reason": "verified Cloudflare activation (D027)"}
    return access_writer().apply(workload_id=workload_id, desired=state, decision=decision, actor=actor, timestamp=now())


def rollback_target(workload_id: str) -> str:
    tailnet = load_json("routes.json").get("workloadRoutes", {}).get(workload_id, {}).get("tailnet", {})
    return "tailnet" if tailnet.get("enabled") is True else "local"


def lower_effective(workload_id: str, actor: str) -> dict[str, Any]:
    admission = evaluate_current(root(), workload_id, "access.cloudflare-protected.rollback")
    if not admission.allowed:
        raise PermissionError(admission.decision_code)
    target = rollback_target(workload_id)
    decision = {"allowed": True, "effective": target, "plannedOnly": False, "reason": "Cloudflare activation rolled back"}
    return access_writer().apply(workload_id=workload_id, desired=target, decision=decision, actor=actor, timestamp=now())


def write_rollback_record(workload_id: str, hostnames: tuple[str, ...]) -> Path:
    """Supersede every earlier activation evidence record for the workload."""
    return write_evidence({"ok": True, "workloadId": workload_id, "mode": ROLLED_BACK, "hostnames": list(hostnames), "recordedAt": now()})


def print_preview(plan: dict[str, Any]) -> None:
    state = "ready" if plan["ok"] else "blocked"
    print(f"{plan['workloadId']} Cloudflare {plan['mode']} activation: {state}")
    print(f"Hostnames: {', '.join(plan['hostnames']) or '-'}")
    print(f"Service: {plan['service'] or '-'}")
    for title, items in (("Blockers", plan["blockers"]), ("Warnings", plan["warnings"]), ("Manual checks", plan["manualChecks"])):
        if items:
            print(f"{title}:")
            for item in items:
                print(f"- {item}")


def json_or_text(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print_json(payload)
    else:
        print_preview(payload)


def audit_preview(plan: dict[str, Any]) -> None:
    audit(
        "cloudflare.activate.preview",
        str(plan["workloadId"]),
        "ok" if plan["ok"] else "blocked",
        mode=plan["mode"],
        hostname=plan.get("hostname", ""),
        blockers=plan.get("blockers", []),
    )
