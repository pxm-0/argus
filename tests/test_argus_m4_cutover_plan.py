from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m4_cutover_plan import CutoverPlanError, build_plan, inspect_stateless_compose  # noqa: E402


PREFLIGHT = {
    "workloadId": "hello-nginx", "backupVerified": True, "restoreVerified": True,
    "sourceHealthVerified": True, "targetDaemonVerified": True, "targetEmptyVerified": True,
    "targetNoTcpListenersVerified": True,
}
COMPOSE = {"name": "hello-nginx", "services": {"web": {"image": "nginx:stable"}}}


class CutoverPlanTest(unittest.TestCase):
    def test_stateless_compose_generates_unapproved_plan(self) -> None:
        plan = build_plan(preflight=PREFLIGHT, compose=COMPOSE, target_empty=True)
        self.assertFalse(plan["cutoverApproved"])
        self.assertTrue(plan["sourceComposeDigest"].startswith("sha256:"))

    def test_permits_only_loopback_source_ports_for_removal(self) -> None:
        loopback = {"services": {"web": {"image": "nginx:stable", "ports": [{"host_ip": "127.0.0.1", "published": "18080", "target": 80}]}}}
        self.assertTrue(inspect_stateless_compose(loopback)["sourceLoopbackPortsRemoved"])
        wildcard = {"services": {"web": {"image": "nginx:stable", "ports": [{"host_ip": "0.0.0.0", "published": "8080", "target": 80}]}}}
        with self.assertRaises(CutoverPlanError):
            inspect_stateless_compose(wildcard)

    def test_forbidden_service_capabilities_fail_closed(self) -> None:
        mounted = {"services": {"web": {"image": "nginx:stable", "volumes": ["/:/host:ro"]}}}
        with self.assertRaises(CutoverPlanError):
            inspect_stateless_compose(mounted)
        missing_preflight = dict(PREFLIGHT)
        missing_preflight["targetEmptyVerified"] = False
        with self.assertRaises(CutoverPlanError):
            build_plan(preflight=missing_preflight, compose=COMPOSE, target_empty=True)
