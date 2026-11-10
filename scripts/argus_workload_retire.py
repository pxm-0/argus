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
PR_URL = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/pull/\d+$")
RECONCILE = "scripts/argus-m1-reconcile-retired-workloads"
RECONCILE_APPLY = f"{RECONCILE} --apply --acknowledge-retired-workload-reconciliation"
Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


def quiet_runner(command: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    """Like the CLI runner but keeps stderr out of stdout, which retire parses."""
    return subprocess.run(command, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


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


def unit_files(files: list[Path], workload_id: str, all_ids: tuple[str, ...] = ()) -> list[str]:
    # Match the id as a whole token, and ignore longer ids that contain it (nodens vs nodens-staging).
    longer = sorted((i for i in all_ids if i != workload_id and workload_id in i), key=len, reverse=True)
    token = re.compile(rf"(?<![A-Za-z0-9]){re.escape(workload_id)}(?![A-Za-z0-9])")

    def owned(name: str) -> bool:
        for other in longer:
            name = name.replace(other, "\0")
        return bool(token.search(name))

    return sorted(str(p) for p in files if "systemd" in p.parts and owned(p.name))


# Residue the registry cannot see, for workloads that predate Argus-managed Compose.
# Volume class: "keep" holds data (remove only after a verified dump), "remove" is cache/config.
KNOWN_RESIDUE: dict[str, dict[str, Any]] = {
    "nodens": {
        "images": ["sha256:2633eeb26a5f"],
        "volumes": [("nodens-live_caddy-config", "remove"), ("nodens-live_caddy-data", "remove"), ("nodens-live_postgres-data", "keep")],
        "networks": ["nodens_default", "nodens-net", "nodens-sprint55-net"],
    }
}
IMAGE_ID = re.compile(r"^\s*image:\s*(sha256:[0-9a-f]{64})", re.MULTILINE)


def compose_image_ids(repo: Path, files: list[Path]) -> dict[str, set[str]]:
    """Map workload id to the image IDs pinned by its tracked workloads/<id>/source/compose.yml."""
    pinned: dict[str, set[str]] = {}
    for rel in files:
        if len(rel.parts) == 4 and rel.parts[0] == "workloads" and rel.parts[2] == "source" and rel.suffix in {".yml", ".yaml"} and (repo / rel).is_file():
            pinned.setdefault(rel.parts[1], set()).update(IMAGE_ID.findall((repo / rel).read_text(encoding="utf-8")))
    return pinned


def image_step(repo: Path, workload_id: str, files: list[Path], known: list[str]) -> str:
    pinned = compose_image_ids(repo, files)
    own = sorted(pinned.get(workload_id, set()))
    shared = {digest: sorted(i for i, ids in pinned.items() if i != workload_id and digest in ids) for digest in own}
    removable = [d[:19] for d in own if not shared[d]] + known
    text = "Remove images by ID, never by name or tag: " + (", ".join(f"`docker image rm {d}`" for d in removable) or "none pinned in this repository; list candidates with `docker image ls --digests`") + "."
    for digest, users in shared.items():
        if users:
            text += f" WARNING: `{digest[:19]}` is also pinned by {', '.join(f'`{u}`' for u in users)}; do NOT remove it."
    return text


def teardown_runbook(repo: Path, workload: dict[str, Any], workload_id: str, files: list[Path], all_ids: tuple[str, ...] = ()) -> str:
    paths = workload.get("paths", {})
    runtime = workload.get("runtime", {})
    project = runtime.get("composeProject") or workload_id
    domain = workload.get("migration", {}).get("targetTrustDomain", "unknown")
    units = unit_files(files, workload_id, all_ids)
    routes = _load(repo / "config/routes.json").get("workloadRoutes", {}).get(workload_id, {})
    tailnet_url = routes.get("tailnet", {}).get("url", "")
    port = re.search(r":(\d+)(?:/|$)", tailnet_url)
    if port:
        serve = f"`sudo tailscale serve --https={port.group(1)} off`"
        serve_check = f"`tailscale serve status` no longer lists `{tailnet_url}` and `ss -ltn` shows nothing listening on :{port.group(1)}"
    else:
        serve = "`sudo tailscale serve --https=<port> off` for the workload's port (`tailscale serve status` lists it)"
        serve_check = "`tailscale serve status` and `ss -ltn` show no leftover listener"
    residue = KNOWN_RESIDUE.get(workload_id, {})
    volumes, networks = residue.get("volumes", []), residue.get("networks", [])
    if volumes:
        volume_text = "Volumes: " + "; ".join(f"`{v}` ({c.upper()})" for v, c in volumes) + ". KEEP volumes hold data: dump and verify them first, remove them only after the backup is verified."
    else:
        volume_text = f"Volumes: list `docker volume ls --filter name={workload_id}` (it is a substring match: ignore `{workload_id}-staging` and `{workload_id}-production` volumes), classify each KEEP (data) or REMOVE (cache/config), and remove only after the backup is verified."
    network_text = ("Networks: " + ", ".join(f"`docker network rm {n}`" for n in networks) + ".") if networks else f"Networks: check `docker network ls --format '{{{{.Name}}}}' | grep -x '{workload_id}.*'` by name, and remove only this workload's leftovers (not `{workload_id}-staging` or `{workload_id}-production`)."
    unit_stem = f"argus-m5-workload-{workload_id}"
    steps = [
        f"Disable and remove the reconcile retry timer first so nothing restarts the workload (`{unit_stem}.timer` runs `argus-m5-workload-cutover --reconcile` every minute): `sudo systemctl disable --now {unit_stem}.timer {unit_stem}.service`, delete `/etc/systemd/system/{unit_stem}.timer` and `.service`, `sudo systemctl daemon-reload`, then check `systemctl list-unit-files '{unit_stem}*'` prints nothing (match the exact unit name: a substring grep also hits `{workload_id}-staging` and `{workload_id}-production` units that must stay).",
        f"Confirm a verified backup of `{workload_id}` exists; there are two gates. (a) Source and config: `cd /srv/argus`, `ls runtime/backups/{workload_id}/`. If it is empty, run `python3 scripts/argus-backup-run {workload_id} --confirm {workload_id}`. That refuses with `backup is not allowed` when the workload manifest has `operations.backupAllowed=false` (and for manifests with volumes or a database); either set `operations.backupAllowed=true` in `/srv/argus/workloads/{workload_id}/manifest.json` as a reviewed change, or skip to (b) and record that no restore-tested source artifact exists. If an artifact exists, run the isolated restore dry-run on its snapshot ID: `sudo python3 scripts/argus-backup-restore --workload {workload_id} --artifact-id <snapshot-id> --acknowledge-isolated-restore`; it leaves a root-owned `/var/lib/argus/{workload_id}/restore-operations` tree to remove with `sudo rm -r` once checked. (b) Data volumes: argus-backup-run never covers them, so the newest `sudo ls /var/backups/argus-m5-workload-staging/{workload_id}/` stage dir (root 0700) counts only if you inspect its contents, otherwise dump each volume with `docker run --rm -v <volume>:/d -v \"$PWD\":/out alpine tar -czf /out/<volume>.tgz -C /d .` and verify it. The gate passes when (b) is verified, plus (a) where an artifact exists. Record the snapshot ID, if any, and the data backup in `docs/RETIRED_{workload_id.upper().replace('-', '_')}.md`. Nothing below is deleted before this passes.",
        f"Stop and remove the Compose project `{project}` (service `{runtime.get('service') or 'n/a'}`) in trust domain `{domain}` with `docker compose -p {project} down` (no `-v`, no `--rmi`).",
        image_step(repo, workload_id, files, residue.get("images", [])),
        volume_text,
        network_text,
        f"Remove the Tailscale Serve route with {serve}, then confirm {serve_check}. Also remove any ingress socket for `{workload_id}`.",
        "Disable and remove any other systemd units, timers and sockets for the workload"
        + (f" (tracked here: {', '.join(units)})" if units else " (none tracked in this repository; check `systemctl list-units '*" + workload_id + "*'` on the host)")
        + ".",
        f"Remove the runtime root `{paths.get('root', f'/srv/argus/workloads/{workload_id}')}` including the materialized source checkout.",
        f"Directories, each only after the backup is verified. REMOVE `/var/lib/argus/migration-runtime/{domain}/{workload_id}` and `/var/lib/argus/migration-staging/{domain}/{workload_id}` (domain-nested, root-owned: use `sudo`; the runtime dir holds the tailnet-serve ingress socket). KEEP `/var/lib/argus/migration-cutovers/{workload_id}` (cutover evidence) until it is summarised in the retirement doc, then remove it. KEEP `/var/backups/argus-m5-workload-staging/{workload_id}` (root 0700, `sudo`) until it has been copied off-host and that copy verified, then remove it.",
        f"Once the backup is verified, remove the legacy source checkout `{paths['legacy']}` if present; keep it until then." if paths.get("legacy") else "Check for a legacy source checkout and remove it only after the backup is verified.",
        f"Merge this PR, pull it on the server, then run `{RECONCILE}` (preview) and `{RECONCILE_APPLY}` so private M1 state converges with `retired-workloads.json`.",
        f"Run `scripts/argus-m1-verify`, confirm `argus workload list` no longer shows `{workload_id}` and `argus doctor` is clean.",
    ]
    return f"# Server teardown runbook: {workload_id}\n\nStage 1 never touches the server. Run these as the operator, in order, starting at step 0:\n\n" + "\n".join(
        f"{n}. {text}" for n, text in enumerate(steps)
    ) + "\n"


def pr_body(workload_id: str, applied: list[str], review: dict[str, int], doc: str, check_passed: bool, units: list[str]) -> str:
    check_line = "- [x] `argus check` passed on this branch" if check_passed else "- [ ] `argus check` FAILED after the generated edits; fix the leftovers below (draft PR)"
    review_lines = "\n".join(f"- [ ] Review `{name}` ({count} reference(s))" for name, count in review.items()) or "- [x] No remaining text references found"
    unit_lines = "".join(f"- [ ] Delete or retarget tracked unit `{u}` and remove it on the server\n" for u in units)
    return f"""## P0 Scope

Retire workload `{workload_id}` from the reviewed Argus registries (generated by `argus workload retire`).

## Summary

Registry entries removed from: {', '.join(f'`{a}`' for a in applied) or 'none'}.
Added to `config/argus/retired-workloads.json`; `{doc}` generated.

{check_line}
{review_lines}
{unit_lines}- [ ] Fill in the reason and backup evidence in `{doc}`
- [ ] Server teardown per the runbook comment on this PR
- [ ] After merge, on the server: `{RECONCILE}` then `{RECONCILE_APPLY}`, then `scripts/argus-m1-verify`

## Verification

`argus check` result is in the checklist above. Stage 1 did not touch the server.

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

Revert this PR. Nothing on the server changes until the operator runs the teardown runbook and `{RECONCILE_APPLY}`.

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
    all_ids = tuple(w.get("id", "") for w in workloads)
    runbook = teardown_runbook(repo, workload, workload_id, files, all_ids)
    review = text_references(repo, files, workload_id, set(changes))
    plan = {
        "command": "workload.retire",
        "workloadId": workload_id,
        "dryRun": dry_run,
        "jsonEdits": sorted(str(p) for p in changes),
        "deletions": sorted(str(p) for p in source_dir),
        "generatedDoc": doc,
        "textReferencesToReview": review,
        "unitFiles": unit_files(files, workload_id, all_ids),
        "runbook": runbook,
    }
    if dry_run:
        return plan

    if _git(runner, repo, "git", "status", "--porcelain").strip():
        raise RetireError("tree-dirty", "The working tree has uncommitted changes.", "Commit or stash them, then rerun.")
    branch = f"retire/{workload_id}"
    _git(runner, repo, "git", "fetch", "-q", "origin", "main")
    if _git(runner, repo, "git", "rev-parse", "HEAD").strip() != _git(runner, repo, "git", "rev-parse", "origin/main").strip():
        raise RetireError("head-not-main", "HEAD is not at origin/main.", "Check out an up-to-date main, then rerun.")
    if runner(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], repo).returncode == 0:
        raise RetireError("branch-exists", f"Branch {branch} already exists.", f"Delete or finish {branch}, then rerun.")
    _git(runner, repo, "git", "switch", "-c", branch)
    try:
        return _apply(repo, workload_id, workload, retired, changes, plan, review, doc, runbook, reason, branch, runner)
    except RetireError as exc:
        raise RetireError(
            exc.code, exc.message,
            f"{exc.next_action} Recovery: inspect `git status` on {branch}; to abandon run `git switch main && git branch -D {branch}` (and delete the remote branch or PR if it was pushed).",
        ) from exc


def _apply(repo, workload_id, workload, retired, changes, plan, review, doc, runbook, reason, branch, runner):
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

    # Docs, tests and scripts are free-form, so leftovers can fail the check: open a draft PR to finish on.
    check_passed = runner([str(repo / "scripts" / "argus-check")], repo).returncode == 0
    _git(runner, repo, "git", "add", "-A")
    _git(runner, repo, "git", "commit", "-q", "-m", f"chore: retire {workload_id} from Argus active inventory\n\nGenerated by argus workload retire.")
    _git(runner, repo, "git", "push", "-q", "-u", "origin", branch)
    with tempfile.TemporaryDirectory() as tmp:
        body_file, runbook_file = Path(tmp, "body.md"), Path(tmp, "runbook.md")
        body_file.write_text(pr_body(workload_id, plan["jsonEdits"], review, doc, check_passed, plan["unitFiles"]), encoding="utf-8")
        runbook_file.write_text(runbook, encoding="utf-8")
        out = _git(runner, repo, "gh", "pr", "create", "--base", "main", "--head", branch,
                   "--title", f"chore: retire {workload_id} from Argus active inventory", "--body-file", str(body_file),
                   *([] if check_passed else ["--draft"]))
        url = (out.strip().splitlines() or [""])[-1].strip()
        if not PR_URL.fullmatch(url):
            raise RetireError("pr-url-unparsed", "Could not read the PR URL from gh.", f"The PR was likely created for {branch}; open it with gh pr view and post the runbook comment manually.")
        _git(runner, repo, "gh", "pr", "comment", url, "--body-file", str(runbook_file))
    return {**plan, "branch": branch, "prUrl": url, "checks": "pass" if check_passed else "fail"}
