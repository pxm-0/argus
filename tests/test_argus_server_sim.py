from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "infra" / "server-sim"
sys.path.insert(0, str(ROOT / "scripts"))

from argus_tailscale import funnel_disabled  # noqa: E402


def stub(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SIM / "tailscale-stub"), *args], text=True, capture_output=True, check=False
    )


class TailscaleStubTests(unittest.TestCase):
    def test_funnel_and_serve_status_pass_the_fail_closed_validator(self) -> None:
        for args in (("funnel", "status"), ("serve", "status")):
            result = stub(*args)
            self.assertEqual(0, result.returncode)
            self.assertTrue(funnel_disabled(result.stdout))

    def test_unknown_calls_fail_instead_of_pretending(self) -> None:
        self.assertEqual(1, stub("funnel", "443", "on").returncode)
        self.assertEqual(0, stub("serve", "--bg", "8448", "http://127.0.0.1:8088").returncode)


class SimLanExposureTests(unittest.TestCase):
    def run_sim(self, config: str, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "orbctl"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                'case "$1 ${2:-}" in\n'
                f"  'config show') printf '%s\\n' '{config}' ;;\n"
                "  'list -q') ;;\n"
                "  'list ') printf 'NAME STATE\\n' ;;\n"
                "  *) echo \"unexpected orbctl $*\" >&2; exit 99 ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}"}
            return subprocess.run(
                ["bash", str(SIM / "sim"), *args], text=True, capture_output=True, env=env, check=False
            )

    def test_refuses_when_ports_reach_the_lan(self) -> None:
        result = self.run_sim("machines.expose_ports_to_lan: true\ndocker.expose_ports_to_lan: false", "up", "--yes")
        self.assertEqual(3, result.returncode)
        self.assertIn("orbctl config set machines.expose_ports_to_lan false", result.stderr)

    def test_create_needs_explicit_yes(self) -> None:
        result = self.run_sim("machines.expose_ports_to_lan: false\ndocker.expose_ports_to_lan: false", "up")
        self.assertEqual(2, result.returncode)
        self.assertIn("PLAN  orbctl create --arch amd64 --isolated", result.stdout)


if __name__ == "__main__":
    unittest.main()
