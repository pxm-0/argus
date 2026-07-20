"""Fail-closed evaluation for the M4 personal-sandbox persistence gate."""

from __future__ import annotations

from typing import Any


REQUIRED = {
    "daemonActive",
    "targetRunning",
    "targetHealthy",
    "sourceFenced",
    "publishedPortsAbsent",
    "hostMountsAbsent",
    "namespaceListenersAbsent",
    "delegationEnabled",
    "cgroupDriverCorrect",
    "hostRebootedAfterCutover",
}


def evaluate_persistence(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != REQUIRED:
        raise ValueError("persistence evidence must contain exactly the required facts")
    if not all(isinstance(facts[key], bool) for key in REQUIRED):
        raise ValueError("persistence evidence facts must be boolean")
    failed = sorted(key for key in REQUIRED if not facts[key])
    return {
        "schemaVersion": 1,
        "workloadId": "hello-nginx",
        "trustDomain": "personal-sandbox",
        "verified": not failed,
        "failedChecks": failed,
        **{key: facts[key] for key in sorted(REQUIRED)},
    }
