"""Read-only, redacted prerequisite evidence for the Argus M2 pilot."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


class PilotError(ValueError):
    pass


def evaluate_pilot(*, subordinate_ids: bool, rootless_tool: bool, linger: bool, cgroup_v2: bool, storage: bool, namespace_tool: bool, user_networking: bool) -> dict[str, Any]:
    checks = {
        "subordinateIds": subordinate_ids,
        "rootlessTooling": rootless_tool,
        "userLinger": linger,
        "cgroupV2": cgroup_v2,
        "storageDriver": storage,
        "namespaceTooling": namespace_tool,
        "userNetworking": user_networking,
    }
    return {"schemaVersion": 1, "complete": all(checks.values()), "checks": checks, "missing": sorted(name for name, value in checks.items() if not value)}


def collect_pilot(user: str) -> dict[str, Any]:
    if not user or any(char.isspace() for char in user):
        raise PilotError("a local Unix user name is required")
    subuid = Path("/etc/subuid").read_text(encoding="utf-8", errors="ignore") if Path("/etc/subuid").exists() else ""
    subordinate_ids = any(line.split(":", 1)[0] == user for line in subuid.splitlines() if ":" in line)
    linger_output = ""
    if shutil.which("loginctl"):
        import subprocess
        result = subprocess.run(["loginctl", "show-user", user, "-p", "Linger"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        linger_output = result.stdout
    return evaluate_pilot(
        subordinate_ids=subordinate_ids,
        rootless_tool=shutil.which("dockerd-rootless-setuptool.sh") is not None,
        linger="Linger=yes" in linger_output,
        cgroup_v2=Path("/sys/fs/cgroup/cgroup.controllers").exists(),
        storage=shutil.which("fuse-overlayfs") is not None,
        namespace_tool=shutil.which("unshare") is not None,
        user_networking=shutil.which("slirp4netns") is not None,
    )
