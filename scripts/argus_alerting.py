"""Pure alert evaluation for Argus: checks over injected inputs plus the open/resolve state engine.

Nothing here touches the host. scripts/argus-alert collects inputs and persists the state;
the checks and the reconcile step are deterministic so they can be tested with fixtures.
A check returns None when its input is unknown (file missing, tool absent); an unknown
check never opens an alert and never resolves one that is already open.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA_VERSION = 1
PAGE = "page"
WARN = "warn"
HOUR = 3600
DAY = 24 * HOUR

SMOKE_MAX_AGE = 26 * HOUR
SNAPSHOT_MAX_AGE = 24 * HOUR
DB_BACKUP_MAX_AGE = 26 * HOUR
BEHIND_MAX_AGE = 24 * HOUR
CONTAINER_EXITED_MAX_AGE = 7 * DAY
EXPIRY_WARNING_WINDOW = 14 * DAY
DISK_WARN_PERCENT = 80
DISK_PAGE_PERCENT = 90
HEALTH_FAILURES_TO_ALERT = 2
DETAIL_LIMIT = 200

Finding = dict[str, str]
Inputs = dict[str, Any]

_SECRET_ASSIGNMENT = re.compile(r"(?i)\b(token|secret|password|passwd|authorization|bearer|api[-_]?key)\b\s*[=:]?\s*\S+")
_AGE_IDENTITY = re.compile(r"AGE-SECRET-KEY-[A-Z0-9]+")
_LONG_OPAQUE = re.compile(r"\b[A-Za-z0-9+/_=-]{40,}\b")


def scrub(text: Any) -> str:
    """Bound and redact free text so an alert detail can never carry a credential."""
    value = "".join(ch if ch.isprintable() else " " for ch in str(text))
    value = _AGE_IDENTITY.sub("[redacted]", value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", value)
    value = _LONG_OPAQUE.sub("[redacted]", value)
    return value[:DETAIL_LIMIT]


def parse_timestamp(value: Any) -> float | None:
    """Epoch seconds from epoch numbers, '@epoch' (systemctl --timestamp=unix) or ISO-8601."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().removeprefix("@")
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def finding(alert_id: str, severity: str, detail: str) -> Finding:
    return {"id": alert_id, "severity": severity, "detail": scrub(detail)}


def _hours(seconds: float) -> str:
    return f"{seconds / HOUR:.1f}h"


def check_failed_units(inputs: Inputs, now: float) -> list[Finding] | None:
    units = inputs.get("failedUnits")
    if units is None:
        return None
    return [finding(f"unit-failed:{unit}", PAGE, "systemd unit is in the failed state") for unit in sorted(set(units))]


def check_smoke(inputs: Inputs, now: float) -> list[Finding] | None:
    latest = inputs.get("smokeLatest")
    if not isinstance(latest, dict):
        return None
    findings: list[Finding] = []
    stamp = parse_timestamp(latest.get("timestamp"))
    if latest.get("ok") is False:
        findings.append(
            finding("smoke-failed", PAGE, f"latest smoke failed: failures={latest.get('failures')} warnings={latest.get('warnings')}")
        )
    if stamp is None:
        findings.append(finding("smoke-stale", WARN, "latest smoke result has no readable timestamp"))
    elif now - stamp > SMOKE_MAX_AGE:
        findings.append(finding("smoke-stale", WARN, f"latest smoke is {_hours(now - stamp)} old (limit 26h)"))
    return findings


def check_snapshot(inputs: Inputs, now: float) -> list[Finding] | None:
    last = inputs.get("snapshotLast")
    if not isinstance(last, dict):
        return None
    stamp = parse_timestamp(last.get("timestamp"))
    if stamp is None:
        return [finding("snapshot-stale", PAGE, "snapshot-last.json has no readable timestamp")]
    if now - stamp > SNAPSHOT_MAX_AGE:
        return [finding("snapshot-stale", PAGE, f"newest snapshot is {_hours(now - stamp)} old (limit 24h)")]
    return []


