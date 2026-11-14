from __future__ import annotations

import json
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

    def test_json_status_is_an_empty_serve_config(self) -> None:
        for args in (("serve", "status", "--json"), ("funnel", "status", "--json")):
            result = stub(*args)
            self.assertEqual(0, result.returncode)
            self.assertEqual({}, json.loads(result.stdout))

    def test_serve_off_is_a_no_op(self) -> None:
        self.assertEqual(0, stub("serve", "--yes", "--https=8448", "off").returncode)


class ProvisionStepOrderTests(unittest.TestCase):
    def test_phase_b_follows_the_server_provisioning_order(self) -> None:
        result = subprocess.run(
            ["bash", str(SIM / "provision"), "--help"], text=True, capture_output=True, check=False
        )
        self.assertEqual(0, result.returncode)
        self.assertIn(
            "sysusers secrets dashboard ledger-worker capability-issuer sandbox caddy "
            "session-boundary control-plane-reconcile units collectors workloads",
            result.stdout,
        )


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
        # OrbStack's own default user must not take the name oreo, so cloud-init can give oreo UID 1000.
        self.assertIn("--user simadmin", result.stdout)


class SimPhaseBTests(unittest.TestCase):
    def test_phase_b_runs_the_pushed_provisioner_not_the_checkout_copy(self) -> None:
        # --ref may name a tree without infra/server-sim (e.g. the wave2 branch), so phase B
        # must run the provisioner that sim pushed into the machine's home directory.
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls"
            fake = Path(directory) / "orbctl"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f"echo \"$*\" >> '{log}'\n"
                'case "$*" in\n'
                "  'config show') printf 'machines.expose_ports_to_lan: false\\ndocker.expose_ports_to_lan: false\\n' ;;\n"
                "  'list -q') printf 'oreochiserver-sim\\n' ;;\n"
                "  *'printf %s \"$HOME\"'*) printf /home/simadmin ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}"}
            result = subprocess.run(
                ["bash", str(SIM / "sim"), "phase-b", "--from", "workloads"],
                text=True, capture_output=True, env=env, check=False,
            )
            calls = log.read_text()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("bash /home/simadmin/provision phase-b --from workloads", calls)
        self.assertNotIn("/srv/argus/infra/server-sim/provision", calls)


if __name__ == "__main__":
    unittest.main()
