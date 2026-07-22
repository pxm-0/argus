from __future__ import annotations
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m2_bootstrap import BootstrapError, first_free_subid_range, pilot_contract  # noqa: E402
class M2BootstrapTest(unittest.TestCase):
    def test_contract_is_fixed_and_has_no_exposure_path(self) -> None:
        contract = pilot_contract(domain="personal-sandbox-pilot", user="argus-pilot")
        self.assertTrue(contract["contractDigest"].startswith("sha256:"))
        self.assertIn("no-published-ports", contract["prohibitions"])
        with self.assertRaises(BootstrapError):
            pilot_contract(domain="work-managed", user="anything")

    def test_subordinate_range_avoids_both_uid_and_gid_allocations(self) -> None:
        start, end = first_free_subid_range(
            subuid="argus:100000:65536\nother:231072:65536\n",
            subgid="argus:165536:65536\n",
        )
        self.assertEqual((296608, 362143), (start, end))

    def test_bootstrap_is_explicit_and_sealed(self) -> None:
        script = (ROOT / "scripts" / "argus-m2-bootstrap").read_text(encoding="utf-8")
        self.assertIn("--acknowledge-disposable-pilot", script)
        self.assertIn("policy drop", script)
        self.assertIn("DOCKERD_ROOTLESS_ROOTLESSKIT_PORT_DRIVER=none", script)
        self.assertIn("--iptables=false", script)
        self.assertIn("NetworkNamespacePath=/run/netns/argus-pilot", script)

    def test_daemon_unit_has_a_service_owned_runtime_directory(self) -> None:
        script = (ROOT / "scripts" / "argus-m2-bootstrap").read_text(encoding="utf-8")
        self.assertIn("RuntimeDirectory=argus-pilot", script)
        self.assertIn("Environment=HOME=/home/argus-pilot", script)
        self.assertIn('install -d -o "$PILOT_USER" -g "$PILOT_USER" -m 0700 "$PILOT_HOME"', script)
        self.assertIn("RuntimeDirectoryMode=0700", script)
        self.assertIn("Environment=XDG_RUNTIME_DIR=/run/argus-pilot", script)
        self.assertIn("ProtectHome=read-only", script)
        self.assertNotIn("ProtectHome=yes", script)
        self.assertNotIn("Environment=XDG_RUNTIME_DIR=/run/user/", script)

    def test_bootstrap_uses_portable_heredoc_writes(self) -> None:
        script = (ROOT / "scripts" / "argus-m2-bootstrap").read_text(encoding="utf-8")
        self.assertNotIn("install -m 0644 /dev/stdin", script)
        self.assertNotIn("install -m 0755 /dev/stdin", script)
        self.assertIn('tee "$NFT_FILE" >/dev/null', script)

    def test_teardown_terminates_the_lingering_user_manager_first(self) -> None:
        script = (ROOT / "scripts" / "argus-m2-pilot-teardown").read_text(encoding="utf-8")
        self.assertIn('loginctl terminate-user "$USER" || true', script)
        self.assertIn('pgrep -u "$USER"', script)
