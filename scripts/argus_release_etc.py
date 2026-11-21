"""Converge root-owned /etc state (units, drop-ins, sysusers, release overrides, sudoers) to a release.

Used by scripts/argus-release-apply (task 2/5, docs/RELEASE_APPLY.md steps 6 and 11). Scope is deliberately
narrow: unit and sysusers files are only updated when already installed; drop-ins, release overrides and the
sudoers file may be created. Nothing is ever deleted, enabled or disabled, and a `<unit>.d` dir is never removed.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib.machinery
import importlib.util
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VISUDO, SYSTEMCTL, SYSUSERS = "/usr/sbin/visudo", "/usr/bin/systemctl", "/usr/bin/systemd-sysusers"
CREATABLE = frozenset({"dropin", "override", "sudoers"})
APPLIED_CLASSES = ("update", "mode-owner", "create")
Runner = Callable[[list[str]], subprocess.CompletedProcess]
Desired = dict[Path, tuple[bytes, int, str]]


class EtcRefused(RuntimeError):
    """An /etc target is unsafe to write (symlink, foreign owner, writable parent) or the sudoers is invalid."""


class EtcFailed(RuntimeError):
    """Convergence failed after a change; the caller records exit 5."""


@dataclass(frozen=True)
class EtcRoots:
    systemd: Path = Path("/etc/systemd/system")
    sysusers: Path = Path("/etc/sysusers.d")
    sudoers: Path = Path("/etc/sudoers.d")


def sha256(data: bytes | None) -> str | None:
    return None if data is None else "sha256:" + hashlib.sha256(data).hexdigest()


def _load_renderer(candidate: Path):
    """The candidate's own renderer, from the hash-verified tree (it becomes current code moments later anyway)."""
    path = candidate / "scripts" / "argus_sudoers.py"
    if not path.is_file():
        return None
    loader = importlib.machinery.SourceFileLoader("argus_sudoers_candidate", str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def desired_state(candidate: Path, etc: EtcRoots) -> tuple[Desired, list[dict]]:
    """({target: (content, mode, kind)}, report-only entries) for the verified candidate tree."""
    units = candidate / "systemd"
    desired: Desired = {}
    report: list[dict] = []

    def offer(source: Path, target: Path, mode: int, kind: str, installed: bool) -> None:
        if installed:
            desired[target] = (source.read_bytes(), mode, kind)
        else:
            report.append({"path": str(target), "class": "available-not-installed"})

    if units.is_dir():
        for source in sorted([*units.glob("*.service"), *units.glob("*.timer")]):
            target = etc.systemd / source.name
            offer(source, target, 0o644, "unit", os.path.lexists(target))
        for folder in sorted(path for path in units.glob("*.d") if path.is_dir() and path.name != "sysusers.d"):
            installed = os.path.lexists(etc.systemd / folder.name[:-2]) or (etc.systemd / folder.name).is_dir()
            for source in sorted(folder.glob("*.conf")):
                offer(source, etc.systemd / folder.name / source.name, 0o644, "dropin", installed)
        for source in sorted((units / "sysusers.d").glob("*.conf")):
            target = etc.sysusers / source.name
            offer(source, target, 0o644, "sysusers", os.path.lexists(target))

    renderer = _load_renderer(candidate)
    if renderer is not None:
        # Overrides cover every installed argus unit (including generated workload units the repo does not carry),
        # each as it will be after convergence. templates/systemd is never a source.
        with tempfile.TemporaryDirectory(prefix="argus-units-") as scratch:
            for installed in sorted(etc.systemd.glob("argus-*.service")):
                if installed.is_symlink() or not installed.is_file():
                    continue
                repo_copy = units / installed.name
                (Path(scratch) / installed.name).write_bytes(repo_copy.read_bytes() if repo_copy.is_file() else installed.read_bytes())
            rendered = renderer.render_overrides(candidate, renderer.DEFAULT_PREFIX, Path(scratch))
        for relative, text in rendered.items():
            desired[etc.systemd / relative] = (text.encode(), 0o644, "override")

    sudoers = candidate / "deploy" / "sudoers" / "argus-operator"
    if sudoers.is_file():
        # CI proves the committed file equals its renderer's output (tests/test_argus_sudoers.py).
        desired[etc.sudoers / "argus-operator"] = (sudoers.read_bytes(), 0o440, "sudoers")
    return desired, report


def _require_safe_parents(target: Path, top: Path, owner: tuple[int, int]) -> None:
    node = target.parent
    while True:
        if os.path.lexists(node):
            info = node.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner[0] or info.st_mode & 0o022:
                raise EtcRefused(f"{node} is a symlink, not root-owned, or group/other writable")
        if node == top or node == node.parent:
            return
        node = node.parent


def classify(desired: Desired, etc: EtcRoots, owner: tuple[int, int]) -> list[dict]:
    entries = []
    for target, (content, mode, kind) in sorted(desired.items()):
        top = etc.sudoers if kind == "sudoers" else etc.sysusers if kind == "sysusers" else etc.systemd
        _require_safe_parents(target, top, owner)
        before = None
        if os.path.lexists(target):
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != owner[0]:
                raise EtcRefused(f"{target} is not a root-owned regular file")
            before = target.read_bytes()
            if before != content:
                drift = "update"
            elif stat.S_IMODE(info.st_mode) != mode or info.st_gid != owner[1]:
                drift = "mode-owner"
            else:
                drift = "same"
        elif kind in CREATABLE:
            drift = "create"
        else:
            continue
        entries.append({"path": str(target), "kind": kind, "class": drift, "mode": oct(mode),
                        "before": sha256(before), "after": sha256(content)})
    return entries


def managed_orphans(desired: Desired, etc: EtcRoots) -> list[dict]:
    """Drop-ins carrying a "Managed by" header that the release no longer wants: reported, never removed."""
    orphans = []
    for path in sorted(etc.systemd.glob("*.d/*.conf")):
        if path in desired or path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.readline().startswith(b"# Managed by"):
                orphans.append({"path": str(path), "class": "managed-orphan"})
    return orphans


def describe(entries: list[dict], desired: Desired, diff_lines: int = 40) -> list[str]:
    lines = []
    for entry in entries:
        if entry["class"] == "same":
            continue
        lines.append(f"  {entry['class']:<24} {entry['path']}")
        if entry["class"] == "update":
            target = Path(entry["path"])
            new = desired[target][0].decode(errors="replace").splitlines()
            old = target.read_bytes().decode(errors="replace").splitlines()
            diff = list(difflib.unified_diff(old, new, "installed", "release", lineterm="", n=1))
            lines += [f"    {line}" for line in diff[:diff_lines]]
            if len(diff) > diff_lines:
                lines.append(f"    ... {len(diff) - diff_lines} more diff lines")
    return lines


def precheck_sudoers(entries: list[dict], desired: Desired, runner: Runner) -> None:
    """visudo -cf on a private copy before anything changes."""
    for entry in entries:
        if entry["kind"] != "sudoers" or entry["class"] not in ("update", "create"):
            continue
        with tempfile.TemporaryDirectory(prefix="argus-sudoers-") as scratch:
            candidate = Path(scratch) / "argus-operator"
            candidate.write_bytes(desired[Path(entry["path"])][0])
            result = runner([VISUDO, "-cf", str(candidate)])
        if result.returncode != 0:
            raise EtcRefused(f"visudo -cf rejects the release sudoers: {(result.stderr or result.stdout or '').strip()[-300:]}")


def _atomic_write(target: Path, content: bytes, mode: int, owner: tuple[int, int], temp_name: str) -> None:
    temp = target.parent / temp_name
    if os.path.lexists(temp):
        temp.unlink()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, content)
        os.fchown(fd, *owner)
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, target)


