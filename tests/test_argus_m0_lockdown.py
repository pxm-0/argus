from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class LockdownTest(unittest.TestCase):
    def test_guard_is_explicit_and_reversible(self) -> None:
        text = (ROOT / "scripts" / "argus-m0-docker-lockdown").read_text()
        self.assertIn("--acknowledge-workload-lockdown", text)
        self.assertIn("--confirm-workload-unlock", text)
        self.assertIn("-i lo -j RETURN", text)
        self.assertIn("-i 'docker+' -j RETURN", text)
        self.assertIn("-j DROP", text)
