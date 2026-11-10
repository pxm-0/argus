from __future__ import annotations

import base64
import io
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class DoctorBoundaryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
        self.core_boundary_check = self.namespace["core_boundary_check"]
        self.globals = self.core_boundary_check.__globals__

    def audit_result(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        payload = {
            "auditResult": "pass",
            "policyVersion": "argus-core-boundary-v1",
            "auditVersion": "argus-core-boundary-audit-v1",
            "sbomDigest": "sha256:fixture",
            "endpointDigest": "sha256:fixture",
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    def test_host_doctor_runs_boundary_audit_as_reviewed_checkout_owner(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return self.audit_result(command)

        with (
            patch.object(self.globals["os"], "geteuid", return_value=0),
            patch.object(self.globals["pwd"], "getpwuid", return_value=SimpleNamespace(pw_name="oreo")),
            patch.object(self.globals["shutil"], "which", return_value="/usr/sbin/runuser"),
            patch.dict(self.globals, {"run": runner}),
        ):
            checks: list[dict[str, object]] = []
            self.core_boundary_check(checks)

        self.assertEqual(1, len(calls))
        self.assertEqual(
            ["/usr/sbin/runuser", "-u", "oreo", "--", str(ROOT / "scripts" / "argus-check"), "--boundary-only", "--boundary-json"],
            calls[0],
        )
        self.assertTrue(checks[0]["ok"])

    def test_non_root_doctor_keeps_direct_boundary_audit(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return self.audit_result(command)

        with (
            patch.object(self.globals["os"], "geteuid", return_value=1000),
            patch.dict(self.globals, {"run": runner}),
        ):
            checks: list[dict[str, object]] = []
            self.core_boundary_check(checks)

        self.assertEqual([[str(ROOT / "scripts" / "argus-check"), "--boundary-only", "--boundary-json"]], calls)
        self.assertTrue(checks[0]["ok"])


class DoctorTrackedSourceTests(unittest.TestCase):
    def test_only_opted_in_reviewed_compose_may_be_tracked(self) -> None:
        namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
        check = namespace["tracked_file_checks"]
        files = [
            "workloads/nodens-staging/source/compose.yml",
            "workloads/nodens-staging/source/app.js",
            "workloads/nodens/source/compose.yml",
        ]
        checks: list[dict] = []
        with patch.dict(check.__globals__, {"tracked_files": lambda: files}):
            check(checks)
        row = next(item for item in checks if item["message"] == "no tracked workload source or runtime data")
        self.assertEqual(files[1:], row["paths"])


class HostSudoAndRegistryTests(unittest.TestCase):
    """Real filesystem shapes: modes, owners, and rotation-age boundaries."""

    def setUp(self) -> None:
        self.namespace = runpy.run_path(str(ROOT / "scripts" / "argus-doctor"))
        self.uid = os.getuid()
        self.trusted = (0, self.uid)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.now = datetime(2026, 11, 10, tzinfo=timezone.utc)

    def stamp_at(self, days: int) -> Path:
        path = self.tmp / "stamp"
        path.write_text((self.now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
        return path

    def config(self, auths: dict | None = None, mode: int = 0o600) -> Path:
        directory = self.tmp / "docker"
        directory.mkdir(exist_ok=True)
        directory.chmod(0o700)
        path = directory / "config.json"
        path.unlink(missing_ok=True)
        token = base64.b64encode(b"user:ghp_SECRETTOKEN").decode()
        path.write_text(json.dumps({"auths": auths if auths is not None else {"ghcr.io": {"auth": token}}}))
        path.chmod(mode)
        return path

    def ghcr(self, **overrides):
        checks: list[dict] = []
        arguments = {"now": self.now, "trusted_uids": self.trusted, "below": self.tmp, **overrides}
        if "config" not in arguments:
            arguments["config"] = self.config()
        if "stamp" not in arguments:
            arguments["stamp"] = self.stamp_at(10)
        self.namespace["ghcr_credential_checks"](checks, **arguments)
        return checks

    def row(self, checks: list[dict], fragment: str) -> dict:
        return next(item for item in checks if fragment in item["message"])

    # --- trusted path walk
    def test_trusted_path_problem_flags_group_writable_directories(self) -> None:
        problem = self.namespace["trusted_path_problem"]
        good = self.tmp / "good"
        good.mkdir(mode=0o755)
        (good / "tool").write_text("x")
        self.assertIsNone(problem(str(good / "tool"), self.trusted, self.tmp))
        good.chmod(0o775)
        self.assertIn("group/other writable", problem(str(good / "tool"), self.trusted, self.tmp))
        good.chmod(0o755)
        self.assertIn("owned by uid", problem(str(good / "tool"), (0,), self.tmp))

    def test_trusted_path_problem_resolves_symlinks_to_the_real_location(self) -> None:
        problem = self.namespace["trusted_path_problem"]
        release = self.tmp / "release"
        release.mkdir(mode=0o755)
        (release / "tool").write_text("x")
        unsafe = self.tmp / "unsafe"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        (unsafe / "tool").symlink_to(release / "tool")
        (self.tmp / "via-unsafe").symlink_to(unsafe)
        (self.tmp / "via-release").symlink_to(release)
        self.assertIsNone(problem(str(unsafe / "tool"), self.trusted, self.tmp))  # the link resolves into the release
        self.assertIsNone(problem(str(self.tmp / "via-unsafe" / "tool"), self.trusted, self.tmp))
        self.assertIsNone(problem(str(self.tmp / "via-release" / "tool"), self.trusted, self.tmp))
        self.assertIn("group/other writable", problem(str(self.tmp / "via-unsafe"), self.trusted, self.tmp) or "")

    # --- ExecStart
    def test_exec_start_paths_parse_systemctl_show_output(self) -> None:
        script = self.tmp / "server.py"
        script.write_text("x")
        shown = (
            "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 " + str(script) + " ; ignore_errors=no ; "
            "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"
        )
        self.assertEqual(["/usr/bin/python3", str(script)], self.namespace["exec_start_paths"](shown))
        self.assertEqual([], self.namespace["exec_start_paths"](""))

    def test_exec_start_checks_pass_per_unit_and_fail_for_writable_trees(self) -> None:
        good, bad = self.tmp / "release", self.tmp / "checkout"
        for directory, mode in ((good, 0o755), (bad, 0o775)):
            directory.mkdir(mode=mode)
            directory.chmod(mode)
            (directory / "run").write_text("x")
        shows = {
            "argus-good.service": "{ path=%s ; argv[]=%s ; }" % (good / "run", good / "run"),
            "argus-bad.service": "{ path=%s ; argv[]=%s ; }" % (bad / "run", bad / "run"),
            "argus-empty.service": "",
        }

        def runner(command: list[str]):
            if command[1] == "list-units":
                return subprocess.CompletedProcess(command, 0, "".join(f"{unit} loaded active running x\n" for unit in shows), "")
            return subprocess.CompletedProcess(command, 0, shows[command[2]], "")

        checks: list[dict] = []
        self.namespace["exec_start_checks"](checks, runner, self.trusted, self.tmp)
        self.assertEqual(2, len(checks))
        self.assertTrue(self.row(checks, "argus-good.service")["ok"])
        self.assertFalse(self.row(checks, "argus-bad.service")["ok"])

    # --- sudoers
    def test_sudoers_checks_fail_on_escape_warn_on_accepted_exceptions_and_skip_ignored_names(self) -> None:
        directory = self.tmp / "sudoers.d"
        directory.mkdir()
        (directory / "argus-operator").write_text("oreo ALL=(root) NOPASSWD: /opt/argus/current/scripts/argus m1 verify\n")
        (directory / "90-codex-nopasswd").write_text("oreo ALL=(ALL:ALL) NOPASSWD: ALL\n")
        (directory / "oreo-yog-sothoth").write_text("oreo ALL=(root) NOPASSWD: /usr/bin/systemctl start *\n")
        (directory / "99-evil").write_text("oreo ALL=(root) NOPASSWD: /usr/bin/bash\n")
        (directory / "old.dpkg-dist").write_text("oreo ALL=(ALL) NOPASSWD: ALL\n")
        (directory / "backup~").write_text("oreo ALL=(ALL) NOPASSWD: ALL\n")
        checks: list[dict] = []
        self.namespace["sudoers_checks"](checks, directory)
        rows = {re.search(r"drop-in (\S+)", item["message"]).group(1): item for item in checks}
        self.assertEqual({"90-codex-nopasswd", "99-evil", "argus-operator", "oreo-yog-sothoth"}, set(rows))
        self.assertTrue(rows["argus-operator"]["ok"] and not rows["argus-operator"].get("warn"))
        self.assertTrue(rows["90-codex-nopasswd"]["ok"] and rows["90-codex-nopasswd"]["warn"])
        self.assertTrue(rows["oreo-yog-sothoth"]["warn"])
        self.assertFalse(rows["99-evil"]["ok"])

    def test_sudoers_checks_are_silent_when_directory_unreadable(self) -> None:
        checks: list[dict] = []
        self.namespace["sudoers_checks"](checks, self.tmp / "missing")
        self.assertEqual([], checks)

    # --- GHCR
    def test_ghcr_age_boundaries(self) -> None:
        for days, ok, warn in ((74, True, False), (75, True, True), (76, True, True), (89, True, True), (90, False, False), (91, False, False)):
            row = self.row(self.ghcr(stamp=self.stamp_at(days)), "token age")
            self.assertEqual((ok, bool(row.get("warn"))), (row["ok"], warn_flag := bool(row.get("warn"))), days)
            self.assertEqual(warn, warn_flag, days)
            self.assertEqual(days, row["ageDays"])

    def test_ghcr_future_stamp_and_bad_stamp_fail(self) -> None:
        self.assertFalse(self.row(self.ghcr(stamp=self.stamp_at(-3)), "token age")["ok"])
        bad = self.tmp / "bad"
        bad.write_text("yesterday")
        self.assertFalse(self.row(self.ghcr(stamp=bad), "rotation stamp")["ok"])
        self.assertFalse(self.row(self.ghcr(stamp=self.tmp / "absent"), "rotation stamp")["ok"])

    def test_ghcr_wrong_mode_fails(self) -> None:
        for mode in (0o644, 0o640, 0o660, 0o400):
            self.assertFalse(self.row(self.ghcr(config=self.config(mode=mode)), "mode 0600")["ok"], oct(mode))
        self.assertTrue(self.row(self.ghcr(), "mode 0600")["ok"])

    def test_ghcr_wrong_owner_fails(self) -> None:
        self.assertFalse(self.row(self.ghcr(trusted_uids=(0,)), "mode 0600")["ok"])

    def test_ghcr_writable_config_directory_fails(self) -> None:
        config = self.config()
        config.parent.chmod(0o775)
        self.assertFalse(self.row(self.ghcr(config=config), "config directory")["ok"])

    def test_ghcr_extra_registry_fails(self) -> None:
        token = base64.b64encode(b"u:t").decode()
        extra = {"ghcr.io": {"auth": token}, "docker.io": {"auth": token}}
        row = self.row(self.ghcr(config=self.config(extra)), "ghcr.io only")
        self.assertFalse(row["ok"])
        self.assertEqual(["docker.io", "ghcr.io"], row["registries"])
        self.assertFalse(self.row(self.ghcr(config=self.config({})), "ghcr.io only")["ok"])
        self.assertFalse(self.row(self.ghcr(config=self.config({"docker.io": {"auth": token}})), "ghcr.io only")["ok"])

    def test_ghcr_missing_config_warns_instead_of_failing(self) -> None:
        checks = self.ghcr(config=self.tmp / "nope" / "config.json")
        self.assertEqual(1, len(checks))
        self.assertTrue(checks[0]["ok"] and checks[0]["warn"])

    def test_ghcr_online_scope_check(self) -> None:
        tokens: list[str] = []

        def fetch_for(scopes: str, status: str = "200"):
            def fetch(token: str):
                tokens.append(token)
                body = f"HTTP/2 {status} \r\nserver: GitHub.com\r\nX-OAuth-Scopes: {scopes}\r\n\r\n"
                return subprocess.CompletedProcess([], 0, body, "")

            return fetch

        checks = self.ghcr(online=True, fetch=fetch_for("read:packages"))
        self.assertTrue(self.row(checks, "scopes")["ok"])
        self.assertEqual(["ghp_SECRETTOKEN"], tokens)
        for scopes in ("read:packages, write:packages", "repo", ""):
            self.assertFalse(self.row(self.ghcr(online=True, fetch=fetch_for(scopes)), "scopes")["ok"], scopes)

    def test_ghcr_online_failures_and_secret_hygiene(self) -> None:
        def rejected(token: str):
            return subprocess.CompletedProcess([], 0, "HTTP/2 401 \r\n\r\n", "")

        def offline(token: str):
            return subprocess.CompletedProcess([], 6, "", "Could not resolve host")

        def no_curl(token: str):
            raise FileNotFoundError("curl")

        denied = self.ghcr(online=True, fetch=rejected)
        self.assertFalse(self.row(denied, "rejected the token")["ok"])
        unreachable = self.ghcr(online=True, fetch=offline)
        self.assertTrue(self.row(unreachable, "unreachable")["warn"])
        missing = self.ghcr(online=True, fetch=no_curl)
        self.assertTrue(self.row(missing, "unavailable")["warn"])
        for checks in (denied, unreachable, missing, self.ghcr()):
            self.assertNotIn("SECRETTOKEN", json.dumps(checks))
        self.assertEqual([], [c for c in self.ghcr() if "scopes" in c["message"]], "offline by default")

    def test_curl_header_helper_sends_the_token_on_stdin_not_argv(self) -> None:
        seen: dict = {}

        def fake_run(command, **kwargs):  # noqa: ANN001
            seen.update(command=command, **kwargs)
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(self.namespace["curl_github_headers"].__globals__["subprocess"], "run", fake_run):
            self.namespace["curl_github_headers"]("ghp_SECRETTOKEN")
        self.assertNotIn("SECRETTOKEN", " ".join(seen["command"]))
        self.assertIn("Authorization: Bearer ghp_SECRETTOKEN", seen["input"])
        self.assertIn("@-", seen["command"])


if __name__ == "__main__":
    unittest.main()
