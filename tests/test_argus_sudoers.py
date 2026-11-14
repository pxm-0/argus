from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_sudoers as sudoers  # noqa: E402

COMMITTED = ROOT / "deploy" / "sudoers" / "argus-operator"
RUNBOOKS = ROOT / "docs" / "RUNBOOKS"
DOMAINS = sudoers.rootless_domains(ROOT)
PROMOTABLE = sudoers.promotable_workloads(ROOT)
RENDERED = sudoers.render_sudoers(DOMAINS, promotable=PROMOTABLE)
ENTRIES = sudoers.parse_entries(RENDERED)
loader = importlib.machinery.SourceFileLoader("argus_sudoers_render", str(ROOT / "scripts" / "argus-sudoers-render"))
render_cli = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(render_cli)


class RenderedFileTests(unittest.TestCase):
    def test_committed_file_is_the_render(self) -> None:
        self.assertEqual(RENDERED, COMMITTED.read_text())
        self.assertEqual(0, render_cli.main(["--check"]))

    @unittest.skipUnless(shutil.which("visudo"), "visudo not installed")
    def test_visudo_accepts_rendered_files(self) -> None:
        variants = {
            "default": RENDERED,
            "alt-prefix": sudoers.render_sudoers(DOMAINS, "/opt/x/current", promotable=PROMOTABLE),
            "log-output": sudoers.render_sudoers(DOMAINS, log_output=True, promotable=PROMOTABLE),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in variants.items():
                path = Path(tmp, name)
                path.write_text(text)
                result = subprocess.run(["visudo", "-cf", str(path)], capture_output=True, text=True, check=False)
                self.assertEqual(0, result.returncode, f"{name}: {result.stdout}{result.stderr}")

    def test_defaults_and_aliases(self) -> None:
        for line in ("Defaults:oreo !env_keep", "Defaults:oreo noexec", 'Defaults:oreo secure_path="/usr/local/sbin'):
            self.assertIn(line, RENDERED)
        self.assertNotIn("log_output", RENDERED, "sudo-rs, the server's sudo, rejects log_output")
        for name in ("ARGUS_SCRIPTS", "ARGUS_SYSTEMCTL", "ARGUS_READ", "ARGUS_NET"):
            self.assertIn(f"Cmnd_Alias {name} =", RENDERED)
        self.assertIn("NOPASSWD: EXEC: ARGUS_SCRIPTS", RENDERED)
        self.assertIn("NOEXEC: ARGUS_SYSTEMCTL, ARGUS_READ, ARGUS_NET", RENDERED)
        self.assertTrue(all(e.user == "oreo" and e.runas == "root" for e in ENTRIES))

    def test_prefix_is_applied_to_every_script(self) -> None:
        text = sudoers.render_sudoers(DOMAINS, "/opt/x/current", promotable=PROMOTABLE)
        scripts = [e.command for e in sudoers.parse_entries(text) if "/scripts/" in e.command]
        self.assertTrue(scripts)
        self.assertTrue(all(c.startswith("/opt/x/current/scripts/") for c in scripts))
        self.assertNotIn("/opt/argus/current", text)


class ParserTests(unittest.TestCase):
    def test_rendered_rules_have_no_escape_entries(self) -> None:
        self.assertEqual([], sudoers.findings(ENTRIES))

    def test_no_forbidden_binary_or_bare_wildcard_in_rendered_rules(self) -> None:
        for entry in ENTRIES:
            self.assertNotIn(Path(entry.command).name, sudoers.FORBIDDEN_BINARIES)
            self.assertNotEqual(("*",), entry.args[:1], entry)
            self.assertTrue(entry.command.startswith("/"), entry)
            self.assertNotIn("*", "".join(entry.args[:-1]))
            if entry.args and entry.args[-1] == "*":
                self.assertGreaterEqual(len(entry.args), 2)

    def test_release_installer_is_root_shell_only(self) -> None:
        # It installs the code every other entry runs as root, from a checkout the operator owns.
        self.assertNotIn("argus-release-install", RENDERED)

    def test_promote_evidence_is_allowed_per_promotable_workload_with_a_pinned_workload(self) -> None:
        self.assertIn("nodens-staging", PROMOTABLE)
        lines = [e for e in ENTRIES if e.command.endswith("argus-promote-evidence")]
        self.assertEqual(len(PROMOTABLE), len(lines))
        for entry in lines:
            self.assertEqual(("--workload", entry.args[1], "--image", "*"), entry.args)
            self.assertIn(entry.args[1], PROMOTABLE)
            self.assertNotIn("--ledger", entry.args)

    def test_excluded_tools_never_appear(self) -> None:
        for forbidden in ("argus-m5-", "argus-m0-", "python3", "/bin/bash", "/usr/bin/cp", "/usr/bin/sed", "/usr/bin/tee", "/usr/bin/docker"):
            self.assertNotIn(forbidden, RENDERED)
        self.assertNotIn("ALL=(ALL", RENDERED)

    def test_systemctl_restart_and_start_never_use_globs(self) -> None:
        verbs = [e for e in ENTRIES if e.command.endswith("systemctl") and e.args[:1] in (("restart",), ("start",))]
        self.assertGreaterEqual(len(verbs), len(sudoers.DAEMON_UNITS))
        for entry in verbs:
            self.assertEqual(2, len(entry.args))
            self.assertTrue(re.fullmatch(r"argus-[a-z-]+(@[a-z-]+)?\.service", entry.args[1]), entry)
        for unit in sudoers.restart_units(DOMAINS):
            template = re.sub(r"@.*\.service$", "@.service", unit)
            self.assertTrue((ROOT / "systemd" / template).exists(), unit)

    def test_one_journalctl_line_per_unit(self) -> None:
        lines = [e for e in ENTRIES if e.command.endswith("journalctl")]
        self.assertEqual(len(sudoers.restart_units(DOMAINS)), len(lines))
        for entry in lines:
            self.assertEqual(("--no-pager", "-n", "200", "-u"), entry.args[:4])
            self.assertEqual(5, len(entry.args))

    def test_findings_flag_escapes(self) -> None:
        bad = {
            "oreo ALL=(ALL:ALL) NOPASSWD: ALL": "forbidden",
            "oreo ALL=(root) NOPASSWD: /usr/bin/bash": "forbidden",
            "oreo ALL=(root) NOPASSWD: /usr/bin/cp *": "forbidden",
            "oreo ALL=(root) NOPASSWD: /usr/bin/sed -i *": "forbidden",
            "oreo ALL=(root) NOPASSWD: /usr/bin/tee /etc/x": "forbidden",
            "oreo ALL=(root) NOPASSWD: /usr/bin/python3 /opt/argus/current/scripts/x": "forbidden",
            "oreo ALL=(root) NOPASSWD: /opt/argus/current/scripts/x *": "bare",
            "oreo ALL=(root) NOPASSWD: /usr/bin/systemctl restart *": "systemctl",
            "oreo ALL=(root) NOPASSWD: /opt/x --image ghcr.io/pxm-0/*@sha256\\:*": "lone trailing",
            "oreo ALL=(root) NOPASSWD: /opt/x * --image": "bare",
            "oreo ALL=(root) NOPASSWD: scripts/x": "absolute",
            "oreo ALL=(root) NOPASSWD: /opt/argus/current/scripts/*": "directory",
        }
        for rule, kind in bad.items():
            found = sudoers.findings(sudoers.parse_entries(rule))
            self.assertTrue(found and kind in found[0], f"{rule!r} -> {found}")

    def test_parser_handles_aliases_tags_and_escapes(self) -> None:
        text = (
            "Cmnd_Alias A = /opt/a one\\:two, \\\n  /opt/b \"\"\n"
            "oreo ALL=(root) NOPASSWD: EXEC: A, NOEXEC: /usr/bin/ss -H\n"
        )
        entries = sudoers.parse_entries(text)
        self.assertEqual(
            [("/opt/a", ("one:two",)), ("/opt/b", ()), ("/usr/bin/ss", ("-H",))],
            [(e.command, e.args) for e in entries],
        )
        self.assertEqual({"NOPASSWD", "EXEC"}, set(entries[0].tags))
        self.assertIn("NOEXEC", entries[2].tags)

    def test_entry_matching_semantics(self) -> None:
        wildcard = sudoers.Entry("oreo", "root", frozenset(), "/opt/x", ("--image", "*"))
        self.assertTrue(sudoers.entry_matches(wildcard, "/opt/x", ["--image", "a", "b"]))
        self.assertFalse(sudoers.entry_matches(wildcard, "/opt/x", ["--image"]))
        self.assertFalse(sudoers.entry_matches(wildcard, "/opt/y", ["--image", "a"]))
        exact = sudoers.Entry("oreo", "root", frozenset(), "/opt/x", ("m1", "sync"))
        self.assertTrue(sudoers.entry_matches(exact, "/opt/x", ["m1", "sync"]))
        self.assertFalse(sudoers.entry_matches(exact, "/opt/x", ["m1", "sync", "--apply"]))
        self.assertTrue(sudoers.entry_matches(exact, "/opt/x", ["m1", "<verb>"]))
        self.assertFalse(sudoers.entry_matches(exact, "/opt/x", ["m2", "sync"]))


class OverrideTests(unittest.TestCase):
    def test_control_api_override_repoints_exec_workdir_and_root(self) -> None:
        text = sudoers.render_overrides(ROOT)["argus-control-api.service.d/10-argus-release.conf"]
        self.assertIn("[Service]\nEnvironment=ARGUS_ROOT=/opt/argus/current\n", text)
        self.assertIn("WorkingDirectory=/opt/argus/current\n", text)
        self.assertIn("ExecStart=\nExecStart=/usr/bin/python3 /opt/argus/current/control-plane/api/server.py\n", text)

    def test_config_writer_units_keep_the_live_root_while_code_runs_from_the_release(self) -> None:
        overrides = sudoers.render_overrides(ROOT)
        writers = [p for p in sorted((ROOT / "systemd").glob("*.service")) if "/srv/argus/config" in "".join(
            line.partition("=")[2] for line in p.read_text().splitlines() if line.startswith("ReadWritePaths="))]
        self.assertTrue(writers)
        for path in writers:
            text = overrides[f"{path.name}.d/10-argus-release.conf"]
            self.assertIn("Environment=ARGUS_ROOT=/srv/argus\n", text, path.name)
            self.assertIn("/opt/argus/current/", text, path.name)
        self.assertIn("Environment=ARGUS_ROOT=/opt/argus/current\n", overrides["argus-control-api.service.d/10-argus-release.conf"])

    def test_every_unit_touching_srv_argus_gets_a_dropin_that_leaves_none(self) -> None:
        overrides = sudoers.render_overrides(ROOT)
        for path in sorted((ROOT / "systemd").glob("*.service")):
            exec_lines = [line for line in path.read_text().splitlines() if line.startswith("Exec") and "/srv/argus" in line]
            self.assertEqual(bool(exec_lines), f"{path.name}.d/10-argus-release.conf" in overrides, path.name)
        for name, text in overrides.items():
            self.assertNotIn("/srv/argus", text.replace("Environment=ARGUS_ROOT=/srv/argus\n", ""), name)
            lines = text.splitlines()
            for key in ("ExecStartPre", "ExecStart"):
                for index, line in enumerate(lines):
                    if line == f"{key}=":
                        self.assertTrue(lines[index + 1].startswith(f"{key}="), name)

    def test_docker_cli_units_keep_docker_through_a_unit_group_not_the_operator_group(self) -> None:
        overrides = sudoers.render_overrides(ROOT)
        for unit in sudoers.DOCKER_GROUP_UNITS:
            text = (ROOT / "systemd" / unit).read_text()
            self.assertIn("User=oreo", text, unit)
            script = next(line for line in text.splitlines() if line.startswith("ExecStart=")).partition("=")[2].split()[-1].replace("/srv/argus/", "")
            self.assertIn('"docker"', (ROOT / script).read_text(), f"{unit} no longer calls docker; drop it from DOCKER_GROUP_UNITS")
            self.assertIn("SupplementaryGroups=docker\n", overrides[f"{unit}.d/20-argus-docker-group.conf"])
        # no other oreo-run unit may run the default-socket docker CLI (it would break when oreo leaves the group)
        for path in sorted((ROOT / "systemd").glob("*.service")):
            text = path.read_text()
            if "User=oreo" in text and path.name not in sudoers.DOCKER_GROUP_UNITS:
                script = next((line for line in text.splitlines() if line.startswith("ExecStart=")), "").partition("=")[2].split()[-1:]
                target = ROOT / script[0].replace("/srv/argus/", "") if script else None
                if target and target.is_file() and not target.name.startswith("argus_domain_agent"):
                    self.assertNotRegex(target.read_text(), r'\["docker", "(ps|stats|compose|inspect)"', path.name)

    def test_unit_without_srv_argus_is_skipped_and_prefix_is_validated(self) -> None:
        self.assertIsNone(sudoers.render_override("[Service]\nExecStart=/usr/bin/true\n"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            render_cli.main(["--prefix", "relative/"])

    def test_installed_units_dir_covers_units_the_repo_lacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            units = Path(tmp)
            (units / "argus-m5-workload-nodens.service").write_text(
                "[Service]\nExecStart=/srv/argus/scripts/argus-m5-workload-cutover --workload nodens --reconcile\n")
            (units / "argus-other.service").write_text("[Service]\nExecStart=/usr/bin/true\n")
            (units / "not-argus.service").write_text("[Service]\nExecStart=/srv/argus/x\n")
            overrides = sudoers.render_overrides(ROOT, units_dir=units)
        self.assertEqual(["argus-m5-workload-nodens.service.d/10-argus-release.conf"], list(overrides))
        self.assertIn("ExecStart=/opt/argus/current/scripts/argus-m5-workload-cutover --workload nodens --reconcile", next(iter(overrides.values())))

    def test_cli_writes_dropin_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, render_cli.main(["--overrides-dir", tmp]))
            self.assertTrue(Path(tmp, "argus-control-api.service.d", "10-argus-release.conf").is_file())


def runbook_sudo_lines() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(RUNBOOKS.glob("*.md")):
        text = path.read_text()
        if "<!-- sudoers: root-shell-runbook" in text:
            continue
        lines = text.splitlines()
        fenced = exempt = False
        pending = ""
        for number, raw in enumerate(lines, 1):
            line = raw.strip()
            if line.startswith("```"):
                fenced = not fenced
                exempt = fenced and number >= 2 and lines[number - 2].strip() == "<!-- sudoers: root-shell -->"
                pending = ""
                continue
            if not fenced or exempt:
                continue
            line = pending + line.removeprefix("$ ")
            pending = line[:-1].rstrip() + " " if line.endswith("\\") else ""
            if not pending and line.startswith("sudo "):
                found.append((path.name, number, line))
    return found


def normalise(line: str) -> tuple[str, list[str]] | None:
    words = sudoers.split_command(line)
    for stop in ("|", "&&", ";", ">"):
        words = words[: words.index(stop)] if stop in words else words
    words = words[1:]
    while words and words[0] == "-n":
        words = words[1:]
    if not words or words[0].startswith("-"):
        return None
    command, args = words[0].removeprefix("./"), words[1:]
    for source in (sudoers.SOURCE_PREFIX + "/", sudoers.DEFAULT_PREFIX + "/"):
        command = command.removeprefix(source)
    if command.startswith("scripts/"):
        return f"{sudoers.DEFAULT_PREFIX}/{command}", args
    if command == "argus":
        return f"{sudoers.DEFAULT_PREFIX}/scripts/argus", args
    if command in ("systemctl", "journalctl", "tailscale", "ss"):
        return f"/usr/bin/{command}", args
    return command, args


class RunbookConsistencyTests(unittest.TestCase):
    def test_runbooks_contain_sudo_lines_to_check(self) -> None:
        self.assertGreaterEqual(len(runbook_sudo_lines()), 10)

    def test_every_runbook_sudo_line_is_covered_by_an_alias(self) -> None:
        uncovered = []
        for name, number, line in runbook_sudo_lines():
            parsed = normalise(line)
            if parsed is None or not any(sudoers.entry_matches(e, *parsed) for e in ENTRIES):
                uncovered.append(f"{name}:{number}: {line}")
        self.assertEqual([], uncovered, "mark root-shell blocks with <!-- sudoers: root-shell --> or widen the renderer")

    def test_root_shell_exemptions_are_explicit(self) -> None:
        for path in RUNBOOKS.glob("*.md"):
            for marker in re.findall(r"<!-- sudoers: (.*?) ?-->", path.read_text()):
                self.assertTrue(marker.startswith("root-shell"), f"{path.name}: {marker}")

    def test_new_runbooks_carry_the_safety_steps(self) -> None:
        narrowing = (RUNBOOKS / "sudo-narrowing.md").read_text()
        for needle in ("two", "/root/sudoers-backup", "visudo -cf", "visudo -c", "sudo -n -l", "90-codex-nopasswd", "pkexec"):
            self.assertIn(needle, narrowing)
        self.assertLess(narrowing.index("sudo -n -l"), narrowing.index("rm /etc/sudoers.d/90-codex-nopasswd"))
        self.assertIn("argus-promote-evidence --workload nodens-staging", narrowing)
        self.assertNotIn("sudo -n /usr/bin/systemctl restart sshd", narrowing, "the retained yog-sothoth entry allows it")
        self.assertIn("ROOT-EQUIVALENT", narrowing.upper())
        self.assertLess(narrowing.index("rm /etc/sudoers.d/90-codex-nopasswd"), narrowing.index("gpasswd -d oreo docker"))
        ghcr = (RUNBOOKS / "ghcr-token-rotation.md").read_text()
        self.assertIn("read -rs", ghcr)
        self.assertIn("/etc/argus/registry/.docker", ghcr)
        self.assertIn("ln -sfn /opt/argus/releases/", (RUNBOOKS / "root-owned-release.md").read_text())


if __name__ == "__main__":
    unittest.main()