def check_db_backups(inputs: Inputs, now: float) -> list[Finding] | None:
    backups = inputs.get("dbBackups")
    if not isinstance(backups, dict):
        return None
    findings: list[Finding] = []
    for name, item in sorted(backups.items()):
        finished = parse_timestamp(item.get("finishedAt")) if isinstance(item, dict) else None
        if finished is None or item.get("result") != "success":
            continue  # a failed run is the failed-unit check's job; a never-run unit has no age yet
        if now - finished > DB_BACKUP_MAX_AGE:
            findings.append(finding(f"db-backup-stale:{name}", PAGE, f"last successful dump is {_hours(now - finished)} old (limit 26h)"))
    return findings


def next_health_failures(previous: dict[str, int], probes: dict[str, dict] | None) -> dict[str, int]:
    """Consecutive failed probes per workload; unknown probes leave the counts alone."""
    if probes is None:
        return dict(previous)
    return {
        workload: int(previous.get(workload, 0)) + 1
        for workload, probe in sorted(probes.items())
        if not probe.get("ok")
    }


def check_health(inputs: Inputs, now: float) -> list[Finding] | None:
    probes = inputs.get("probes")
    if probes is None:
        return None
    failures = inputs.get("healthFailures") or {}
    severities = inputs.get("healthSeverity") or {}
    return [
        finding(
            f"health:{workload}",
            severities.get(workload, WARN),
            f"{count} consecutive failed health probes ({probes.get(workload, {}).get('detail', 'no detail')})",
        )
        for workload, count in sorted(failures.items())
        if count >= HEALTH_FAILURES_TO_ALERT and workload in probes
    ]


def check_stale_containers(inputs: Inputs, now: float) -> list[Finding] | None:
    containers = inputs.get("exitedContainers")
    if containers is None:
        return None
    findings = []
    for item in sorted(containers, key=lambda row: str(row.get("name"))):
        exited = parse_timestamp(item.get("exitedAt"))
        if exited is not None and now - exited > CONTAINER_EXITED_MAX_AGE:
            findings.append(finding(f"container-exited:{item.get('name')}", WARN, f"registered workload container exited {(now - exited) / DAY:.0f}d ago"))
    return findings


def check_disk(inputs: Inputs, now: float) -> list[Finding] | None:
    percent = inputs.get("diskPercent")
    if percent is None:
        return None
    if percent >= DISK_PAGE_PERCENT:
        return [finding("disk-usage", PAGE, f"root filesystem {percent:.0f}% full (page at 90%)")]
    if percent >= DISK_WARN_PERCENT:
        return [finding("disk-usage", WARN, f"root filesystem {percent:.0f}% full (warn at 80%)")]
    return []


def check_deploy_behind(inputs: Inputs, now: float) -> list[Finding] | None:
    behind = inputs.get("deployBehind")
    if not isinstance(behind, dict):
        return None
    oldest = parse_timestamp(behind.get("oldestCommitAt"))
    if behind.get("count", 0) > 0 and oldest is not None and now - oldest > BEHIND_MAX_AGE:
        return [finding("deploy-behind", WARN, f"/srv/argus is {behind['count']} commit(s) behind origin/main for {_hours(now - oldest)}")]
    return []


def check_egress_drift(inputs: Inputs, now: float) -> list[Finding] | None:
    drift = inputs.get("egressDrift")
    if drift is None:
        return None
    return [finding(f"egress-drift:{workload}", WARN, "persisted egress policy differs from the declaration") for workload, drifted in sorted(drift.items()) if drifted]


def check_m1_drift(inputs: Inputs, now: float) -> list[Finding] | None:
    status = inputs.get("m1Drift")
    if not isinstance(status, dict) or status.get("state") not in {"clean", "drift"}:
        return None  # not-applicable and unavailable are unknown, not healthy
    if status["state"] == "clean":
        return []
    return [finding("m1-drift", WARN, f"private M1 state differs from reviewed config {status.get('counts', {})}")]


