from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-m5-rootless-gid-repair"
loader = importlib.machinery.SourceFileLoader(
    "argus_m5_rootless_gid_repair", str(SCRIPT)
)
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class RootlessGidRepairTest(unittest.TestCase):
    def test_target_command_is_scoped_to_one_sandbox_socket(self) -> None:
        self.assertTrue(SCRIPT.stat().st_mode & stat.S_IXUSR)
        self.assertEqual(
            [
                "runuser",
                "-u",
                "argus-personal-sandbox",
                "--",
                "env",
                "HOME=/home/argus-personal-sandbox",
                "docker",
                "--host",
                "unix:///var/lib/argus/personal-sandbox/docker.sock",
                "ps",
            ],
            module.target_command("personal-sandbox", "ps"),
        )

    def test_plan_is_read_only_and_apply_requires_exact_acknowledgement(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        plan_branch = source.split("if arguments.plan:", 1)[1].split(
            "\n    else:", 1
        )[0]
        self.assertIn("public_plan", plan_branch)
        self.assertNotIn("acquire_lock", plan_branch)
        self.assertNotIn("write_", plan_branch)
        self.assertIn(module.APPLY_ACK, source)
        self.assertIn(module.ROLLBACK_ACK, source)

    def test_stale_gid_must_not_be_root_current_or_subordinate(self) -> None:
        with self.assertRaises(module.RepairError):
            module.validate_stale_gid(0, 1002, ((231072, 65536),))
        with self.assertRaises(module.RepairError):
            module.validate_stale_gid(1002, 1002, ((231072, 65536),))
        with self.assertRaises(module.RepairError):
            module.validate_stale_gid(232070, 1002, ((231072, 65536),))
        module.validate_stale_gid(981, 1002, ((231072, 65536),))

    def test_always_restart_policy_is_rejected_before_quiescence(self) -> None:
        original = module.restart_policies
        module.restart_policies = lambda *_args: {
            "safe": "no",
            "unsafe": "always",
        }
        try:
            with self.assertRaisesRegex(
                module.RepairError, "restart policy could bypass"
            ):
                module.require_restart_suppression(
                    "personal-sandbox", {"safe", "unsafe"}
                )
        finally:
            module.restart_policies = original

    def test_runtime_probe_records_only_sanitized_state(self) -> None:
        recorded = []
        original_active = module.daemon_is_active
        original_probe = module.probe_daemon
        original_write = module.write_probe_result
        module.daemon_is_active = lambda _domain: True
        module.probe_daemon = lambda _domain: None
        module.write_probe_result = lambda domain, result: recorded.append(
            (domain, result)
        )
        try:
            result = module.runtime_probe("personal-sandbox")
        finally:
            module.daemon_is_active = original_active
            module.probe_daemon = original_probe
            module.write_probe_result = original_write
        self.assertTrue(result["ok"])
        self.assertEqual("passed", result["reason"])
        self.assertEqual(
            {
                "schemaVersion",
                "domain",
                "daemonActive",
                "containerCreation",
                "ok",
                "generatedAt",
                "reason",
            },
            set(recorded[0][1]),
        )

    def test_scheduled_probe_requires_root_controlled_code_and_fixture(self) -> None:
        original_lstat = module.os.lstat
        module.os.lstat = lambda _path: SimpleNamespace(
            st_uid=1000,
            st_mode=stat.S_IFREG | 0o755,
        )
        try:
            with self.assertRaisesRegex(
                module.RepairError, "not root-controlled"
            ):
                module.require_installed_probe_boundary()
        finally:
            module.os.lstat = original_lstat

    def test_selection_requires_the_exact_sandbox_uid(self) -> None:
        original = module.iter_entries
        root = Path("/var/lib/argus/personal-sandbox/docker-data")
        module.iter_entries = lambda _root: iter(
            (
                (os.fsencode(root), SimpleNamespace(st_uid=1002, st_gid=981)),
                (
                    os.fsencode(root / "safe"),
                    SimpleNamespace(st_uid=1002, st_gid=981),
                ),
                (
                    os.fsencode(root / "foreign"),
                    SimpleNamespace(st_uid=1003, st_gid=981),
                ),
                (
                    os.fsencode(root / "subordinate"),
                    SimpleNamespace(st_uid=232070, st_gid=232070),
                ),
            )
        )
        try:
            selected, foreign, total = module.selected_entries(root, 1002, 981)
        finally:
            module.iter_entries = original
        self.assertEqual([b".", b"safe"], selected)
        self.assertEqual(1, foreign)
        self.assertEqual(4, total)

    def test_manifest_round_trip_is_checksum_bound_and_private(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            manifest, digest = module.write_manifest(
                root, [b".", b"containers/id/config.v2.json", b"odd\nname"]
            )
            self.assertEqual(0o600, manifest.stat().st_mode & 0o777)
            original_lstat = module.os.lstat

            def root_lstat(path):
                metadata = original_lstat(path)
                return SimpleNamespace(
                    st_uid=0,
                    st_mode=metadata.st_mode,
                )

            module.os.lstat = root_lstat
            try:
                entries = module.read_manifest(manifest, digest)
                with self.assertRaises(module.RepairError):
                    module.read_manifest(manifest, "0" * 64)
            finally:
                module.os.lstat = original_lstat
            self.assertEqual(
                [b".", b"containers/id/config.v2.json", b"odd\nname"],
                entries,
            )

    def test_change_preflights_every_path_before_mutation(self) -> None:
        paths = [b"/data/one", b"/data/two"]
        events = []
        original_lstat = module.os.lstat
        original_chown = module.os.chown
        module.os.lstat = lambda path: SimpleNamespace(
            st_uid=1002,
            st_gid=981 if path == paths[0] else 1002,
        )
        module.os.chown = lambda *args, **kwargs: events.append((args, kwargs))
        try:
            with self.assertRaises(module.RepairError):
                module.change_paths(paths, 1002, 981, 1002)
        finally:
            module.os.lstat = original_lstat
            module.os.chown = original_chown
        self.assertEqual([], events)

    def test_rollback_path_cannot_traverse_a_replaced_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory) / "root"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "child").write_text("unchanged", encoding="utf-8")
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(
                module.RepairError, "unsafe ancestor"
            ):
                module.validate_paths(
                    root,
                    [b"link/child"],
                    os.getuid(),
                    os.getgid(),
                )

    def test_change_preserves_uid_and_does_not_follow_symlinks(self) -> None:
        paths = [b"/data/one", b"/data/link"]
        gids = {path: 981 for path in paths}
        events = []
        original_lstat = module.os.lstat
        original_chown = module.os.chown

        def fake_lstat(path):
            return SimpleNamespace(st_uid=1002, st_gid=gids[path])

        def fake_chown(path, uid, gid, *, follow_symlinks):
            events.append((path, uid, gid, follow_symlinks))
            gids[path] = gid

        module.os.lstat = fake_lstat
        module.os.chown = fake_chown
        try:
            module.change_paths(paths, 1002, 981, 1002)
        finally:
            module.os.lstat = original_lstat
            module.os.chown = original_chown
        self.assertEqual(
            [
                (b"/data/one", -1, 1002, False),
                (b"/data/link", -1, 1002, False),
            ],
            events,
        )

    def test_change_compensates_prior_paths_after_mid_loop_failure(self) -> None:
        paths = [b"/data/one", b"/data/two"]
        gids = {path: 981 for path in paths}
        events = []
        original_lstat = module.os.lstat
        original_chown = module.os.chown

        def fake_lstat(path):
            return SimpleNamespace(st_uid=1002, st_gid=gids[path])

        def fake_chown(path, uid, gid, *, follow_symlinks):
            events.append((path, uid, gid, follow_symlinks))
            if path == paths[1] and gid == 1002:
                raise OSError("injected chown failure")
            gids[path] = gid

        module.os.lstat = fake_lstat
        module.os.chown = fake_chown
        try:
            with self.assertRaisesRegex(OSError, "injected chown failure"):
                module.change_paths(paths, 1002, 981, 1002)
        finally:
            module.os.lstat = original_lstat
            module.os.chown = original_chown
        self.assertEqual({b"/data/one": 981, b"/data/two": 981}, gids)
        self.assertEqual(
            [
                (b"/data/one", -1, 1002, False),
                (b"/data/two", -1, 1002, False),
                (b"/data/one", -1, 981, False),
            ],
            events,
        )

    def test_apply_stops_before_change_and_probes_before_success(self) -> None:
        events = []
        details = {
            "domain": "personal-sandbox",
            "user": "argus-personal-sandbox",
            "uid": 1002,
            "currentGid": 1002,
            "staleGid": 981,
            "staleGroup": "argus-control",
            "dataRoot": Path("/data"),
            "entries": [b"entry"],
            "totalEntries": 1,
        }
        inventory = {
            "containerIds": ["one"],
            "volumeNames": ["volume"],
            "projectNames": ["project"],
        }
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "repair-summary.json"
            originals = (
                module.daemon_is_active,
                module.inventory,
                module.docker_ids,
                module.boundary,
                module.require_restart_suppression,
                module.quiesce_containers,
                module.stop_daemon,
                module.prepare_state,
                module.validate_paths,
                module.change_paths,
                module.update_summary,
                module.start_daemon,
                module.restore_firewall,
                module.probe_daemon,
                module.restore_running_set,
            )
            module.daemon_is_active = lambda _domain: True
            module.inventory = lambda _domain: inventory
            module.docker_ids = lambda _domain, running_only=False: {"one"}
            module.boundary = lambda *_args: details
            module.require_restart_suppression = lambda *_args: events.append(
                "policy"
            )
            module.quiesce_containers = lambda *_args: events.append("quiesce")
            module.stop_daemon = lambda _domain: events.append("stop")
            module.prepare_state = lambda _details: (
                summary_path,
                Path(directory) / "paths.b64",
                {},
            )
            module.validate_paths = lambda *_args: [b"/data/entry"]
            module.change_paths = lambda *_args: events.append("change")
            module.update_summary = lambda *_args, **_kwargs: events.append(
                "summary"
            )
            module.start_daemon = lambda _domain: events.append("start")
            module.restore_firewall = lambda _domain: events.append("firewall")
            module.probe_daemon = lambda _domain: events.append("probe")
            module.restore_running_set = lambda *_args: events.append("restore")
            try:
                result = module.apply_repair("personal-sandbox", 981)
            finally:
                (
                    module.daemon_is_active,
                    module.inventory,
                    module.docker_ids,
                    module.boundary,
                    module.require_restart_suppression,
                    module.quiesce_containers,
                    module.stop_daemon,
                    module.prepare_state,
                    module.validate_paths,
                    module.change_paths,
                    module.update_summary,
                    module.start_daemon,
                    module.restore_firewall,
                    module.probe_daemon,
                    module.restore_running_set,
                ) = originals
        self.assertTrue(result["verified"])
        self.assertLess(events.index("policy"), events.index("quiesce"))
        self.assertLess(events.index("quiesce"), events.index("stop"))
        self.assertLess(events.index("stop"), events.index("change"))
        self.assertLess(events.index("change"), events.index("start"))
        self.assertLess(events.index("start"), events.index("firewall"))
        self.assertLess(events.index("firewall"), events.index("probe"))
        self.assertLess(events.index("start"), events.index("probe"))
        self.assertLess(events.index("probe"), events.index("restore"))

    def test_failed_probe_keeps_forward_migration_for_runtime_recovery(self) -> None:
        events = []
        details = {
            "domain": "personal-sandbox",
            "user": "argus-personal-sandbox",
            "uid": 1002,
            "currentGid": 1002,
            "staleGid": 981,
            "staleGroup": "argus-control",
            "dataRoot": Path("/data"),
            "entries": [b"entry"],
            "totalEntries": 1,
        }
        inventory = {
            "containerIds": ["one"],
            "volumeNames": ["volume"],
            "projectNames": ["project"],
        }
        with tempfile.TemporaryDirectory() as directory:
            originals = (
                module.daemon_is_active,
                module.inventory,
                module.docker_ids,
                module.boundary,
                module.require_restart_suppression,
                module.quiesce_containers,
                module.stop_daemon,
                module.prepare_state,
                module.validate_paths,
                module.change_paths,
                module.update_summary,
                module.start_daemon,
                module.restore_firewall,
                module.probe_daemon,
                module.restore_running_set,
            )
            module.daemon_is_active = lambda _domain: True
            module.inventory = lambda _domain: inventory
            module.docker_ids = lambda _domain, running_only=False: {"one"}
            module.boundary = lambda *_args: details
            module.require_restart_suppression = lambda *_args: None
            module.quiesce_containers = lambda *_args: events.append("quiesce")
            module.stop_daemon = lambda _domain: events.append("stop")
            module.prepare_state = lambda _details: (
                Path(directory) / "repair-summary.json",
                Path(directory) / "paths.b64",
                {},
            )
            module.validate_paths = lambda *_args: [b"/data/entry"]

            def change(_paths, _uid, from_gid, to_gid):
                events.append(f"change:{from_gid}:{to_gid}")

            module.change_paths = change
            module.update_summary = (
                lambda _path, _summary, status, **values: events.append(
                    ("summary", status, values)
                )
            )
            module.start_daemon = lambda _domain: events.append("start")
            module.restore_firewall = lambda _domain: events.append("firewall")
            module.probe_daemon = lambda _domain: (_ for _ in ()).throw(
                module.RepairError("probe failed")
            )
            module.restore_running_set = lambda *_args: events.append("restore")
            try:
                with self.assertRaisesRegex(
                    module.RepairError, "migration retained"
                ):
                    module.apply_repair("personal-sandbox", 981)
            finally:
                (
                    module.daemon_is_active,
                    module.inventory,
                    module.docker_ids,
                    module.boundary,
                    module.require_restart_suppression,
                    module.quiesce_containers,
                    module.stop_daemon,
                    module.prepare_state,
                    module.validate_paths,
                    module.change_paths,
                    module.update_summary,
                    module.start_daemon,
                    module.restore_firewall,
                    module.probe_daemon,
                    module.restore_running_set,
                ) = originals
        self.assertEqual(
            ["change:981:1002"],
            [
                event
                for event in events
                if isinstance(event, str) and event.startswith("change:")
            ],
        )
        summaries = [event for event in events if not isinstance(event, str)]
        self.assertEqual("recovery-required", summaries[-1][1])
        self.assertTrue(summaries[-1][2]["metadataRetained"])

    def test_ingress_is_prepared_before_start_and_relocked_after_stability(
        self,
    ) -> None:
        events = []
        ingress = Path("/runtime/workload/stage/ingress")
        states = iter((set(), {"app", "ingress"}, {"app", "ingress"}))
        originals = (
            module.docker_ids,
            module.verified_ingress_directories,
            module.prepare_ingress_directories,
            module.lock_ingress_directories,
            module.run,
            module.RUNNING_STABILITY_SECONDS,
        )
        module.docker_ids = lambda *_args, **_kwargs: next(states)
        module.verified_ingress_directories = (
            lambda _domain, missing: events.append(("discover", set(missing)))
            or [ingress]
        )
        module.prepare_ingress_directories = (
            lambda _domain, paths: events.append(("prepare", list(paths)))
        )
        module.lock_ingress_directories = (
            lambda _domain, paths, *, require_socket: events.append(
                ("lock", list(paths), require_socket)
            )
        )
        module.run = lambda command, **_kwargs: events.append(
            ("start", command)
        ) or SimpleNamespace(returncode=0)
        module.RUNNING_STABILITY_SECONDS = 0
        try:
            module.restore_running_set(
                "personal-sandbox", {"app", "ingress"}
            )
        finally:
            (
                module.docker_ids,
                module.verified_ingress_directories,
                module.prepare_ingress_directories,
                module.lock_ingress_directories,
                module.run,
                module.RUNNING_STABILITY_SECONDS,
            ) = originals
        labels = [event[0] for event in events]
        self.assertLess(labels.index("discover"), labels.index("prepare"))
        self.assertLess(labels.index("prepare"), labels.index("start"))
        self.assertLess(labels.index("start"), labels.index("lock"))
        self.assertTrue(events[-1][2])

    def test_ingress_bind_cannot_escape_the_domain_runtime(self) -> None:
        original_text = module.text
        original_getpwnam = module.pwd.getpwnam
        module.text = lambda *_args, **_kwargs: json.dumps(
            [
                {
                    "Type": "bind",
                    "Source": "/tmp/attacker/ingress",
                    "Destination": "/run/argus-ingress",
                    "RW": True,
                }
            ]
        )
        module.pwd.getpwnam = lambda _user: SimpleNamespace(
            pw_uid=1002, pw_gid=1002
        )
        try:
            with self.assertRaisesRegex(module.RepairError, "escapes"):
                module.verified_ingress_directories(
                    "personal-sandbox", {"container"}
                )
        finally:
            module.text = original_text
            module.pwd.getpwnam = original_getpwnam

    def test_firewall_retries_one_transient_verifier_failure(self) -> None:
        calls = []
        returncodes = iter((0, 1, 1, 0, 0, 0))
        originals = (module.run, module.time.sleep)

        def fake_run(command, **_kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=next(returncodes))

        module.run = fake_run
        module.time.sleep = lambda _seconds: None
        try:
            module.restore_firewall("personal-sandbox")
        finally:
            module.run, module.time.sleep = originals
        restarts = [command for command in calls if "restart" in command]
        self.assertEqual(2, len(restarts))
        self.assertTrue(any("reset-failed" in command for command in calls))

    def test_script_has_no_public_or_broad_deletion_path(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("rm -rf", source)
        self.assertNotIn("tailscale funnel", source.lower())
        self.assertNotIn("cloudflare", source.lower())
        self.assertIn('"--network", "none"', source)
        self.assertIn("follow_symlinks=False", source)
        self.assertIn("sandbox runtime processes remained", source)
        self.assertIn("data root still contains active mounts", source)
        self.assertIn("container restart policy could bypass", source)
        self.assertIn("restore_firewall(domain)", source)
        self.assertIn("scheduled probe executable or fixture is not root-controlled", source)


if __name__ == "__main__":
    unittest.main()
