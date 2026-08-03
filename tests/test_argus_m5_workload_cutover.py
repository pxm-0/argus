import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-m5-workload-cutover"
loader = importlib.machinery.SourceFileLoader(
    "argus_m5_workload_cutover", str(SCRIPT)
)
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class WorkloadCutoverTests(unittest.TestCase):
    def test_reviewed_domain_and_tailnet_mapping(self) -> None:
        self.assertEqual("personal-sandbox", module.SPECS["hastur"]["domain"])
        self.assertEqual("personal-sandbox", module.SPECS["locigraph"]["domain"])
        self.assertEqual("work-sandbox", module.SPECS["intake-os"]["domain"])
        self.assertEqual(443, module.SPECS["locigraph"]["tail_port"])
        self.assertEqual(8443, module.SPECS["kadath"]["tail_port"])
        self.assertEqual(8444, module.SPECS["nodens"]["tail_port"])
        self.assertEqual(8445, module.SPECS["hastur"]["tail_port"])
        self.assertEqual(8446, module.SPECS["intake-os"]["tail_port"])

    def test_firewall_allows_only_sandbox_bridge_forwarding(self) -> None:
        networks = [
            {"project": "nodens", "network": "default", "networkId": "a" * 64, "interface": "br-aaaaaaaaaaaa"}
        ]
        rules = module.firewall_text("personal-sandbox", networks=networks)
        self.assertIn('iifname "br-aaaaaaaaaaaa" oifname "br-aaaaaaaaaaaa" accept', rules)
        self.assertNotIn("br-*", rules)
        self.assertIn("chain input", rules)
        self.assertIn("chain output", rules)
        self.assertGreaterEqual(rules.count("policy drop"), 3)
        self.assertNotIn("tap0", rules)

    def test_previous_proxy_is_scoped_to_selected_port(self) -> None:
        status = {
            "Web": {
                "host.example:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8090"}}
                },
                "host.example:8448": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:8088"}}
                },
            }
        }
        self.assertEqual(
            "http://127.0.0.1:8090", module.previous_proxy(status, 443)
        )
        self.assertIsNone(module.previous_proxy(status, 8445))

    def test_restoring_an_already_absent_route_is_idempotent(self) -> None:
        original_status = module.serve_status
        original_run = module.run
        calls = []
        module.serve_status = lambda: {"Web": {}}
        module.run = lambda command, **_kwargs: calls.append(command)
        try:
            module.restore_private_route(8445, None)
        finally:
            module.serve_status = original_status
            module.run = original_run
        self.assertEqual([], calls)

    def test_reconcile_queues_on_the_shared_lock_and_cutover_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock"
            with open(path, "a+") as holder, open(path, "a+") as waiter:
                module.acquire_lock(holder)
                # Cutovers and rollbacks keep refusing instantly.
                with self.assertRaises(BlockingIOError):
                    module.acquire_lock(waiter)
                # Reconciles poll until the deadline instead of failing fast.
                sleeps = []
                original_sleep = module.time.sleep
                module.time.sleep = sleeps.append
                try:
                    with self.assertRaises(BlockingIOError):
                        module.acquire_lock(waiter, 1.0)
                finally:
                    module.time.sleep = original_sleep
                self.assertGreater(len(sleeps), 0)
            # Releasing the holder lets a queued reconcile through.
            with open(path, "a+") as waiter:
                module.acquire_lock(waiter, 1.0)

    def test_reconcile_lock_wait_stays_under_systemd_start_timeout(self) -> None:
        self.assertLess(module.RECONCILE_LOCK_WAIT_SECONDS, 90)

    def test_cutover_contract_has_no_public_exposure_commands(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("unix:/", script)
        self.assertIn('"publishedPorts": False', script)
        self.assertIn('"publicRoute": False', script)
        self.assertIn('"tailscale", "funnel", "status"', script)
        self.assertNotIn('"tailscale", "funnel", "--bg"', script)
        self.assertNotIn("cloudflared", script)
        self.assertNotIn("docker compose down -v", script)
        self.assertIn("stateful post-cutover rollback requires reviewed", script)
        self.assertIn("O_NOFOLLOW", script)
        self.assertIn("authority-committed", script)
        self.assertIn("sourceRestartPolicies", script)
        self.assertIn("require_target_absent", script)
        self.assertIn("verified_stage_compose", script)
        self.assertIn("install_persistence_unit", script)
        self.assertIn("--reconcile", script)
        self.assertIn("OnUnitInactiveSec=60s", script)
        self.assertIn("wait_target_socket", script)
        self.assertIn("rendered_firewall_rules", script)
        self.assertIn("cutover.recovered-before-acceptance", script)
        self.assertNotIn("shutil.rmtree", script)

    def test_all_stateful_writers_are_explicit(self) -> None:
        self.assertEqual(("hastur",), module.SPECS["hastur"]["writers"])
        self.assertEqual(("api", "web"), module.SPECS["kadath"]["writers"])
        self.assertEqual(
            ("backend", "caddy", "frontend", "worker"),
            module.SPECS["locigraph"]["writers"],
        )
        self.assertEqual(
            ("api", "local-proxy", "web"),
            module.SPECS["intake-os"]["writers"],
        )

    def test_cron_source_resurrection_detection_is_secret_safe_and_scoped(self) -> None:
        source = "/home/oreo/intake-os"
        crontab = """
        # docker compose up -d in /home/oreo/intake-os
        */5 * * * * cd /home/oreo/intake-os && /usr/bin/docker compose -f docker-compose.server.yml up -d
        @reboot cd /home/oreo/intake-os && docker-compose start
        */5 * * * * cd /home/oreo/other && docker compose up -d
        0 1 * * * cd /home/oreo/intake-os && docker compose ps
        """
        self.assertEqual(
            2,
            module.cron_source_resurrection_count(source, crontab),
        )

    def test_plain_docker_exec_against_the_source_counts_as_resurrection(self) -> None:
        """Pins the exact orphan class that hid for ~13h after M5 cutover:
        a plain `docker exec` against the legacy container, no compose and
        no up/start/restart keyword, so the old check never counted it."""
        source = "/home/oreo/hastur"
        crontab = """
        0 */6 * * * cd /home/oreo/hastur && docker exec hastur pnpm run scrape
        0 1 * * * cd /home/oreo/other && docker exec other pnpm run scrape
        0 2 * * * cd /home/oreo/hastur && echo docker-exec-typo not a real command
        """
        self.assertEqual(
            1,
            module.cron_source_resurrection_count(source, crontab),
        )

    def test_crontab_inspection_exit_one_fails_closed_unless_explicitly_empty(self) -> None:
        original_run = module.run
        with tempfile.TemporaryDirectory() as source:
            spec = {"source": source}
            try:
                module.run = lambda command, **kwargs: subprocess.CompletedProcess(
                    command,
                    1,
                    b"",
                    b"permission denied",
                )
                with self.assertRaisesRegex(
                    module.CutoverError,
                    "could not be inspected safely",
                ):
                    module.scheduled_source_resurrections(spec)

                module.run = lambda command, **kwargs: subprocess.CompletedProcess(
                    command,
                    1,
                    b"",
                    b"no crontab for operator",
                )
                self.assertEqual(0, module.scheduled_source_resurrections(spec))
            finally:
                module.run = original_run

    def test_runtime_socket_path_fits_linux_sun_path(self) -> None:
        for workload, workload_spec in module.SPECS.items():
            stage_id = f"{workload}-20260729t123700z-d13f99e7"
            socket_path = (
                module.runtime_directory(workload, workload_spec, stage_id)
                / "ingress"
                / "upstream.sock"
            )
            self.assertLess(
                len(module.os.fsencode(socket_path)),
                module.UNIX_SOCKET_PATH_LIMIT,
            )

    def test_build_and_reconcile_share_runtime_directory_derivation(self) -> None:
        script = SCRIPT.read_text()
        self.assertEqual(2, script.count("runtime_directory(") - 1)
        expected = (
            module.RUNTIME_ROOT
            / "personal-sandbox"
            / "nodens"
            / module.hashlib.sha256(b"stage-id").hexdigest()[:16]
        )
        self.assertEqual(
            expected,
            module.runtime_directory(
                "nodens", module.SPECS["nodens"], "stage-id"
            ),
        )

    def test_source_recovery_starts_existing_dependencies_before_writers(self) -> None:
        original_records = module.source_container_records
        original_run = module.run
        original_wait_dependencies = module.wait_source_containers_ready
        original_wait_source = module.wait_source_ready
        calls = []
        module.source_container_records = lambda _spec: [
            {
                "name": "project-api-1",
                "service": "api",
                "state": {"Status": "exited"},
            },
            {
                "name": "project-postgres-1",
                "service": "postgres",
                "state": {"Status": "exited"},
            },
        ]
        module.run = lambda command, **_kwargs: calls.append(command)
        module.wait_source_containers_ready = (
            lambda names: calls.append(["wait-dependencies", *names])
        )
        module.wait_source_ready = (
            lambda workload: calls.append(["wait-source", workload])
        )
        try:
            spec = {**module.SPECS["kadath"], "writers": ("api",)}
            module.source_up("kadath", spec)
        finally:
            module.source_container_records = original_records
            module.run = original_run
            module.wait_source_containers_ready = original_wait_dependencies
            module.wait_source_ready = original_wait_source
        self.assertEqual(
            [
                ["docker", "start", "project-postgres-1"],
                ["wait-dependencies", "project-postgres-1"],
                ["docker", "start", "project-api-1"],
                ["wait-source", "kadath"],
            ],
            calls,
        )

    def test_source_recovery_accepts_already_running_dependencies(self) -> None:
        original_records = module.source_container_records
        original_run = module.run
        original_wait_dependencies = module.wait_source_containers_ready
        original_wait_source = module.wait_source_ready
        calls = []
        module.source_container_records = lambda _spec: [
            {
                "name": "project-api-1",
                "service": "api",
                "state": {"Status": "exited"},
            },
            {
                "name": "project-postgres-1",
                "service": "postgres",
                "state": {"Status": "running"},
            },
        ]
        module.run = lambda command, **_kwargs: calls.append(command)
        module.wait_source_containers_ready = (
            lambda names: calls.append(["wait-dependencies", *names])
        )
        module.wait_source_ready = (
            lambda workload: calls.append(["wait-source", workload])
        )
        try:
            spec = {**module.SPECS["kadath"], "writers": ("api",)}
            module.source_up("kadath", spec)
        finally:
            module.source_container_records = original_records
            module.run = original_run
            module.wait_source_containers_ready = original_wait_dependencies
            module.wait_source_ready = original_wait_source
        self.assertEqual(
            [
                ["wait-dependencies", "project-postgres-1"],
                ["docker", "start", "project-api-1"],
                ["wait-source", "kadath"],
            ],
            calls,
        )


class CredentialDeliveryTest(unittest.TestCase):
    def test_hastur_gets_sealed_credentials_and_internal_schedule(self) -> None:
        spec = module.SPECS["hastur"]
        self.assertEqual({"hastur": "/app/auth"}, spec["credentials"])
        self.assertEqual(
            {
                "CRAWL_SCHEDULE_ENABLED": "true",
                "CRAWL_SCHEDULE_MECHANISM": "internal",
            },
            spec["extra_environment"]["hastur"],
        )
        self.assertEqual(
            Path("/etc/argus/workload-credentials"), module.CREDENTIAL_ROOT
        )
        self.assertNotIn("/home/oreo", str(module.CREDENTIAL_ROOT))

    def test_credential_directory_must_be_root_owned_and_group_readable(self) -> None:
        original_root = module.CREDENTIAL_ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module.CREDENTIAL_ROOT = root
            try:
                with self.assertRaises(FileNotFoundError):
                    module.credential_source(
                        "hastur", module.SPECS["hastur"], module.os.getgid()
                    )
                source = root / "hastur"
                source.mkdir(mode=0o750)
                credential = source / "threads-storage.json"
                credential.write_text("{}")
                module.os.chmod(credential, 0o640)
                # Owned by the invoking user rather than root: rejected.
                with self.assertRaises(module.CutoverError):
                    module.credential_source(
                        "hastur", module.SPECS["hastur"], module.os.getgid()
                    )
                # Wrong sandbox group: rejected.
                with self.assertRaises(module.CutoverError):
                    module.credential_source(
                        "hastur", module.SPECS["hastur"], module.os.getgid() + 1
                    )
            finally:
                module.CREDENTIAL_ROOT = original_root


class DeclaredEgressTest(unittest.TestCase):
    SEALED_POLICY = (
        "destroy table inet argus_personal_sandbox\n"
        "table inet argus_personal_sandbox {\n"
        "  chain input { type filter hook input priority filter; policy drop; "
        'iifname "lo" accept; }\n'
        "  chain forward {\n"
        "    type filter hook forward priority filter; policy drop;\n"
        "  }\n"
        "  chain output { type filter hook output priority filter; policy drop; "
        'oifname "lo" accept; }\n'
        "}\n"
        "destroy table inet argus_personal_sandbox_nat\n"
    )
    NETWORKS = [
        {"project": "hastur", "network": "default", "networkId": "a" * 64, "interface": "argus-hastur"},
        {"project": "kadath-live", "network": "default", "networkId": "b" * 64, "interface": "br-bbbbbbbbbbbb"},
        {"project": "locigraph", "network": "default", "networkId": "c" * 64, "interface": "br-cccccccccccc"},
        {"project": "nodens", "network": "default", "networkId": "d" * 64, "interface": "br-dddddddddddd"},
    ]

    def test_every_workload_declares_an_egress_policy(self) -> None:
        for workload, spec in module.SPECS.items():
            self.assertIn("egress", spec, workload)

    def test_only_hastur_is_granted_egress(self) -> None:
        self.assertEqual(
            ["hastur"], sorted(module.domain_egress("personal-sandbox"))
        )
        self.assertEqual({}, module.domain_egress("work-sandbox"))
        for workload in ("kadath", "nodens", "locigraph", "intake-os"):
            self.assertIsNone(
                module.validated_egress(workload, module.SPECS[workload]),
                workload,
            )

    def test_hastur_is_granted_dns_and_tls_only(self) -> None:
        policy = module.validated_egress("hastur", module.SPECS["hastur"])
        self.assertEqual((("tcp", 443),), policy["allow"])
        self.assertEqual("10.0.2.3", policy["resolver"])

    def test_granted_domain_still_seals_every_other_workload(self) -> None:
        rendered = module.firewall_text(
            "personal-sandbox", module.domain_egress("personal-sandbox"), self.NETWORKS
        )
        for workload in ("kadath", "nodens", "locigraph"):
            self.assertNotIn(module.sandbox_bridge(workload), rendered)

    def test_sealed_rendering_is_byte_identical_to_the_installed_policy(self) -> None:
        self.assertEqual(
            self.SEALED_POLICY, module.firewall_text("personal-sandbox")
        )
        self.assertEqual(
            self.SEALED_POLICY.replace("personal_sandbox", "work_sandbox"),
            module.firewall_text(
                "work-sandbox", module.domain_egress("work-sandbox")
            ),
        )

    def test_a_declared_policy_renders_scoped_rules_and_masquerade(self) -> None:
        policies = {
            "hastur": {
                "resolver": "10.0.2.3",
                "allow": (("tcp", 443),),
                "reason": "threads.net crawl",
            }
        }
        rendered = module.firewall_text("personal-sandbox", policies, self.NETWORKS)
        self.assertIn(
            'iifname "argus-hastur" oifname "tap0" tcp dport 443 '
            "ct state new,established accept;",
            rendered,
        )
        self.assertIn(
            'iifname "argus-hastur" oifname "tap0" ip daddr 10.0.2.3 '
            "udp dport 53 ct state new,established accept;",
            rendered,
        )
        self.assertIn(
            'iifname "tap0" oifname "argus-hastur" '
            "ct state established,related accept;",
            rendered,
        )
        self.assertIn("table inet argus_personal_sandbox_nat {", rendered)
        self.assertIn(
            'iifname "argus-hastur" oifname "tap0" masquerade;', rendered
        )
        self.assertNotIn("argus-kadath", rendered)
        self.assertNotIn("argus-nodens", rendered)

    def test_sealed_domains_render_no_nat_table(self) -> None:
        rendered = module.firewall_text("work-sandbox", module.domain_egress("work-sandbox"))
        self.assertIn("destroy table inet argus_work_sandbox_nat", rendered)
        self.assertNotIn("table inet argus_work_sandbox_nat {", rendered)

    def test_incomplete_policies_are_refused(self) -> None:
        for policy in (
            {"allow": (("tcp", 443),), "reason": "no resolver"},
            {"resolver": "10.0.2.3", "reason": "no allowance"},
            {"resolver": "10.0.2.3", "allow": (("tcp", 443),)},
            {"resolver": "10.0.2.3", "allow": (("sctp", 443),), "reason": "bad proto"},
            {"resolver": "10.0.2.3", "allow": (("tcp", 0),), "reason": "bad port"},
        ):
            with self.assertRaises(module.CutoverError):
                module.validated_egress("hastur", {"egress": policy})

    def test_a_missing_declaration_is_refused(self) -> None:
        with self.assertRaises(module.CutoverError):
            module.validated_egress("hastur", {})

    def test_policy_changes_need_an_acknowledged_apply(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("--acknowledge-m5-egress-policy", script)
        self.assertIn("refusing egress policy change", script)
        # Reconcile reports drift; it must not install policy on a timer.
        reconcile_body = script[script.index("def reconcile("):script.index("def egress_policy_drift(")]
        self.assertNotIn("install_internal_firewall", reconcile_body)
        self.assertIn("egressPolicyDrift", reconcile_body)


class RuntimeRefreshTest(unittest.TestCase):
    """A stateful cutover is one-way, so spec drift after acceptance needs a
    fenced way in. Hastur proved the gap: sealed credentials, the schedule
    overlay, and a declared egress policy all landed after it was cut over,
    and no action could deliver any of them."""

    CREDENTIAL_DIR = Path("/etc/argus/workload-credentials/hastur")
    ACCEPTED = {
        "services": {
            "hastur": {
                "image": "sha256:aaaa",
                "environment": {"CRAWL_MAX_RUNTIME_MS": "10800000"},
                "restart": "no",
                "volumes": [
                    {
                        "type": "volume",
                        "source": "argus_stage_hastur__app_data",
                        "target": "/app/data",
                    }
                ],
            },
            "argus-ingress": {
                "image": "sha256:bbbb",
                "environment": {},
                "restart": "no",
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/var/lib/argus/x/ingress.json",
                        "target": "/etc/caddy/ingress.json",
                        "read_only": True,
                    }
                ],
            },
        }
    }

    def granted_spec(self) -> dict:
        return {
            **module.SPECS["hastur"],
            "egress": {
                "resolver": "10.0.2.3",
                "allow": (("tcp", 443),),
                "reason": "threads.net crawl",
            },
        }

    def test_overlay_delivers_what_hastur_was_missing(self) -> None:
        updated = module.refresh_overlay(
            self.ACCEPTED, "hastur", self.granted_spec(), self.CREDENTIAL_DIR
        )
        service = updated["services"]["hastur"]
        # The schedule overlay, absent from the running container.
        self.assertEqual("true", service["environment"]["CRAWL_SCHEDULE_ENABLED"])
        self.assertEqual(
            "internal", service["environment"]["CRAWL_SCHEDULE_MECHANISM"]
        )
        # Captured runtime environment is preserved, not replaced.
        self.assertEqual(
            "10800000", service["environment"]["CRAWL_MAX_RUNTIME_MS"]
        )
        # The sealed credential bind, which had no mount at all.
        self.assertIn(
            {
                "type": "bind",
                "source": str(self.CREDENTIAL_DIR),
                "target": "/app/auth",
                "read_only": True,
            },
            service["volumes"],
        )
        # Workload state must survive the recreate.
        self.assertIn(
            {
                "type": "volume",
                "source": "argus_stage_hastur__app_data",
                "target": "/app/data",
            },
            service["volumes"],
        )
        # The bridge a declared rule can name.
        self.assertEqual(
            "argus-hastur",
            updated["networks"]["default"]["driver_opts"][
                "com.docker.network.bridge.name"
            ],
        )
        # #289: a target staged before that fix landed keeps internal=True
        # forever unless refresh also clears it -- an internal network has
        # no default route, so the nft allow rules are unreachable no
        # matter how correct they are. Confirmed live 2026-07-31: hastur's
        # own refresh renamed the bridge but left it with EAI_AGAIN until
        # this assertion's fix landed.
        self.assertFalse(updated["networks"]["default"]["internal"])

    def test_overlay_is_idempotent(self) -> None:
        spec = self.granted_spec()
        once = module.refresh_overlay(
            self.ACCEPTED, "hastur", spec, self.CREDENTIAL_DIR
        )
        twice = module.refresh_overlay(
            once, "hastur", spec, self.CREDENTIAL_DIR
        )
        self.assertEqual(once, twice)
        binds = [
            volume
            for volume in twice["services"]["hastur"]["volumes"]
            if volume.get("target") == "/app/auth"
        ]
        self.assertEqual(1, len(binds), "credential bind must not stack")

    def test_overlay_does_not_mutate_the_accepted_compose(self) -> None:
        before = json.dumps(self.ACCEPTED, sort_keys=True)
        module.refresh_overlay(
            self.ACCEPTED, "hastur", self.granted_spec(), self.CREDENTIAL_DIR
        )
        self.assertEqual(before, json.dumps(self.ACCEPTED, sort_keys=True))

    def test_a_sealed_workload_gets_a_stable_bridge_pin(self) -> None:
        # Exact project isolation must remain stable even when Docker recreates
        # a sealed workload's network with a different immutable NetworkID.
        self.assertIsNone(module.SPECS["kadath"]["egress"])
        updated = module.refresh_overlay(
            self.ACCEPTED, "kadath", module.SPECS["kadath"], None
        )
        self.assertEqual(
            "argus-kadath",
            updated["networks"]["default"]["driver_opts"][
                "com.docker.network.bridge.name"
            ],
        )

    def test_overlay_refuses_to_name_unknown_services(self) -> None:
        spec = {**module.SPECS["hastur"], "credentials": {"absent": "/app/auth"}}
        with self.assertRaises(module.CutoverError):
            module.refresh_overlay(
                self.ACCEPTED, "hastur", spec, self.CREDENTIAL_DIR
            )

    def test_refresh_never_destroys_named_volumes(self) -> None:
        script = SCRIPT.read_text()
        body = script[script.index("def refresh(") : script.index("def reconcile(")]
        self.assertIn('"down"', body)
        # -v would delete argus_stage_<workload>__* and the workload's state.
        self.assertNotIn('"-v"', body)
        self.assertNotIn('"--volumes"', body)

    def test_refresh_is_acknowledged_and_reuses_the_shared_validator(self) -> None:
        script = SCRIPT.read_text()
        self.assertIn("--acknowledge-m5-workload-refresh", script)
        self.assertIn("refusing runtime refresh", script)
        # reconcile and refresh must not drift apart on the fence checks.
        self.assertEqual(2, script.count("= accepted_cutover_state("))

    def test_recovery_restores_root_ownership_before_preparing(self) -> None:
        """Regression: hastur stayed down because recovery called
        prepare_ingress_start on an already-prepared directory. That raised
        "locked ingress directory ownership is unsafe" and replaced the real
        failure, so up -d never ran and the cause was lost."""
        events = []
        originals = (
            module.run,
            module.os.replace,
            module.os.chown,
            module.prepare_ingress_start,
        )
        module.run = lambda command, **_kwargs: events.append(command[-2:])
        module.os.replace = lambda *_args: events.append(["replace"])
        module.os.chown = lambda _path, uid, gid: events.append(
            ["chown", uid, gid]
        )

        def prepare(_spec, _socket):
            # Fails unless ownership was restored to root immediately before.
            if ["chown", 0, 0] not in events:
                raise module.CutoverError(
                    "locked ingress directory ownership is unsafe"
                )
            events.append(["prepare"])

        module.prepare_ingress_start = prepare
        try:
            module.restore_accepted_runtime(
                module.SPECS["hastur"],
                Path("/x/docker-compose.json"),
                Path("/x/docker-compose.json.before"),
                Path("/x/ingress/upstream.sock"),
            )
        finally:
            (
                module.run,
                module.os.replace,
                module.os.chown,
                module.prepare_ingress_start,
            ) = originals

        self.assertEqual(["replace"], events[0])
        self.assertLess(
            events.index(["chown", 0, 0]),
            events.index(["prepare"]),
            "ownership must be restored before preparing",
        )
        # The known-good project must actually be started again.
        self.assertEqual(["up", "-d"], events[-1])

    def test_refresh_recovery_cannot_mask_the_original_failure(self) -> None:
        script = SCRIPT.read_text()
        body = script[script.index("def refresh(") : script.index("def reconcile(")]
        recovery = body[
            body.index("except BaseException:") : body.index("    state.update(")
        ]
        # Recovery is guarded, so a failure inside it cannot replace the error
        # that triggered it.
        self.assertIn("restore_accepted_runtime(", recovery)
        self.assertIn("except Exception as recovery_error", recovery)
        self.assertIn("recovery incomplete", recovery)
        self.assertTrue(recovery.rstrip().endswith("raise"))
        # The bug was calling this directly in the handler.
        self.assertNotIn("prepare_ingress_start(", recovery)

    def test_refresh_keeps_the_source_fenced_on_failure(self) -> None:
        script = SCRIPT.read_text()
        region = script[
            script.index("def restore_accepted_runtime(") : script.index(
                "def reconcile("
            )
        ]
        # Recovery restores the accepted Compose...
        self.assertIn("os.replace(before, runtime_compose)", region)
        # ...and never starts the legacy source, whose data is now stale.
        self.assertNotIn("source_up(", region)
        self.assertNotIn("restore_source_restart(", region)
        self.assertNotIn("fence_source_restart(", region)


if __name__ == "__main__":
    unittest.main()