def check_tailscale(inputs: Inputs, now: float) -> list[Finding] | None:
    tailscale = inputs.get("tailscale")
    if not isinstance(tailscale, dict):
        return None
    findings: list[Finding] = []
    if tailscale.get("backendState") != "Running":
        findings.append(finding("tailscale-backend", PAGE, f"tailscale BackendState is {tailscale.get('backendState')}"))
    expiry = parse_timestamp(tailscale.get("keyExpiry"))
    if expiry is not None and expiry - now <= EXPIRY_WARNING_WINDOW:
        severity = PAGE if expiry <= now else WARN
        findings.append(finding("tailscale-key-expiry", severity, f"node key expires in {(expiry - now) / DAY:.1f}d"))
    return findings


def check_certs(inputs: Inputs, now: float) -> list[Finding] | None:
    certs = inputs.get("certs")
    if certs is None:
        return None
    findings = []
    for item in sorted(certs, key=lambda row: str(row.get("name"))):
        expiry = parse_timestamp(item.get("notAfter"))
        if expiry is not None and expiry - now <= EXPIRY_WARNING_WINDOW:
            findings.append(finding(f"cert-expiry:{item.get('name')}", PAGE if expiry <= now else WARN, f"certificate expires in {(expiry - now) / DAY:.1f}d"))
    return findings


# (check, id prefix owned by the check) — the prefix lets an unknown check carry its alerts over.
CHECKS: tuple[tuple[Callable[[Inputs, float], list[Finding] | None], str], ...] = (
    (check_failed_units, "unit-failed:"),
    (check_smoke, "smoke-"),
    (check_snapshot, "snapshot-"),
    (check_db_backups, "db-backup-"),
    (check_health, "health:"),
    (check_stale_containers, "container-exited:"),
    (check_disk, "disk-"),
    (check_deploy_behind, "deploy-behind"),
    (check_egress_drift, "egress-drift:"),
    (check_m1_drift, "m1-drift"),
    (check_tailscale, "tailscale-"),
    (check_certs, "cert-expiry:"),
)


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def reconcile(
    findings: list[Finding], previous: list[dict], carried_prefixes: list[str], now: float
) -> tuple[list[dict], list[dict]]:
    """Edge-detect: returns (alerts, events). Events are opened, changed or resolved."""
    stamp = iso(now)
    current: dict[str, Finding] = {}
    for item in findings:
        old = current.get(item["id"])
        if old is None or (item["severity"] == PAGE and old["severity"] != PAGE):
            current[item["id"]] = item
    before = {alert["id"]: alert for alert in previous}
    alerts: list[dict] = []
    events: list[dict] = []
    for alert_id in sorted(current):
        item, old = current[alert_id], before.get(alert_id)
        if old is None:
            alert = {"id": alert_id, "severity": item["severity"], "since": stamp, "detail": item["detail"], "lastSeen": stamp, "acked": False}
            events.append({"event": "opened", "alert": alert})
        else:
            alert = {**old, "severity": item["severity"], "detail": item["detail"], "lastSeen": stamp}
            if old["severity"] != item["severity"]:
                events.append({"event": "changed", "alert": alert})
        alerts.append(alert)
    for alert_id, old in sorted(before.items()):
        if alert_id in current:
            continue
        if any(alert_id.startswith(prefix) for prefix in carried_prefixes):
            alerts.append(old)
        else:
            events.append({"event": "resolved", "alert": {**old, "resolvedAt": stamp}})
    return sorted(alerts, key=lambda alert: alert["id"]), events


def evaluate(inputs: Inputs, previous_state: dict, now: float) -> tuple[dict, list[dict]]:
    """Run every check over `inputs` and reconcile against the previous state document."""
    findings: list[Finding] = []
    carried: list[str] = []
    for check, prefix in CHECKS:
        result = check(inputs, now)
        if result is None:
            carried.append(prefix)
        else:
            findings.extend(result)
    previous = [alert for alert in previous_state.get("alerts", []) if isinstance(alert, dict) and "id" in alert]
    alerts, events = reconcile(findings, previous, carried, now)
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": iso(now),
        "alerts": alerts,
        "probeFailures": inputs.get("healthFailures") or {},
        "summary": {
            "open": len(alerts),
            "page": sum(1 for alert in alerts if alert["severity"] == PAGE),
            "warn": sum(1 for alert in alerts if alert["severity"] == WARN),
        },
    }
    return state, events