def _backup(target: Path, backup_root: Path) -> None:
    if not os.path.lexists(target):
        return
    copy = backup_root / str(target).lstrip("/")
    copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(target, copy, follow_symlinks=False)


def converge(entries: list[dict], desired: Desired, backup_root: Path, owner: tuple[int, int], runner: Runner) -> list[dict]:
    """Apply every non-`same` entry, sudoers last; returns the changed entries. Raises EtcFailed."""
    pending = sorted((e for e in entries if e["class"] in APPLIED_CLASSES), key=lambda e: (e["kind"] == "sudoers", e["path"]))
    changed = []
    for entry in pending:
        target = Path(entry["path"])
        content, mode, kind = desired[target]
        try:
            _backup(target, backup_root)
            if not target.parent.exists():
                target.parent.mkdir(mode=0o755)
                os.chown(target.parent, *owner)
            # sudo skips names containing a dot, so the sudoers temp file is never live.
            _atomic_write(target, content, mode, owner, f".{target.name}.argus-new")
        except OSError as exc:
            raise EtcFailed(f"cannot write {target}: {exc}") from exc
        changed.append(entry)
        if kind == "sudoers":
            _verify_sudoers(target, backup_root, owner, runner)
    if any(entry["kind"] == "sysusers" for entry in changed):
        result = runner([SYSUSERS])
        if result.returncode != 0:
            raise EtcFailed(f"systemd-sysusers failed: {(result.stderr or '').strip()[-300:]}")
    return changed


def _verify_sudoers(target: Path, backup_root: Path, owner: tuple[int, int], runner: Runner) -> None:
    if runner([VISUDO, "-c"]).returncode == 0:
        return
    backup = backup_root / str(target).lstrip("/")
    if backup.is_file():
        _atomic_write(target, backup.read_bytes(), stat.S_IMODE(backup.lstat().st_mode), owner, f".{target.name}.argus-restore")
    else:
        target.unlink()
    restored = runner([VISUDO, "-c"]).returncode == 0
    raise EtcFailed(f"visudo -c failed after installing {target}; previous state restored"
                    + ("" if restored else ", but visudo -c STILL fails: fix sudoers by hand"))
