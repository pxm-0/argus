"""Stage 1 of workload retirement: a registry-driven PR generator.

Runs on the operator's machine, edits the reviewed checkout only and never
touches the server. The teardown of the server runtime is emitted as a
numbered runbook for the operator to execute.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from string import Template
from typing import Any, Callable

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RETIRED_FILE = Path("config/argus/retired-workloads.json")
TEMPLATE_FILE = Path("docs/RETIRED_TEMPLATE.md")
ID_KEYS = ("id", "workload", "workloadId")
TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".service", ".timer", ".toml", ".txt", ""}
Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


class RetireError(Exception):
    def __init__(self, code: str, message: str, next_action: str) -> None:
        super().__init__(message)
        self.code, self.message, self.next_action = code, message, next_action


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def prune(node: Any, workload_id: str) -> Any:
    """Return a copy of node without keys, list entries or id-records naming the workload."""
    if isinstance(node, dict):
        return {k: prune(v, workload_id) for k, v in node.items() if k != workload_id}
    if isinstance(node, list):
        kept = [
            item
            for item in node
            if item != workload_id
            and not (isinstance(item, dict) and any(item.get(key) == workload_id for key in ID_KEYS))
        ]
        return [prune(item, workload_id) for item in kept]
    return node


def tracked_files(repo: Path, runner: Runner) -> list[Path]:
    result = runner(["git", "ls-files", "-z"], repo)
    if result.returncode != 0:
        raise RetireError("git-unavailable", "Could not list tracked files.", "Run from a complete Git clone.")
    return [Path(name) for name in result.stdout.split("\0") if name]


def json_changes(repo: Path, files: list[Path], workload_id: str) -> dict[Path, str]:
    changes: dict[Path, str] = {}
    for rel in files:
        if rel.parts[0] != "config" or rel.suffix != ".json" or rel == RETIRED_FILE:
            continue
        original = _load(repo / rel)
        pruned = prune(original, workload_id)
        if pruned != original:
            changes[rel] = _dump(pruned)
    return changes


def text_references(repo: Path, files: list[Path], workload_id: str, skip: set[Path]) -> dict[str, int]:
    pattern = re.compile(rf"(?<![\w-]){re.escape(workload_id)}(?![\w-])")
    found: dict[str, int] = {}
    for rel in files:
        if rel in skip or rel.suffix not in TEXT_SUFFIXES or rel.parts[:2] == ("workloads", workload_id):
            continue
        if rel.name.startswith("RETIRED_") or rel == RETIRED_FILE or not (repo / rel).is_file():
            continue
        try:
            count = len(pattern.findall((repo / rel).read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
        if count:
            found[str(rel)] = count
    return dict(sorted(found.items()))


def teardown_runbook(repo: Path, workload: dict[str, Any], workload_id: str, files: list[Path]) -> str:
    paths = workload.get("paths", {})
    runtime = workload.get("runtime", {})
    domain = workload.get("migration", {}).get("targetTrustDomain", "unknown")
    units = sorted(str(p) for p in files if p.parts[0] == "systemd" and workload_id in p.name)
    routes = _load(repo / "config/routes.json").get("workloadRoutes", {}).get(workload_id, {})
    tailnet_url = routes.get("tailnet", {}).get("url", "")
    steps = [
        f"Confirm a verified, restore-tested backup of `{workload_id}` exists and record it in `docs/RETIRED_{workload_id.upper().replace('-', '_')}.md`.",
        f"Stop and remove the Compose project `{runtime.get('composeProject') or workload_id}` (service `{runtime.get('service') or 'n/a'}`) in trust domain `{domain}`; remove its named volumes and images.",
        f"Remove the Tailscale Serve route{f' for {tailnet_url}' if tailnet_url else ''} and any ingress socket for `{workload_id}`.",
        "Disable and remove any systemd units, timers and sockets for the workload"
        + (f" (tracked here: {', '.join(units)})" if units else " (none tracked in this repository; check `systemctl list-units '*" + workload_id + "*'` on the host)")
        + ".",
        f"Remove the runtime root `{paths.get('root', f'/srv/argus/workloads/{workload_id}')}` including the materialized source checkout.",
        f"Remove the legacy source checkout `{paths['legacy']}` if present." if paths.get("legacy") else "Check for a legacy source checkout and remove it if present.",
        "Merge this PR, pull it on the server, then run `argus m1 sync` (preview) and `argus m1 sync --apply` so private M1 state converges with `retired-workloads.json`.",
        f"Verify `argus workload list` no longer shows `{workload_id}` and `argus doctor` is clean.",
    ]
    return f"# Server teardown runbook: {workload_id}\n\nStage 1 never touches the server. Run these as the operator, in order:\n\n" + "\n".join(
        f"{n}. {text}" for n, text in enumerate(steps, 1)
    ) + "\n"


def pr_body(workload_id: str, applied: list[str], review: dict[str, int], doc: str) -> str:
    review_lines = "\n".join(f"- [ ] Review `{name}` ({count} reference(s))" for name, count in review.items()) or "- [x] No remaining text references found"
    return f"""## P0 Scope

Retire workload `{workload_id}` from the reviewed Argus registries (generated by `argus workload retire`).

