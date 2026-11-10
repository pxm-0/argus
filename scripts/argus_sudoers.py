"""Render and audit the reviewed operator sudoers drop-in and release override units.

The server runs sudo-rs, whose parser is stricter than classic sudo: command
arguments may only be exact words or a lone trailing ``*`` (no ``a*b`` globs),
and ``log_output`` does not exist.  The rendered file sticks to that common
subset so ``visudo -cf`` passes on both implementations.  Scripts that accept a
trailing ``*`` validate their own arguments (image digest, 40-hex sha, domain).
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

DEFAULT_PREFIX = "/opt/argus/current"
SOURCE_PREFIX = "/srv/argus"
OPERATOR = "oreo"
SECURE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SYSTEMCTL, JOURNALCTL, TAILSCALE, SS = "/usr/bin/systemctl", "/usr/bin/journalctl", "/usr/bin/tailscale", "/usr/bin/ss"
DAEMON_UNITS = (
    "argus-capability-issuer.service",
    "argus-control-api.service",
    "argus-operation-worker.service",
    "argus-migration-coordinator.service",
    "argus-privileged-lifecycle-agent.service",
    "argus-domain-agent-legacy-rootful.service",
)
STATUS_EXTRA_UNITS = (
    "argus-smoke.service", "argus-smoke.timer",
    "argus-estate-refresh.service", "argus-estate-refresh.timer",
    "argus-backup-snapshot.service", "argus-backup-snapshot.timer",
    "argus-metrics.service", "argus-metrics.timer",
)
START_UNITS = ("argus-smoke.service", "argus-estate-refresh.service", "argus-backup-snapshot.service")
TAILSCALE_SERVE = (
    "serve --bg --https=8450 unix:/var/lib/argus/sandbox-ingress/nodens-staging/upstream.sock",
    "serve --bg --https=8451 unix:/var/lib/argus/managed-ingress/nodens-production/upstream.sock",
)
# Binaries that turn a sudo entry into a root shell or arbitrary file write.
FORBIDDEN_BINARIES = frozenset({
    "all", "sh", "bash", "dash", "zsh", "fish", "python", "python3", "perl", "ruby", "node", "lua", "env",
    "cp", "mv", "sed", "tee", "install", "chmod", "chown", "chgrp", "ln", "rm", "dd", "find", "awk", "xargs",
    "vi", "vim", "nano", "less", "more", "man", "tar", "rsync", "mount", "nsenter", "unshare", "chroot",
    "su", "sudo", "sudoedit", "visudo", "runuser", "pkexec", "systemd-run", "busybox", "docker", "lxc", "psql",
    "git", "ssh", "scp", "curl", "wget", "nc", "socat", "gdb", "strace", "setsid", "script", "watch", "timeout",
})


def promotable_workloads(repo: Path) -> tuple[str, ...]:
    """Staging workloads whose deploy evidence `argus release promote` reads over ssh."""
    registry = json.loads((repo / "config" / "workloads.json").read_text())
    return tuple(sorted(str(item["id"]) for item in registry["workloads"] if item.get("promotesTo")))


def rootless_domains(repo: Path) -> tuple[str, ...]:
    registry = json.loads((repo / "config" / "argus" / "observation-sources.json").read_text())
    return tuple(sorted({
        str(item["trustDomain"]) for item in registry["sources"] if str(item["sourceId"]).endswith(".rootless-docker")
    }))


def esc(word: str) -> str:
    return re.sub(r"([\\,:=])", r"\\\1", word)


def cmd(path: str, *args: str) -> str:
    return " ".join([path, *[esc(a) if a != "*" else a for a in args]]) if args else f'{path} ""'


def alias(name: str, commands: Iterable[str]) -> str:
    return f"Cmnd_Alias {name} = \\\n    " + ", \\\n    ".join(commands)


def script_commands(prefix: str, domains: tuple[str, ...], promotable: tuple[str, ...] = ()) -> list[str]:
    scripts = f"{prefix}/scripts"
    commands = [cmd(f"{scripts}/argus-image-import", "--domain", d, "--image", "*") for d in domains]
    commands += [
        cmd(f"{scripts}/argus-backup-snapshot"),
        cmd(f"{scripts}/argus-backup-snapshot", "--list"),
        cmd(f"{scripts}/argus-backup-snapshot", "--verify", "*"),
        cmd(f"{scripts}/argus-backup-snapshot", "--restore-plan", "*"),
    ]
    for domain in domains:
        commands += [cmd(f"{scripts}/argus-sandbox-firewall", "--domain", domain, flag) for flag in ("--plan", "--verify", "--probe")]
    commands += [
        cmd(f"{scripts}/argus", "m1", "sync"),
        cmd(f"{scripts}/argus", "m1", "sync", "--apply", "--confirm", "*"),
        cmd(f"{scripts}/argus", "m1", "verify"),
        cmd(f"{scripts}/argus", "m1", "verify", "--json"),
    ]
    # argus-release-install is root-shell only: it installs the code every other entry here runs as root.
    commands += [cmd(f"{scripts}/argus-promote-evidence", "--workload", workload, "--image", "*") for workload in promotable]
    return commands


def restart_units(domains: tuple[str, ...]) -> tuple[str, ...]:
    return DAEMON_UNITS + tuple(f"argus-domain-agent@{d}.service" for d in domains)


def systemctl_commands(domains: tuple[str, ...]) -> list[str]:
    restart = restart_units(domains)
    commands = [cmd(SYSTEMCTL, "restart", unit) for unit in restart]
    commands += [cmd(SYSTEMCTL, "start", unit) for unit in START_UNITS]
    commands += [cmd(SYSTEMCTL, "--no-pager", "status", unit) for unit in dict.fromkeys(restart + STATUS_EXTRA_UNITS)]
    commands.append(cmd(SYSTEMCTL, "daemon-reload"))
    return commands


def read_commands(domains: tuple[str, ...]) -> list[str]:
    return [cmd(JOURNALCTL, "--no-pager", "-n", "200", "-u", unit) for unit in restart_units(domains)]


def net_commands() -> list[str]:
    return [cmd(TAILSCALE, "serve", "status"), cmd(SS, "-H", "-ltnp")] + [cmd(TAILSCALE, *line.split()) for line in TAILSCALE_SERVE]


def render_sudoers(domains: tuple[str, ...], prefix: str = DEFAULT_PREFIX, user: str = OPERATOR, log_output: bool = False, promotable: tuple[str, ...] = ()) -> str:
    defaults = ["!env_keep", "env_reset", f'secure_path="{SECURE_PATH}"', "noexec"] + (["log_output"] if log_output else [])
    parts = [
        "# Managed by scripts/argus-sudoers-render from the reviewed repository; do not edit on the server.",
        f"# Release path: {prefix}. Apply with docs/RUNBOOKS/sudo-narrowing.md (visudo -cf first).",
        "# Argument rules (sudo-rs compatible): exact words, or a lone trailing * on a script that validates it.",
        "# noexec is the default; only ARGUS_SCRIPTS are tagged EXEC because they spawn docker, runuser and git.",
        *(f"Defaults:{user} {item}" for item in defaults),
        "",
        alias("ARGUS_SCRIPTS", script_commands(prefix, domains, promotable)),
        "",
        alias("ARGUS_SYSTEMCTL", systemctl_commands(domains)),
        "",
        alias("ARGUS_READ", read_commands(domains)),
        "",
        alias("ARGUS_NET", net_commands()),
        "",
        f"{user} ALL=(root) NOPASSWD: EXEC: ARGUS_SCRIPTS",
        f"{user} ALL=(root) NOPASSWD: NOEXEC: ARGUS_SYSTEMCTL, ARGUS_READ, ARGUS_NET",
        "",
    ]
    return "\n".join(parts)


@dataclass(frozen=True)
class Entry:
    user: str
    runas: str
    tags: frozenset[str]
    command: str
    args: tuple[str, ...]


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _split_commas(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<!\\),", text) if part.strip()]


def logical_lines(text: str) -> Iterator[str]:
    pending = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\") and not line.endswith("\\\\"):
            pending += line[:-1] + " "
            continue
        full = (pending + line).strip()
        pending = ""
        if full and not full.startswith("#"):
            yield full


def _entry(user: str, runas: str, tags: set[str], text: str) -> Entry:
    while (match := re.match(r"([A-Z_]+):\s*(.*)", text)):
        tags.add(match.group(1))
        text = match.group(2)
    words = [_unescape(word) for word in re.split(r"(?<!\\)\s+", text.strip()) if word]
    args = tuple(w for w in words[1:] if w != '""')
    return Entry(user, runas, frozenset(tags), words[0] if words else "", args)


def parse_entries(text: str) -> list[Entry]:
    """Flatten user rules (aliases expanded) into one Entry per command."""
    aliases: dict[str, list[str]] = {}
    rules: list[tuple[str, str, str]] = []
    for line in logical_lines(text):
        if line.startswith("Defaults"):
            continue
        if match := re.match(r"Cmnd_Alias\s+(\w+)\s*=\s*(.*)", line):
            aliases[match.group(1)] = _split_commas(match.group(2))
        elif re.match(r"(User|Runas|Host)_Alias\s", line):
            continue
        elif match := re.match(r"(\S+)\s+\S+\s*=\s*(?:\(([^)]*)\))?\s*(.*)", line):
            rules.append((match.group(1), match.group(2) or "root", match.group(3)))
    entries: list[Entry] = []
    for user, runas, body in rules:
        tags: set[str] = set()
        for item in _split_commas(body):
            current = set(tags)
            while (tag := re.match(r"([A-Z_]+):\s*(.*)", item)):
                tags.add(tag.group(1))
                current.add(tag.group(1))
                item = tag.group(2)
            for member in aliases.get(item, [item]):
                entries.append(_entry(user, runas, set(current), member))
    return entries


def findings(entries: Iterable[Entry]) -> list[str]:
    """Reasons an entry is a root escape; empty means the rule set is acceptable."""
    problems: list[str] = []
    for entry in entries:
        name = Path(entry.command).name.lower()
        label = " ".join([entry.command, *entry.args])
        if entry.command.upper() == "ALL" or name in FORBIDDEN_BINARIES:
            problems.append(f"forbidden command: {label}")
        elif not entry.command.startswith("/"):
            problems.append(f"command is not an absolute path: {label}")
        elif entry.command.endswith("/*"):
            problems.append(f"directory wildcard command: {label}")
        elif entry.args[:1] == ("*",):
            problems.append(f"bare * argument: {label}")
        elif any("*" in arg and arg != "*" for arg in entry.args) or "*" in entry.args[:-1]:
            problems.append(f"wildcard must be a lone trailing argument: {label}")
        elif name == "systemctl" and "*" in entry.args:
            problems.append(f"systemctl with wildcard: {label}")
    return problems


def entry_matches(entry: Entry, command: str, args: list[str]) -> bool:
    """Does `command args` fall under this entry? `<placeholder>` doc words match any one word."""
    if entry.command != command:
        return False
    want = list(entry.args)
    if want and want[-1] == "*":
        head = want[:-1]
        return len(args) > len(head) and all(_word(w, a) for w, a in zip(head, args))
    return len(want) == len(args) and all(_word(w, a) for w, a in zip(want, args))


def _word(pattern: str, word: str) -> bool:
    return re.fullmatch(r"<[^<>\s]+>", word) is not None or fnmatch.fnmatchcase(word, pattern)


def split_command(line: str) -> list[str]:
    return shlex.split(line, comments=True)


# ---- release override drop-ins -------------------------------------------------

EXEC_KEYS = ("ExecStartPre", "ExecStart", "ExecStartPost", "ExecStop", "ExecReload")
OVERRIDE_NAME = "10-argus-release.conf"
# oreo-run units that call the default-socket docker CLI.  They get the docker group for the unit only, so the
# interactive operator can leave the docker group (membership is root-equivalent: docker.sock is root:docker 0660).
DOCKER_GROUP_UNITS = ("argus-metrics.service", "argus-workload-discover.service")
DOCKER_GROUP_OVERRIDE_NAME = "20-argus-docker-group.conf"
DOCKER_GROUP_OVERRIDE = (
    "# Managed by scripts/argus-sudoers-render --overrides-dir; keeps docker access when oreo leaves the docker group.\n"
    "[Service]\nSupplementaryGroups=docker\n"
)


def render_override(unit_text: str, prefix: str = DEFAULT_PREFIX) -> str | None:
    """Drop-in repointing a unit at the release tree; None when the unit never touches /srv/argus."""
    lines = list(logical_lines(unit_text))
    body: list[str] = []
    for key in EXEC_KEYS:
        mine = [line for line in lines if line.startswith(f"{key}=")]
        if any(SOURCE_PREFIX in line for line in mine):
            body += [f"{key}="] + [line.replace(SOURCE_PREFIX, prefix) for line in mine]
    if not body:
        return None
    if any(line.startswith("WorkingDirectory=") and SOURCE_PREFIX in line for line in lines):
        body.insert(0, f"WorkingDirectory={prefix}")
    header = "# Managed by scripts/argus-sudoers-render --overrides-dir; repoints this unit at the root-owned release."
    # Units that may write /srv/argus/config (access.json, privacy.json) keep ARGUS_ROOT on the live tree: the sealed
    # release is read-only (EROFS) and writing into it would be lost on the next install.  Their code still runs from the release.
    writes_config = any(line.startswith("ReadWritePaths=") and f"{SOURCE_PREFIX}/config" in line.split("=", 1)[1].split() for line in lines)
    root_value = SOURCE_PREFIX if writes_config else prefix
    return "\n".join([header, "[Service]", f"Environment=ARGUS_ROOT={root_value}", *body]) + "\n"


def render_overrides(repo: Path, prefix: str = DEFAULT_PREFIX, units_dir: Path | None = None) -> dict[str, str]:
    """{`<unit>.d/10-argus-release.conf`: text}.

    Sources are the installed units in `units_dir` when given (covers units the repo does not carry, such as the
    generated argus-m5-workload-*.service), else repo systemd/ over templates/systemd/.
    """
    units: dict[str, Path] = {}
    folders = [units_dir] if units_dir else [repo / "templates" / "systemd", repo / "systemd"]
    for folder in folders:
        for path in sorted(folder.glob("argus-*.service" if units_dir else "*.service")):
            if path.is_file():
                units[path.name] = path
    result: dict[str, str] = {}
    for name, path in sorted(units.items()):
        text = render_override(path.read_text(), prefix)
        if text is not None:
            result[f"{name}.d/{OVERRIDE_NAME}"] = text
        if name in DOCKER_GROUP_UNITS:
            result[f"{name}.d/{DOCKER_GROUP_OVERRIDE_NAME}"] = DOCKER_GROUP_OVERRIDE
    return result
