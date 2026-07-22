---
version: 1
slug: "control-plane-dashboard-generate-dashboard-py"
primary_target: "control-plane/dashboard/generate_dashboard.py"
related_targets: []
---

# Argus private estate dashboard

- Mode: Operate.
- Audience: the single private oreochiserver operator.
- Job: understand trust boundaries, placement, drift, exposure, and operation eligibility before changing anything.
- Primary task: select a real workload in the topology, inspect declared and effective state, then use only policy-backed controls.
- Proof: canonical workload/classification/access/route data, explicit quarantine, and visible empty trust domains.
- Constraints: private-only, no fabricated telemetry, no public routes, keyboard-accessible list equivalent, target-domain controls fail closed without an agent.
- Direction: Orbital Operations Plot. The memorable moment is selecting a workload object and seeing its drift vector resolve into the inspection drawer without losing the whole-estate view.
- Unresolved: freshness/provenance and typed domain-operation lifecycle arrive in later M5 gates.
