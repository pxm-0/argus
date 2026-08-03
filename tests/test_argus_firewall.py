from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_firewall import (  # noqa: E402
    FirewallPolicyError,
    POLICY_KEYS,
    canonical_digest,
    render_firewall,
    validate_connectivity,
    validate_networks,
)


NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)
NETWORKS = [
    {"project": "alpha", "network": "default", "networkId": "a" * 64, "interface": "br-aaaaaaaaaaaa"},
    {"project": "beta", "network": "default", "networkId": "b" * 64, "interface": "br-bbbbbbbbbbbb"},
]
ENDPOINTS = [
    {
        "project": "beta",
        "network": "default",
        "service": "api",
        "addresses": ["172.20.0.4"],
    }
]


def policy(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "alpha-to-beta-api",
        "sourceProject": "alpha",
        "sourceNetwork": "default",
        "targetProject": "beta",
        "targetNetwork": "default",
        "targetService": "api",
        "direction": "source-to-target",
        "protocol": "tcp",
        "destinationPort": 8443,
        "owner": "operator",
        "reason": "reviewed integration",
        "expiresAt": None,
    }
    value.update(overrides)
    return value


class FirewallPolicyTests(unittest.TestCase):
    def test_default_policy_is_exact_same_project_only(self) -> None:
        rendered = render_firewall("personal-sandbox", NETWORKS)
        self.assertIn(
            'iifname "br-aaaaaaaaaaaa" oifname "br-aaaaaaaaaaaa" accept;',
            rendered,
        )
        self.assertIn(
            'iifname "br-bbbbbbbbbbbb" oifname "br-bbbbbbbbbbbb" accept;',
            rendered,
        )
        self.assertNotIn('iifname "br-aaaaaaaaaaaa" oifname "br-bbbbbbbbbbbb"', rendered)
        self.assertNotIn("br-*", rendered)

    def test_same_project_multiple_networks_are_canonical_relationships(self) -> None:
        networks = NETWORKS + [
            {"project": "alpha", "network": "worker", "networkId": "c" * 64, "interface": "br-cccccccccccc"}
        ]
        rendered = render_firewall("personal-sandbox", networks)
        self.assertIn(
            'iifname "br-aaaaaaaaaaaa" oifname "br-cccccccccccc" accept;',
            rendered,
        )
        self.assertIn(
            'iifname "br-cccccccccccc" oifname "br-aaaaaaaaaaaa" accept;',
            rendered,
        )

    def test_connectivity_policy_is_direction_port_protocol_and_service_scoped(self) -> None:
        policies = validate_connectivity({"schemaVersion": 1, "policies": [policy()]}, now=NOW)
        rendered = render_firewall(
            "personal-sandbox",
            NETWORKS,
            connectivity=policies,
            endpoints=ENDPOINTS,
        )
        self.assertIn(
            'iifname "br-aaaaaaaaaaaa" oifname "br-bbbbbbbbbbbb" '
            "ip daddr 172.20.0.4 tcp dport 8443 ct state new,established accept;",
            rendered,
        )
        self.assertIn(
            'iifname "br-bbbbbbbbbbbb" oifname "br-aaaaaaaaaaaa" '
            "ip saddr 172.20.0.4 tcp sport 8443 ct state established,related accept;",
            rendered,
        )
        self.assertNotIn("udp dport 8443", rendered)
        self.assertNotIn("tcp dport 443", rendered)

    def test_connectivity_policy_removal_removes_the_grant(self) -> None:
        rendered = render_firewall("personal-sandbox", NETWORKS, connectivity=[], endpoints=ENDPOINTS)
        self.assertNotIn("172.20.0.4", rendered)
        self.assertNotIn('iifname "br-aaaaaaaaaaaa" oifname "br-bbbbbbbbbbbb"', rendered)

    def test_expired_wrong_direction_protocol_port_and_same_project_are_rejected(self) -> None:
        mutations = (
            {"expiresAt": "2026-08-02T00:00:00Z"},
            {"direction": "target-to-source"},
            {"protocol": "icmp"},
            {"destinationPort": 0},
            {"destinationPort": True},
            {"targetProject": "alpha"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(FirewallPolicyError):
                validate_connectivity(
                    {"schemaVersion": 1, "policies": [policy(**mutation)]},
                    now=NOW,
                )

    def test_integral_json_port_is_normalized_like_json_schema_integer(self) -> None:
        policies = validate_connectivity(
            {"schemaVersion": 1.0, "policies": [policy(destinationPort=8443.0)]},
            now=NOW,
        )
        self.assertEqual(8443, policies[0]["destinationPort"])
        self.assertIsInstance(policies[0]["destinationPort"], int)

    def test_unresolved_target_service_is_rejected(self) -> None:
        policies = validate_connectivity({"schemaVersion": 1, "policies": [policy()]}, now=NOW)
        with self.assertRaises(FirewallPolicyError):
            render_firewall("personal-sandbox", NETWORKS, connectivity=policies, endpoints=[])

    def test_unknown_duplicate_or_malformed_runtime_mappings_are_rejected(self) -> None:
        duplicate = NETWORKS + [dict(NETWORKS[0])]
        with self.assertRaises(FirewallPolicyError):
            validate_networks(duplicate)
        malformed = [dict(NETWORKS[0], interface="br-*")]
        with self.assertRaises(FirewallPolicyError):
            validate_networks(malformed)
        for mutation in (
            [dict(NETWORKS[0], networkId=int("1" * 12))],
            [dict(NETWORKS[0], interface=123)],
        ):
            with self.assertRaises(FirewallPolicyError):
                validate_networks(mutation)

    def test_policy_type_confusion_is_rejected_without_internal_exceptions(self) -> None:
        for mutation in (
            {"id": 123},
            {"protocol": ["tcp"]},
            {"sourceProject": ["alpha"]},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(FirewallPolicyError):
                validate_connectivity(
                    {"schemaVersion": 1, "policies": [policy(**mutation)]},
                    now=NOW,
                )
        with self.assertRaises(FirewallPolicyError):
            render_firewall(
                "personal-sandbox",
                NETWORKS,
                egress={"alpha": {"project": "alpha", "resolver": [], "allow": (("tcp", 443),), "reason": "x", "probeHost": "example.com"}},
            )

    def test_egress_uses_the_resolved_project_interface_without_pivot_rule(self) -> None:
        rendered = render_firewall(
            "personal-sandbox",
            NETWORKS,
            egress={
                "alpha": {
                    "project": "alpha",
                    "resolver": "10.0.2.3",
                    "allow": (("tcp", 443),),
                    "reason": "reviewed crawl",
                    "probeHost": "example.com",
                }
            },
        )
        self.assertIn(
            'iifname "br-aaaaaaaaaaaa" oifname "tap0" tcp dport 443', rendered
        )
        self.assertIn(
            'iifname "tap0" oifname "br-aaaaaaaaaaaa" ct state established,related accept;',
            rendered,
        )
        self.assertNotIn('iifname "br-bbbbbbbbbbbb" oifname "tap0"', rendered)

    def test_digest_is_order_independent_for_object_keys(self) -> None:
        self.assertEqual(canonical_digest({"a": 1, "b": 2}), canonical_digest({"b": 2, "a": 1}))

    def test_checked_in_connectivity_document_is_default_deny(self) -> None:
        document = json.loads((ROOT / "config" / "sandbox-connectivity.json").read_text())
        self.assertEqual([], validate_connectivity(document, now=NOW))
        schema = json.loads((ROOT / "config" / "schemas" / "sandbox-connectivity.schema.json").read_text())
        item_schema = schema["properties"]["policies"]["items"]
        self.assertEqual(POLICY_KEYS, set(item_schema["required"]))


if __name__ == "__main__":
    unittest.main()
