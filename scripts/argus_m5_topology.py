"""Build the redacted, read-only M5 estate topology projection."""

from __future__ import annotations

from typing import Any


DOMAIN_ORDER = (
    "management",
    "legacy-rootful",
    "personal-sandbox",
    "personal-managed",
    "work-sandbox",
    "work-managed",
)


def build_topology(
    *,
    workloads: list[dict[str, Any]],
    legacy: dict[str, Any],
    classified: dict[str, Any],
) -> dict[str, Any]:
    """Return a value-allowlisted topology; never copy arbitrary runtime data."""
    legacy_map = legacy.get("workloads", {})
    target_map = classified.get("workloads", {})
    domains = {
        domain_id: {
            "id": domain_id,
            "kind": "management" if domain_id == "management" else ("legacy" if domain_id == "legacy-rootful" else "workload"),
            "workloadIds": [],
        }
        for domain_id in DOMAIN_ORDER
    }
    nodes = [
        {"id": "host", "kind": "host", "label": "oreochiserver"},
        {"id": "management", "kind": "management", "label": "Management plane"},
    ]
    edges = [{"source": "host", "target": "management", "meaning": "containment"}]
    drift_count = 0
    unresolved_count = 0

    for domain_id in DOMAIN_ORDER[1:]:
        nodes.append({"id": domain_id, "kind": "trust-domain", "label": domain_id})
        edges.append({"source": "host", "target": domain_id, "meaning": "containment"})

    for workload in workloads:
        workload_id = str(workload.get("id", ""))
        target = target_map.get(workload_id)
        placement = target if isinstance(target, dict) else legacy_map.get(workload_id, legacy.get("default", {}))
        domain_id = str(placement.get("trustDomain", "legacy-rootful"))
        if domain_id not in domains:
            domain_id = "legacy-rootful"
        access = workload.get("access", {})
        desired = str(access.get("desired", "none"))
        effective = str(access.get("effective", "none"))
        drift = desired != effective
        unresolved = str(placement.get("status", "")) != "classified"
        drift_count += int(drift)
        unresolved_count += int(unresolved)
        domains[domain_id]["workloadIds"].append(workload_id)
        nodes.append(
            {
                "id": workload_id,
                "kind": "workload",
                "label": str(workload.get("name") or workload_id),
                "trustDomain": domain_id,
                "realm": str(placement.get("realm", "unclassified")),
                "zone": str(placement.get("zone", "legacy")),
                "stage": str(placement.get("stage", "none")),
                "classificationStatus": str(placement.get("status", "legacy-unclassified")),
                "admission": str(placement.get("admission", "denied")),
                "declaredAccess": desired,
                "effectiveAccess": effective,
                "drift": drift,
                "controlMode": "domain-agent" if domain_id != "legacy-rootful" else "compatibility-agent",
                "agentAvailable": False,
            }
        )
        edges.append({"source": domain_id, "target": workload_id, "meaning": "runtime-placement"})
        routes = workload.get("routes", {})
        if routes.get("tailnet", {}).get("enabled"):
            edges.append({"source": workload_id, "target": "tailnet", "meaning": "route"})

    for domain in domains.values():
        domain["workloadIds"].sort()
        domain["state"] = "active" if domain["workloadIds"] else "empty"

    return {
        "schemaVersion": 1,
        "readOnly": True,
        "domains": [domains[item] for item in DOMAIN_ORDER],
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "knownResources": len(workloads),
            "unresolvedClassifications": unresolved_count,
            "accessDrift": drift_count,
            "domainAgentsAvailable": 0,
        },
        "edgeMeanings": ["containment", "runtime-placement", "route"],
    }
