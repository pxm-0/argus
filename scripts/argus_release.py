#!/usr/bin/env python3
"""`argus release pin|import` and `argus promote`: reviewed image pins without hand edits.

Imports an allowlisted digest into the workload's trust domain over ssh, rewrites
only the workload service's `image:` line in its reviewed Compose file, runs
`argus check`, and opens a PR. Nothing here deploys; the PR body ends with the
deploy command for the operator to run after merge.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from argus_common import ALLOWED_IMAGES, is_server_checkout
from argus_operations import OperationLedger

EXIT_INTERNAL, EXIT_INVOCATION, EXIT_REFUSAL, EXIT_UNAVAILABLE = 1, 2, 3, 4
REMOTE_REPO = re.compile(r"^/[A-Za-z0-9._/-]{0,200}$")
SSH_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
WORKLOAD_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_LINE = re.compile(r"^(?P<head>    image:\s*)(?P<value>\S+)(?P<tail>.*)$")
PLACEHOLDER_ID = "sha256:<image-id-from-import>"
Result = dict[str, Any]
Runner = Callable[[list[str], Path], Any]


class ReleaseError(Exception):
    def __init__(self, code: str, message: str, next_action: str, exit_code: int = EXIT_REFUSAL) -> None:
        super().__init__(message)
        self.code, self.next_action, self.exit_code = code, next_action, exit_code


def valid_ref(image: str) -> bool:
    return any(pattern.fullmatch(image) for pattern in ALLOWED_IMAGES)


def require_ref(image: str) -> None:
    if not valid_ref(image):
        raise ReleaseError("image-ref-invalid", "image must be an allowlisted reference pinned by sha256 digest.",
                           "Use ghcr.io/pxm-0/<name>@sha256:<digest>.", EXIT_INVOCATION)


def image_lines(text: str, service: str) -> list[tuple[int, re.Match[str]]]:
    """Image lines inside one service body; fails unless the service is declared exactly once."""
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if re.fullmatch(rf"  {re.escape(service)}:\s*(#.*)?", line)]
    if len(headers) != 1:
        raise ReleaseError("compose-service-not-found", f"service {service!r} found {len(headers)} times in compose.yml",
                           "Fix the reviewed compose.yml so the service is declared exactly once.")
    end = next((i for i in range(headers[0] + 1, len(lines)) if re.match(r"(?:  [^\s#]|\S)", lines[i])), len(lines))
    found = ((i, IMAGE_LINE.match(lines[i])) for i in range(headers[0] + 1, end))
    return [(i, match) for i, match in found if match]


def read_pin(text: str, service: str) -> tuple[str, str]:
    """(pinned value, trailing comment text) of the service image line."""
    matches = image_lines(text, service)
    if len(matches) != 1:
        raise ReleaseError("compose-image-line-count", f"expected exactly one image line for {service!r}, found {len(matches)}",
                           "Fix the reviewed compose.yml; pins are never edited when the line is ambiguous.")
    match = matches[0][1]
    return match["value"], match["tail"].strip().lstrip("#").strip()


def rewrite_image(text: str, service: str, image_id: str, comment: str) -> str:
    """Replace only the service's image line; fails unless it is found exactly once."""
    read_pin(text, service)
    index, match = image_lines(text, service)[0]
    lines = text.splitlines(keepends=True)
    ending = "\n" if lines[index].endswith("\n") else ""
    lines[index] = f"{match['head']}{image_id}  # {comment}{ending}"
    return "".join(lines)


def allowed_fields(repo: Path, item: dict[str, Any], workload_id: str, domain: str) -> dict[str, str]:
    """Per-workload values that may legitimately differ: project and bridge from the manifest, ingress dir from the trust domain."""
    try:
        manifest = json.loads((repo / "workloads" / workload_id / "manifest.json").read_text(encoding="utf-8"))
        compose = manifest["runtime"]["compose"]
    except (OSError, KeyError, TypeError, ValueError):
        compose = {}  # no manifest: only the registry project name is masked, so a bridge difference refuses
    fields = {"PROJECT": str(compose.get("project") or item.get("runtime", {}).get("composeProject") or workload_id),
              "INGRESS": f"/var/lib/argus/{domain.split('-', 1)[-1]}-ingress/{workload_id}"}
    if compose.get("bridge"):
        fields["BRIDGE"] = str(compose["bridge"])
    return fields


