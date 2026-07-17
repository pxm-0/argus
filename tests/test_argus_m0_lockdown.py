from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class LockdownTest(unittest.TestCase):
    def test_guard_is_explicit_and_reversible(self) -> None:
        text = (ROOT / "scripts" / "argus-m0-docker-lockdown").read_text()
        self.assertIn("--acknowledge-workload-lockdown", text)
        self.assertIn("--confirm-workload-unlock", text)
        self.assertIn("--install-systemd", text)
        self.assertIn("ip6tables unavailable; refusing partial IPv4-only containment", text)
        self.assertIn("-i lo -j RETURN", text)
        self.assertIn("-i 'docker+' -j RETURN", text)
        self.assertIn("-j DROP", text)
        self.assertIn("apply_family ip6tables", text)
        self.assertIn("systemctl enable --now", text)
        unit = (ROOT / "systemd" / "argus-m0-docker-lockdown.service").read_text()
        self.assertIn("After=docker.service", unit)
        self.assertIn("argus-m0-docker-lockdown --apply --acknowledge-workload-lockdown", unit)
