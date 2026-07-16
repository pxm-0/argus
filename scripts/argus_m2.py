"""Read-only, redacted prerequisite evidence for the Argus M2 pilot."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class PilotError(ValueError):
    pass


def evaluate_pilot(*, subordinate_ids: bool, rootless_tool: bool, linger: bool, cgroup_v2: bool, storage: bool, namespace_tool: bool) -> dict[str, Any]:
    checks = {
        "subordinateIds": subordinate_ids,
        "rootlessTooling": rootless_tool,
        "userLinger": linger,
        "cgroupV2": cgroup_v2,
        "storageDriver": storage,
        "namespaceTooling": namespace_tool,
    }
    return {"schemaVersion": 1, "complete": all(checks.values()), "checks": checks, "missing": sorted(name for name, value in checks.items() if not value)}


def _run(command: list[str]) -> tuple[int, str]:
    if not shutil.which(command[0]):
        return 127, ""
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return result.returncode, result.stdout


def collect_pilot(user: str) -> dict[str, Any]:
    if not user or any(char.isspace() for char in user):
        raise PilotError("a local Unix user name is required")
    subuid = Path("/etc/subuid").read_text(encoding="utf-8", errors="ignore") if Path("/etc/subuid").exists() else ""
    subordinate_ids = any(line.split(":", 1)[0] == user for line in subuid.splitlines() if ":" in line)
    _, linger_output = _run(["loginctl", "show-user", user, "-p", "Linger"])
    _, storage_output = _run(["docker", "info", "--format", "{{.Driver}}"])
    return evaluate_pilot(
        subordinate_ids=subordinate_ids,
        rootless_tool=shutil.which("dockerd-rootless-setuptool.sh") is not None,
        linger="Linger=yes" in linger_output,
        cgroup_v2=Path("/sys/fs/cgroup/cgroup.controllers").exists(),
        storage=bool(storage_output.strip()),
        namespace_tool=shutil.which("unshare") is not None,
    )
