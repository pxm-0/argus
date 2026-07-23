from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_locigraph_cutover import CutoverError, override_text, validate_effective  # noqa: E402


def effective() -> dict:
    services = {name: {"restart": "unless-stopped", "ports": []} for name in ("backend", "caddy", "frontend", "postgres", "redis", "worker")}
    services["caddy"]["ports"] = [{"host_ip": "127.0.0.1", "published": "8090", "target": 80, "protocol": "tcp"}]
    return {"name": "locigraph", "services": services}


class LociGraphCutoverTests(unittest.TestCase):
    def test_override_removes_sensitive_ports_and_binds_caddy_to_loopback(self) -> None:
        text = override_text()
        self.assertIn('"127.0.0.1:8090:80"', text)
        self.assertEqual(3, text.count("ports: !reset []"))
        self.assertEqual(6, text.count("restart: unless-stopped"))

    def test_effective_contract_passes_only_exact_publication(self) -> None:
        report = validate_effective(effective())
        self.assertTrue(report["verified"])
        self.assertFalse(report["databaseHostPublished"])

    def test_database_publication_is_rejected(self) -> None:
        payload = effective()
        payload["services"]["postgres"]["ports"] = [{"host_ip": "127.0.0.1", "published": 15432, "target": 5432}]
        with self.assertRaises(CutoverError):
            validate_effective(payload)

    def test_wildcard_caddy_is_rejected(self) -> None:
        payload = effective()
        payload["services"]["caddy"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(CutoverError):
            validate_effective(payload)

    def test_apply_is_explicit_and_rolls_back_to_stopped(self) -> None:
        text = (ROOT / "scripts" / "argus-locigraph-production-cutover").read_text()
        self.assertIn("--acknowledge-locigraph-production-cutover", text)
        self.assertIn("trap stop_on_failure ERR", text)
        self.assertIn("compose stop", text)
        self.assertNotIn("docker compose down", text)
        self.assertNotIn("tailscale funnel", text.lower())


if __name__ == "__main__":
    unittest.main()
