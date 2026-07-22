import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-identity-cutover"


class ArgusIdentityCutoverTests(unittest.TestCase):
    def test_cutover_is_executable_and_explicitly_acknowledged(self) -> None:
        text = SCRIPT.read_text()
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertIn("--acknowledge-argus-identity-cutover", text)
        self.assertIn('readonly OLD_ROOT="/srv/oreo-cloud"', text)
        self.assertIn('readonly NEW_ROOT="/srv/argus"', text)

    def test_cutover_preserves_exposure_and_compose_identity(self) -> None:
        text = SCRIPT.read_text()
        self.assertIn("publicExposureChanged=false", text)
        self.assertIn("composeProjectsChanged=false", text)
        self.assertNotIn("tailscale funnel", text.lower())
        self.assertNotIn("cloudflared tunnel run", text.lower())

    def test_cutover_validates_caddy_before_reload(self) -> None:
        text = SCRIPT.read_text()
        validate_at = text.index("caddy validate")
        reload_at = text.index("systemctl reload caddy")
        self.assertLess(validate_at, reload_at)

    def test_cutover_can_resume_after_the_root_move(self) -> None:
        text = SCRIPT.read_text()
        self.assertIn("RESUMING_ARGUS_IDENTITY_CUTOVER", text)
        self.assertIn('[[ -d "$NEW_ROOT/.git" && ! -e "$OLD_ROOT" ]]', text)
        self.assertIn('if systemctl is-active --quiet caddy; then', text)


if __name__ == "__main__":
    unittest.main()