def normalised(text: str, fields: dict[str, str], service: str) -> list[str]:
    """Compose lines with the allowed per-workload fields masked: project name, ingress path, bridge name, secret refs, the pin."""
    # shortcut: line-based, not a YAML parser; comments stripped at ' #'. Upgrade if compose files need anchors or flow style.
    pin = {i for i, _ in image_lines(text, service)}
    out: list[str] = []
    skip_indent: int | None = None
    for i, line in enumerate(text.splitlines()):
        indent = len(line) - len(line.lstrip())
        if skip_indent is not None:
            if not line.strip() or indent > skip_indent:
                continue
            skip_indent = None
        if re.fullmatch(r"\s*secrets:\s*(#.*)?", line):
            skip_indent = indent
            continue
        line = re.sub(r"\s+#.*$", "", line).rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if i in pin:
            line = IMAGE_LINE.sub(r"\g<head>PIN", line)
        else:
            for key, value in fields.items():
                line = re.sub(rf"(?<![\w./-]){re.escape(value)}(?![\w.-])", f"<{key}>", line)
        out.append(line)
    return out


def compose_drift(staging: str, production: str, staging_fields: dict[str, str], production_fields: dict[str, str], service: str) -> list[str]:
    """Unified diff of the normalised files; empty when they differ only in allowed fields."""
    return list(difflib.unified_diff(normalised(staging, staging_fields, service), normalised(production, production_fields, service),
                                     "staging", "production", lineterm=""))


def load_registry(repo: Path) -> dict[str, dict[str, Any]]:
    try:
        items = json.loads((repo / "config" / "workloads.json").read_text(encoding="utf-8"))["workloads"]
        return {str(item["id"]): item for item in items}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ReleaseError("workload-registry-unavailable", "config/workloads.json is unreadable or malformed.",
                           "Run from a reviewed Argus checkout.", EXIT_UNAVAILABLE) from exc


def workload_context(repo: Path, workload_id: str) -> dict[str, Any]:
    item = load_registry(repo).get(workload_id)
    if item is None:
        raise ReleaseError("workload-unknown", "The workload is not in the registry.", "Run argus workload list.", EXIT_INVOCATION)
    domain = str(item.get("migration", {}).get("targetTrustDomain", ""))
    service = str(item.get("runtime", {}).get("service", ""))
    compose = repo / "workloads" / workload_id / "source" / "compose.yml"
    if not domain or not service or not compose.is_file():
        raise ReleaseError("workload-not-releasable", "The workload has no trust domain, service, or reviewed compose.yml.",
                           "Onboard the workload before pinning images.")
    return {"item": item, "domain": domain, "service": service, "compose": compose,
            "fields": allowed_fields(repo, item, workload_id, domain)}


def ssh_target() -> tuple[str, str]:
    host = os.environ.get("ARGUS_SSH_HOST", "oreochiserver")
    if not SSH_HOST.fullmatch(host):
        raise ReleaseError("ssh-host-invalid", "ARGUS_SSH_HOST is not a plain host name.", "Unset it or use a bare host or user@host.", EXIT_INVOCATION)
    remote_repo = os.environ.get("ARGUS_REMOTE_REPO", "/srv/argus").rstrip("/")
    if not REMOTE_REPO.fullmatch(remote_repo) or ".." in remote_repo.split("/"):
        raise ReleaseError("remote-repo-invalid", "ARGUS_REMOTE_REPO is not a plain absolute path.", "Unset it or use e.g. /srv/argus.", EXIT_INVOCATION)
    return host, remote_repo


