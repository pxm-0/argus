#!/usr/bin/env python3
"""Collect safe host metrics for the private Argus dashboard."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "control-plane" / "dashboard" / "public"
OUT = PUBLIC / "metrics.json"
HISTORY = ROOT / "runtime" / "metrics-history" / "metrics.jsonl"
OBSERVATIONS_DB = Path(os.environ.get("ARGUS_OBSERVATIONS_DB", ROOT / "runtime" / "argus" / "observations.sqlite3"))
WORKLOADS_CONFIG = ROOT / "config" / "workloads.json"


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return default


def uptime_seconds() -> int:
    value = read_text(Path("/proc/uptime"), "0").split()[0]
    return int(float(value))


def load_average() -> dict[str, float]:
    one, five, fifteen = os.getloadavg()
    return {"one": round(one, 2), "five": round(five, 2), "fifteen": round(fifteen, 2)}


def cpu_times() -> list[int]:
    lines = read_text(Path("/proc/stat")).splitlines()
    if not lines:
        return []
    parts = lines[0].split()[1:]
    return [int(part) for part in parts]


def cpu_percent(interval: float = 0.15) -> float:
    first = cpu_times()
    if not first:
        return 0.0
    time.sleep(interval)
    second = cpu_times()
    if not second:
        return 0.0
    idle_a = first[3] + (first[4] if len(first) > 4 else 0)
    idle_b = second[3] + (second[4] if len(second) > 4 else 0)
    total_a = sum(first)
    total_b = sum(second)
    total_delta = total_b - total_a
    idle_delta = idle_b - idle_a
    if total_delta <= 0:
        return 0.0
    return round((1 - idle_delta / total_delta) * 100, 1)


def meminfo() -> dict[str, int]:
    data: dict[str, int] = {}
    for line in read_text(Path("/proc/meminfo")).splitlines():
        key, value = line.split(":", 1)
        data[key] = int(value.strip().split()[0]) * 1024
    return data


def memory() -> dict[str, float | int]:
    info = meminfo()
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = max(total - available, 0)
    percent = round((used / total) * 100, 1) if total else 0.0
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = max(swap_total - swap_free, 0)
    swap_percent = round((swap_used / swap_total) * 100, 1) if swap_total else 0.0
    return {
        "totalBytes": total,
        "usedBytes": used,
        "percent": percent,
        "swapTotalBytes": swap_total,
        "swapUsedBytes": swap_used,
        "swapPercent": swap_percent,
    }


def disk() -> dict[str, float | int | str]:
    usage = shutil.disk_usage("/")
    return {
        "mount": "/",
        "totalBytes": usage.total,
        "usedBytes": usage.used,
        "percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0.0,
    }


def network() -> list[dict[str, int | str]]:
    rows = []
    for line in read_text(Path("/proc/net/dev")).splitlines()[2:]:
        iface, rest = line.split(":", 1)
        fields = rest.split()
        rows.append({"interface": iface.strip(), "rxBytes": int(fields[0]), "txBytes": int(fields[8])})
    return rows


COMMAND_TIMEOUT_SECONDS = 20


def run_json_lines(command: list[str], timeout: float = COMMAND_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    if not shutil.which(command[0]):
        return []
    try:
        result = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:  # a stuck docker child must not hold the unit in activating
        return []
    rows = []
    for line in result.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def docker_containers() -> list[dict[str, str]]:
    rows = run_json_lines(["docker", "ps", "--format", "{{json .}}"])
    return [
        {
            "name": str(row.get("Names", "")),
            "image": str(row.get("Image", "")),
            "status": str(row.get("Status", "")),
        }
        for row in rows
    ]


def docker_stats() -> list[dict[str, str]]:
    rows = run_json_lines(["docker", "stats", "--no-stream", "--format", "{{json .}}"])
    return [
        {
            "name": str(row.get("Name", "")),
            "cpuPercent": str(row.get("CPUPerc", "")),
            "memory": str(row.get("MemUsage", "")),
            "memoryPercent": str(row.get("MemPerc", "")),
        }
        for row in rows
    ]


def processes(limit: int = 8) -> list[dict[str, float | int | str]]:
    if not shutil.which("ps"):
        return []
    result = subprocess.run(
        ["ps", "-eo", "pid=,%cpu=,%mem=,comm=", "--sort=-%cpu"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    rows = []
    for line in result.stdout.splitlines()[:limit]:
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        try:
            rows.append(
                {
                    "pid": int(parts[0]),
                    "cpuPercent": float(parts[1]),
                    "memoryPercent": float(parts[2]),
                    "name": parts[3],
                }
            )
        except ValueError:
            continue
    return rows


def temperatures() -> list[dict[str, float | str]]:
    rows = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        temp = read_text(zone / "temp")
        if not temp:
            continue
        label = read_text(zone / "type", zone.name)
        try:
            rows.append({"sensor": label, "celsius": round(int(temp) / 1000, 1)})
        except ValueError:
            continue
    return rows


def compose_project_workloads(config: Path = WORKLOADS_CONFIG) -> dict[str, str]:
    try:
        items = json.loads(config.read_text()).get("workloads", [])
    except (OSError, ValueError):
        return {}
    return {
        str((item.get("runtime") or {}).get("composeProject", "")): str(item.get("id", ""))
        for item in items
        if (item.get("runtime") or {}).get("composeProject")
    }


def workload_metrics(database: Path = OBSERVATIONS_DB, config: Path = WORKLOADS_CONFIG) -> list[dict[str, Any]]:
    """Per-Compose-project container health from the latest observation run of every active source.

    Reads the D2 observation repository, so rootless trust domains are visible without any Docker access.
    """
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    except (sqlite3.Error, OSError):
        return []
    try:
        rows = connection.execute(
            """
            SELECT o.source_id, o.observed_at, o.attributes_json
            FROM observations o
            JOIN sources s ON s.source_id = o.source_id AND s.current_run_id = o.run_id
            WHERE s.active = 1 AND o.resource_kind = 'container'
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    ids = compose_project_workloads(config)
    projects: dict[tuple[str, str], dict[str, Any]] = {}
    for source_id, observed_at, attributes_json in rows:
        try:
            attributes = json.loads(attributes_json)
        except ValueError:
            continue
        project = str(attributes.get("project", ""))
        entry = projects.setdefault(
            (source_id, project),
            {
                "workloadId": ids.get(project, ""),
                "project": project,
                "source": source_id,
                "containers": 0,
                "running": 0,
                "unhealthy": 0,
                "observedAt": "",
                "services": [],
            },
        )
        lifecycle, health = str(attributes.get("lifecycle", "")), str(attributes.get("health", ""))
        entry["containers"] += 1
        entry["running"] += lifecycle == "running"
        entry["unhealthy"] += health == "unhealthy"
        entry["observedAt"] = max(entry["observedAt"], str(observed_at))
        entry["services"].append({"service": str(attributes.get("service", "")), "lifecycle": lifecycle, "health": health})
    return sorted(projects.values(), key=lambda item: (item["project"], item["source"]))


def collect() -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "hostname": socket.gethostname(),
        "uptimeSeconds": uptime_seconds(),
        "load": load_average(),
        "cpu": {"percent": cpu_percent()},
        "memory": memory(),
        "disk": disk(),
        "network": network(),
        "docker": {"containers": docker_containers(), "stats": docker_stats()},
        "workloads": workload_metrics(),
        "processes": processes(),
        "temperatures": temperatures(),
    }


def main() -> int:
    metrics = collect()
    PUBLIC.mkdir(parents=True, exist_ok=True)
    temp_path = OUT.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    temp_path.replace(OUT)

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as history:
        history.write(json.dumps(metrics, sort_keys=True) + "\n")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
