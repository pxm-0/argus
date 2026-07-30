from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_m4_bootstrap import (  # noqa: E402
    BootstrapError,
    personal_sandbox_contract,
    sandbox_contract,
)


class M4BootstrapTest(unittest.TestCase):
    def test_contract_is_dedicated_and_sealed(self) -> None:
        contract = personal_sandbox_contract(user="argus-personal-sandbox")
        self.assertEqual("personal-sandbox", contract["domain"])
        self.assertIn("no-published-ports", contract["prohibitions"])
        self.assertTrue(contract["contractDigest"].startswith("sha256:"))
        with self.assertRaises(BootstrapError):
            personal_sandbox_contract(user="argus-pilot")

    def test_bootstrap_never_deploys_a_workload_or_opens_a_route(self) -> None:
        script = (ROOT / "scripts" / "argus-m4-personal-sandbox-bootstrap").read_text(encoding="utf-8")
        self.assertIn("--acknowledge-personal-sandbox-cell", script)
        self.assertIn("policy drop", script)
        self.assertNotIn("flush ruleset", script)
        self.assertIn("destroy table inet $NFT_TABLE", script)
        self.assertIn("DOCKERD_ROOTLESS_ROOTLESSKIT_NET=slirp4netns", script)
        self.assertIn("DOCKERD_ROOTLESS_ROOTLESSKIT_PORT_DRIVER=none", script)
        self.assertIn('FIREWALL_UNIT="argus-${CELL_DOMAIN}-firewall.service"', script)
        self.assertIn("WantedBy=multi-user.target", script)
        self.assertIn('nsenter -t "\\$rootless_child_pid" -n nft -f', script)
        self.assertIn("--iptables=false", script)
        self.assertIn("Delegate=yes", script)
        self.assertIn("TasksMax=infinity", script)
        self.assertIn("systemctl --user", script)
        self.assertIn("daemon_was_active", script)
        self.assertIn('if [[ "$daemon_was_active" != true ]]', script)
        self.assertIn("trap rollback_on_exit EXIT", script)
        self.assertIn("--acknowledge-sandbox-rollback", script)
        self.assertIn(
            'restore_subid_entry /etc/subuid "$backup_dir/etc/subuid"',
            script,
        )
        self.assertIn(
            "preserved = [line for line in current_lines if not line.startswith(prefix)]",
            script,
        )
        self.assertIn(
            "$subid_file must be a readable root-owned regular file",
            script,
        )
        self.assertLess(
            script.index("for subid_file in /etc/subuid /etc/subgid"),
            script.index('useradd --create-home --shell /usr/sbin/nologin "$CELL_USER"'),
        )
        self.assertIn("HOST_GUARD_TABLE", script)
        self.assertIn('Before=user@$(id -u "$CELL_USER").service', script)
        self.assertIn("meta skuid", script)
        self.assertNotIn('systemctl disable --now "$DAEMON_UNIT"', script)
        apply_section = script.rsplit("write_rollback_state\n", 1)[1]
        self.assertLess(
            apply_section.index('nft list table inet "$HOST_GUARD_TABLE"'),
            apply_section.index('loginctl enable-linger "$CELL_USER"'),
        )
        self.assertIn("validate_user_subid_range", script)
        self.assertIn("capture_inventory_digest", script)
        self.assertLess(
            script.index('inventory_digest_before="$(capture_inventory_digest)"'),
            script.index('useradd --create-home --shell /usr/sbin/nologin "$CELL_USER"'),
        )
        self.assertIn("sandbox workload or volume inventory changed", script)
        self.assertIn("rollback capability issuer/domain agent first", script)
        self.assertIn("sandbox identity must own a unique numeric UID", script)
        self.assertIn("--exec-opt native.cgroupdriver=systemd", script)
        self.assertIn("workloadsDeployed", script)
        self.assertNotIn("docker compose", script)

    def test_apply_proves_the_daemon_can_actually_create_a_container(self) -> None:
        """A 2026-07-30 outage left the daemon systemd-"active" but unable to
        create a container (EOVERFLOW on containerd-mount). is-active alone
        does not catch that; apply must run a real container before success."""
        script = (ROOT / "scripts" / "argus-m4-personal-sandbox-bootstrap").read_text()
        self.assertIn("run --rm hello-world", script)
        # A bare `docker run hello-world` pulls from Docker Hub, which the
        # sandbox's default-deny egress cannot reach — confirmed live on
        # oreochiserver as a false-positive rollback. The image must be
        # vendored and loaded locally instead.
        self.assertIn("load -i", script)
        self.assertIn("fixtures/argus-hello-world-amd64.tar", script)
        fixture = ROOT / "scripts" / "fixtures" / "argus-hello-world-amd64.tar"
        self.assertTrue(fixture.exists())
        # is-active only proves the process started, not that the socket
        # exists yet -- a fresh docker-data is slower to initialize than an
        # existing one (confirmed live rebuilding personal-sandbox 2026-07-31).
        self.assertIn("sandbox docker socket never appeared", script)
        self.assertLess(
            script.index('user_systemctl is-active --quiet "$DAEMON_UNIT"'),
            script.index("sandbox docker socket never appeared"),
        )
        self.assertLess(
            script.index("sandbox docker socket never appeared"),
            script.index("load -i"),
        )
        self.assertLess(
            script.index('user_systemctl is-active --quiet "$DAEMON_UNIT"'),
            script.index("load -i"),
        )
        self.assertLess(
            script.index("load -i"),
            script.index("run --rm hello-world"),
        )
        self.assertLess(
            script.index("run --rm hello-world"),
            script.index('systemctl enable "$FIREWALL_UNIT"'),
        )
        self.assertIn(
            "refusing success: sandbox docker daemon is active but cannot run a container",
            script,
        )

    def test_rollback_restores_the_firewall_before_stopping_the_daemon(self) -> None:
        """#286: rollback used to stop a just-started daemon before restoring
        the firewall, stranding any firewall_was_active=true restore (the
        firewall's own start script waits for a live rootlesskit child). This
        is exactly the state the documented rebuild runbook produces -- stop
        and wipe the daemon by hand, leave the firewall running -- not a
        misuse edge case."""
        script = (ROOT / "scripts" / "argus-m4-personal-sandbox-bootstrap").read_text()
        rollback_body = script.split("\nrollback() {\n", 1)[1].split("\nrollback_on_exit() {\n", 1)[0]
        self.assertLess(
            rollback_body.index('if [[ "$firewall_was_active" == true ]]'),
            rollback_body.index('if [[ -n "$CELL_RUNTIME" && -S "$CELL_RUNTIME/bus" ]]'),
        )
        self.assertLess(
            rollback_body.index('if [[ -n "$CELL_RUNTIME" && -S "$CELL_RUNTIME/bus" ]]'),
            rollback_body.index('if [[ "$failed" == true ]]'),
        )

    def test_work_sandbox_uses_an_independent_sealed_contract(self) -> None:
        contract = sandbox_contract(
            domain="work-sandbox",
            user="argus-work-sandbox",
        )
        self.assertEqual("work-sandbox", contract["domain"])
        self.assertIn("no-cross-domain-route", contract["prohibitions"])
        with self.assertRaises(BootstrapError):
            sandbox_contract(
                domain="work-sandbox",
                user="argus-personal-sandbox",
            )

        wrapper = (ROOT / "scripts" / "argus-m5-sandbox-bootstrap").read_text()
        self.assertIn("personal-sandbox", wrapper)
        self.assertIn("work-sandbox", wrapper)
        self.assertIn("--acknowledge-sandbox-cell", wrapper)