def import_image(repo: Path, runner: Runner, domain: str, image: str) -> str:
    host, remote_repo = ssh_target()
    importer = f"{remote_repo}/scripts/argus-image-import"
    result = runner(["ssh", host, "sudo", "-n", importer, "--domain", domain, "--image", image], repo)
    for line in reversed((result.stdout or "").splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("ok") is True and IMAGE_ID.fullmatch(str(payload.get("imageId", ""))):
            return payload["imageId"]
        break
    raise ReleaseError("image-import-failed", f"argus-image-import on the server did not return an image ID (exit {result.returncode}).",
                       "Check passwordless `sudo -n` on the server importer (ARGUS_REMOTE_REPO) and the ref, then retry.", EXIT_UNAVAILABLE)


def diff_text(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{path}", f"b/{path}"))


def git(repo: Path, runner: Runner, *args: str) -> str:
    result = runner(["git", *args], repo)
    if result.returncode != 0:
        raise ReleaseError("git-failed", f"git {args[0]} failed: {(result.stdout or '').strip()[-200:]}",
                           "Resolve the git state and retry.", EXIT_UNAVAILABLE)
    return result.stdout or ""


def pr_body(title: str, ref: str, image_id: str, diff: str, checklist: list[str], workload_id: str) -> str:
    items = "\n".join(f"- [ ] {item}" for item in checklist)
    return f"""## P0 Scope

{title}. Only the `image:` line of the workload service changes.

## Summary

- Ref: `{ref}`
- Image ID (domain-reported): `{image_id}`

```diff
{diff.rstrip()}
```

## Verification

- `argus check` passed on this branch before the PR was opened.
- Image imported into the trust domain with `argus-image-import`; the pin is the ID it reported.

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

Acceptance summary N/A: this PR changes one reviewed pin; the import was the only server action.

## Rollback

Revert this PR, pull on the server, and redeploy the previous pin (its image stays loaded in the domain).

## Deploy checklist

{items}

Next step after merge and server pull: `argus workload deploy {workload_id} --revision {image_id}`
"""


def open_pr(repo: Path, runner: Runner, branch: str, path: Path, new_text: str, message: str, body: str) -> str:
    original = path.read_text(encoding="utf-8")
    if git(repo, runner, "status", "--porcelain").strip():
        raise ReleaseError("worktree-dirty", "The working tree has uncommitted changes.", "Commit or stash them, then retry.")
    path.write_text(new_text, encoding="utf-8")
    try:
        if runner([sys.executable, str(repo / "scripts" / "argus-check")], repo).returncode != 0:
            raise ReleaseError("repository-check-failed", "argus check failed after the pin edit; nothing was committed.",
                               "Run ./scripts/argus-check and fix the first named failure.", EXIT_INTERNAL)
        git(repo, runner, "switch", "-c", branch)
        git(repo, runner, "add", str(path.relative_to(repo)))
        git(repo, runner, "commit", "-m", message)
    except ReleaseError:
        path.write_text(original, encoding="utf-8")
        raise
    git(repo, runner, "push", "-u", "origin", branch)
    created = runner(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", message, "--body", body], repo)
    if created.returncode != 0:
        raise ReleaseError("pr-create-failed", f"gh pr create failed; branch {branch} is pushed.",
                           "Open the PR for that branch by hand.", EXIT_UNAVAILABLE)
    return (created.stdout or "").strip().splitlines()[-1] if (created.stdout or "").strip() else ""


def release_import(repo: Path, runner: Runner, workload_id: str, image: str) -> Result:
    context = workload_context(repo, workload_id)
    require_ref(image)
    return {"command": "release.import", "imageId": import_image(repo, runner, context["domain"], image), "trustDomain": context["domain"]}


def release_pin(repo: Path, runner: Runner, workload_id: str, image: str, dry_run: bool) -> Result:
    context = workload_context(repo, workload_id)
    require_ref(image)
    before = context["compose"].read_text(encoding="utf-8")
    image_id = PLACEHOLDER_ID if dry_run else import_image(repo, runner, context["domain"], image)
    after = rewrite_image(before, context["service"], image_id, image)
    diff = diff_text(str(context["compose"].relative_to(repo)), before, after)
    if dry_run:
        return {"command": "release.pin", "dryRun": True, "diff": diff, "note": "dry run: no import, no branch, no PR"}
    checklist = [
        "Merge, then `git -C /srv/argus pull --ff-only` on the server",
        "First pin for this workload: its manifest `operations` must allow deploy, start, stop and health",
        "Deploy with the exact image ID; verify health",
    ]
    branch = f"release/{workload_id}-{image_id[7:19]}"
    body = pr_body(f"Pin {workload_id} to a reviewed image", image, image_id, diff, checklist, workload_id)
    url = open_pr(repo, runner, branch, context["compose"], after, f"chore(release): pin {workload_id} to {image_id[7:19]}", body)
    return {"command": "release.pin", "branch": branch, "imageId": image_id, "prUrl": url,
            "nextAction": f"After merge and server pull: argus workload deploy {workload_id} --revision {image_id}"}


def ledger_has_deploy(path: Path, staging_id: str, image_id: str) -> bool:
    """True when the read-only operations ledger at `path` lists a succeeded workload.deploy of this image ID."""
    operations = OperationLedger(path, require_existing=True, migrate_schema=False, read_only=True).list_for_workload(staging_id)
    return any(
        op.get("operation_type") == "workload.deploy" and op.get("state") == "succeeded"
        and (op.get("parameters") or {}).get("targetRevision") == image_id
        for op in operations
    )


def deploy_evidence(repo: Path, runner: Runner, staging_id: str, image_id: str) -> bool:
    """Read the ledger directly; if this user cannot (it is argus-control only), ask the server's evidence script via sudo."""
    configured = os.environ.get("ARGUS_OPERATIONS_DB", "").strip()
    if configured:
        path = Path(configured)
    elif is_server_checkout(repo):
        path = Path("/var/lib/argus/control/operations.sqlite3")
    else:
        path = repo / "runtime" / "argus" / "m5" / "operations.sqlite3"
    try:
        return ledger_has_deploy(path, staging_id, image_id)
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        pass
    host, remote_repo = ssh_target()
    result = runner(["ssh", host, "sudo", "-n", f"{remote_repo}/scripts/argus-promote-evidence", "--workload", staging_id, "--image", image_id], repo)
    for line in reversed((result.stdout or "").splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("ok") is True and isinstance(payload.get("deployed"), bool):
            return payload["deployed"]
        break
    raise ReleaseError("promote-evidence-unavailable", "Staging deploy evidence could not be read from the operations ledger, locally or over ssh.",
                       "Needs passwordless `sudo -n` for the server's argus-promote-evidence (merge and pull this change first), or confirm the staging deploy and rerun with --skip-evidence-check.")


def promote(repo: Path, runner: Runner, staging_id: str, production_id: str, dry_run: bool, skip_evidence: bool) -> Result:
    staging, production = workload_context(repo, staging_id), workload_context(repo, production_id)
    if staging["item"].get("promotesTo") != production_id:
        raise ReleaseError("promote-target-unregistered", f"{staging_id} is not registered with promotesTo={production_id}.",
                           "Set promotesTo in config/workloads.json through a reviewed PR.")
    staging_text, production_text = staging["compose"].read_text(encoding="utf-8"), production["compose"].read_text(encoding="utf-8")
    image_id, comment = read_pin(staging_text, staging["service"])
    ref = next((word for word in comment.split() if valid_ref(word)), "")
    if not IMAGE_ID.fullmatch(image_id) or not ref:
        raise ReleaseError("promote-staging-unpinned", "Staging has no imported pin with a recorded image reference.",
                           "Run argus release pin for staging first.")
    drift = compose_drift(staging_text, production_text, staging["fields"], production["fields"], staging["service"])
    if drift:
        raise ReleaseError("promote-compose-differs", "Staging and production compose differ beyond project name, ingress path, bridge name, secret refs and the image pin:\n"
                           + "\n".join(drift[:12]), "Align the two compose files in a reviewed PR first.")
    if not skip_evidence and not deploy_evidence(repo, runner, staging_id, image_id):
        raise ReleaseError("promote-staging-not-deployed", "No succeeded staging deploy of this image ID was found.",
                           "Deploy and verify staging first, or rerun with --skip-evidence-check after confirming it yourself.")
    old_pin = read_pin(production_text, production["service"])[0]
    after = rewrite_image(production_text, production["service"], image_id, comment)
    diff = diff_text(str(production["compose"].relative_to(repo)), production_text, after)
    if dry_run:
        return {"command": "promote", "dryRun": True, "diff": diff, "note": "dry run: no import, no branch, no PR"}
    if import_image(repo, runner, production["domain"], ref) != image_id:
        raise ReleaseError("promote-image-id-mismatch", "The production domain reported a different image ID than the staging pin.",
                           "Do not promote; investigate the two imports.")
    shown = f"# both pinned to the same ID\n# {staging_id}: image: {image_id}\n# {production_id}: image: {image_id} (was {old_pin})\n{diff}"
    checklist = [f"Staging {staging_id} deployed and healthy on this ID",
                 "Merge, then `git -C /srv/argus pull --ff-only` on the server",
                 "First promotion: grant the production manifest deploy, start, stop and health"]
    body = pr_body(f"Promote {staging_id} to {production_id}", ref, image_id, shown, checklist, production_id)
    url = open_pr(repo, runner, f"release/{production_id}-{image_id[7:19]}", production["compose"], after,
                  f"chore(release): promote {staging_id} to {production_id}", body)
    return {"command": "promote", "imageId": image_id, "prUrl": url,
            "nextAction": f"After merge and server pull: argus workload deploy {production_id} --revision {image_id}"}


def register(commands: Any, leaf: Callable[..., Any], description: Callable[..., str], parser_class: type) -> None:
    """Adds `release pin|import` and `promote` to the argus parser."""
    release = commands.add_parser("release", help="import and pin reviewed images through a PR")
    sub = release.add_subparsers(dest="release_command", required=True, parser_class=parser_class)
    for action, purpose in (("pin", "Import an image digest and open a PR pinning it."),
                            ("import", "Import an image digest into the workload's trust domain.")):
        pin = action == "pin"
        item = leaf(sub, action, help_text=purpose, contract=description(
            purpose, "server mutation", "ARGUS_SSH_HOST reachable, passwordless sudo -n on the server importer" + (", gh logged in, clean checkout" if pin else ""),
            "image loaded in the trust domain" + ("; branch and PR" if pin else ""), "image ID" + (" and PR URL" if pin else ""),
            f"argus release {action} nodens-staging --image ghcr.io/pxm-0/nodens@sha256:<digest>", "retry; imports are idempotent. Never deploys"))
        item.add_argument("workload_id")
        item.add_argument("--image", required=True, help="ghcr.io/pxm-0/<name>@sha256:<digest>")
        if pin:
            item.add_argument("--dry-run", action="store_true", help="print the diff only; no import, branch or PR")
    item = leaf(commands, "promote", help_text="promote the staging pin to production through a PR", contract=description(
        "Promote the staging image pin to production.", "server mutation",
        "promotesTo registered, staging deploy evidence, compose files differing only in name/ingress path/bridge name/secret refs",
        "image loaded in the production domain; branch and PR", "image ID and PR URL", "argus promote nodens-staging nodens-production",
        "fix the named refusal and retry. Never deploys"))
    item.add_argument("staging_id")
    item.add_argument("production_id")
    item.add_argument("--dry-run", action="store_true", help="print the diff only; no import, branch or PR")
    item.add_argument("--skip-evidence-check", action="store_true", help="skip the staging deploy evidence lookup")


def dispatch(args: Any, repo: Path, runner: Runner, error: Callable[..., Result], success: Callable[..., Result]) -> Result:
    ids = [getattr(args, name) for name in ("workload_id", "staging_id", "production_id") if hasattr(args, name)]
    try:
        if not all(WORKLOAD_ID.fullmatch(value) for value in ids):
            raise ReleaseError("workload-id-invalid", "The workload ID is invalid.", "Run argus workload list.", EXIT_INVOCATION)
        if args.command == "promote":
            data = promote(repo, runner, args.staging_id, args.production_id, args.dry_run, args.skip_evidence_check)
        elif args.release_command == "pin":
            data = release_pin(repo, runner, args.workload_id, args.image, args.dry_run)
        else:
            data = release_import(repo, runner, args.workload_id, args.image)
    except ReleaseError as exc:
        return error(exc.code, str(exc), exc.next_action, exit_code=exc.exit_code)
    return success(data.pop("command"), **data)