## Summary

Registry entries removed from: {', '.join(f'`{a}`' for a in applied) or 'none'}.
Added to `config/argus/retired-workloads.json`; `{doc}` generated.

- [x] `argus check` passed on this branch
{review_lines}
- [ ] Fill in the reason and backup evidence in `{doc}`
- [ ] Server teardown per the runbook comment on this PR
- [ ] After merge, on the server: `argus m1 sync` then `argus m1 sync --apply`

## Verification

`argus check` (ARGUS_CHECK_PASS). Stage 1 did not touch the server.

Acceptance summaries:

- [x] Acceptance summary N/A (docs-only or no server evidence required); reason documented in Notes.

## Safety Checklist

- [x] This PR is phase-scoped
- [x] No secrets
- [x] No Tailscale Funnel was enabled.
- [x] No Cloudflare tunnel was started or enabled.
- [x] No DNS records were created.
- [x] No router ports were opened.
- [x] No public route was exposed.

## Notes

Acceptance summary N/A: registry-only change; nothing was applied on the server.

## Rollback

Revert this PR. Nothing on the server changes until the operator runs the teardown runbook and `argus m1 sync --apply`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""


def _git(runner: Runner, repo: Path, *args: str) -> str:
    result = runner(list(args), repo)
    if result.returncode != 0:
        raise RetireError("command-failed", f"`{' '.join(args[:3])}` failed.", "Fix the reported problem and rerun; the branch may hold partial work.")
    return result.stdout


def retire(repo: Path, workload_id: str, *, dry_run: bool, reason: str, runner: Runner) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(workload_id):
        raise RetireError("workload-id-invalid", "The workload ID is invalid.", "Run argus workload list.")
    workloads = _load(repo / "config/workloads.json")["workloads"]
    workload = next((w for w in workloads if w.get("id") == workload_id), None)
    if workload is None:
        raise RetireError("workload-unknown", "The workload is not in the registry.", "Run argus workload list.")
    retired = _load(repo / RETIRED_FILE)
    if workload_id in retired["workloads"]:
        raise RetireError("workload-already-retired", "The workload is already retired.", "Nothing to do.")

    files = tracked_files(repo, runner)
    changes = json_changes(repo, files, workload_id)
    source_dir = [p for p in files if p.parts[:2] == ("workloads", workload_id)]
    doc = f"docs/RETIRED_{workload_id.upper().replace('-', '_')}.md"
    runbook = teardown_runbook(repo, workload, workload_id, files)
    review = text_references(repo, files, workload_id, set(changes))
    plan = {
        "command": "workload.retire",
        "workloadId": workload_id,
        "dryRun": dry_run,
        "jsonEdits": sorted(str(p) for p in changes),
        "deletions": sorted(str(p) for p in source_dir),
        "generatedDoc": doc,
        "textReferencesToReview": review,
        "runbook": runbook,
    }
    if dry_run:
        return plan

    if _git(runner, repo, "git", "status", "--porcelain").strip():
        raise RetireError("tree-dirty", "The working tree has uncommitted changes.", "Commit or stash them, then rerun.")
    branch = f"retire/{workload_id}"
    _git(runner, repo, "git", "switch", "-c", branch)
    for rel, content in changes.items():
        (repo / rel).write_text(content, encoding="utf-8")
    if (repo / "workloads" / workload_id).exists():
        shutil.rmtree(repo / "workloads" / workload_id)
    (repo / RETIRED_FILE).write_text(_dump({**retired, "workloads": sorted({*retired["workloads"], workload_id})}), encoding="utf-8")
    title = workload.get("name") or workload_id
    body = Template((repo / TEMPLATE_FILE).read_text(encoding="utf-8")).safe_substitute(
        id=workload_id, title=title, date=date.today().isoformat(), reason=reason
    )
    (repo / doc).write_text(body, encoding="utf-8")

    if runner([str(repo / "scripts" / "argus-check")], repo).returncode != 0:
        raise RetireError(
            "repository-check-failed",
            f"argus check failed after the edits; the work is left on branch {branch}.",
            "Fix the first named failure (see textReferencesToReview), commit, and open the PR manually.",
        )
    _git(runner, repo, "git", "add", "-A")
    _git(runner, repo, "git", "commit", "-q", "-m", f"chore: retire {workload_id} from Argus active inventory\n\nGenerated by argus workload retire.")
    _git(runner, repo, "git", "push", "-q", "-u", "origin", branch)
    with tempfile.TemporaryDirectory() as tmp:
        body_file, runbook_file = Path(tmp, "body.md"), Path(tmp, "runbook.md")
        body_file.write_text(pr_body(workload_id, plan["jsonEdits"], review, doc), encoding="utf-8")
        runbook_file.write_text(runbook, encoding="utf-8")
        url = _git(runner, repo, "gh", "pr", "create", "--base", "main", "--head", branch,
                   "--title", f"chore: retire {workload_id} from Argus active inventory", "--body-file", str(body_file)).strip()
        _git(runner, repo, "gh", "pr", "comment", url, "--body-file", str(runbook_file))
    return {**plan, "branch": branch, "prUrl": url, "checks": "pass"}
