"""`argus m1 sync|verify`: one-pass, digest-confirmed front end for the M1 reconcile modules."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, TextIO

from argus_m1_onboarded_workloads import reconcile_onboarded_workloads
from argus_m1_retired_workloads import (
    TABLES,
    RetirementReconcileError,
    _expected,
    _read_entities,
    _read_projection,
    reconcile_retired_workloads,
)
from argus_m1_verify import VerificationError, verify_m1_state

EXIT_INTERNAL = 1
EXIT_REFUSAL = 3
EXIT_UNAVAILABLE = 4
SERVER_ROOT = "/srv/argus"
SERVER_COMMAND = "ssh oreochiserver 'sudo {root}/scripts/argus m1 {verb}'"
STORES = ("entities", "privacy", "access")
Error = Callable[..., dict[str, Any]]
Success = Callable[..., dict[str, Any]]


def _entity_path(repo: Path) -> Path:
    return repo / "runtime" / "argus" / "entity-store.sqlite3"


def on_server(repo: Path) -> bool:
    return _entity_path(repo).is_file()


def build_plan(repo: Path) -> dict[str, Any]:
    """Diff reviewed config against M1 rows. Read-only; raises RetirementReconcileError on refusal."""
    entities, privacy, access, retired_ids, config_digest = _expected(repo)
    runtime = repo / "runtime" / "argus"
    state = runtime / "m1" / "state.sqlite3"
    pairs = {
        "entities": (_read_entities(_entity_path(repo)), entities),
        "privacy": (_read_projection(state, TABLES["privacy"][0]), privacy),
        "access": (_read_projection(state, TABLES["access"][0]), access),
    }
    plan: dict[str, Any] = {"configDigest": config_digest}
    for store, (actual, expected) in pairs.items():
        stale = set(actual) - set(expected)
        if stale - retired_ids:
            raise RetirementReconcileError(f"M1 {store} contains an unapproved stale workload")
        plan[store] = {
            "add": sorted(set(expected) - set(actual)),
            "remove": sorted(stale),
            "drift": sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key]),
        }
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    plan["planDigest"] = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    return plan


def _count(plan: dict[str, Any], kind: str) -> int:
    return sum(len(plan[store][kind]) for store in STORES)


def _has_changes(plan: dict[str, Any]) -> bool:
    return any(_count(plan, kind) for kind in ("add", "remove", "drift"))


def drift_status(repo: Path) -> dict[str, Any]:
    """Read-only summary for `argus doctor`; never raises."""
    if not on_server(repo):
        return {"state": "not-applicable"}
    try:
        plan = build_plan(repo)
    except (RetirementReconcileError, OSError, sqlite3.Error):
        return {"state": "unavailable", "warning": "M1 drift could not be evaluated; run sudo argus m1 sync"}
    if not _has_changes(plan):
        return {"state": "clean"}
    counts = {kind: _count(plan, kind) for kind in ("add", "remove", "drift")}
    return {"state": "drift", "counts": counts, "warning": "M1 differs from reviewed config; run sudo argus m1 sync"}


def _off_server(error: Error, verb: str) -> dict[str, Any]:
    command = SERVER_COMMAND.format(root=SERVER_ROOT, verb=verb)
    return error(
        "m1-server-only",
        "No M1 private state exists on this machine; this command only works on the server.",
        f"Run on the server: {command}",
        exit_code=EXIT_REFUSAL,
    )


def sync_command(repo: Path, apply: bool, confirm: str, *, error: Error, success: Success) -> dict[str, Any]:
    if not on_server(repo):
        return _off_server(error, "sync")
    try:
        plan = build_plan(repo)
    except (RetirementReconcileError, OSError, sqlite3.Error) as exc:
        return error("m1-plan-refused", f"M1 plan refused: {exc}", "Resolve the named divergence with the legacy reconcile runbook.", exit_code=EXIT_REFUSAL)
    changed = _has_changes(plan)
    if not apply:
        nxt = f"Re-run with --apply --confirm {plan['planDigest']}" if changed else "No drift; nothing to apply."
        return success("m1.sync", applied=False, changes=changed, plan=plan, nextAction=nxt)
    if os.geteuid() != 0:
        return error("m1-root-required", "Applying M1 state requires root.", "Re-run with sudo on the server.", exit_code=EXIT_REFUSAL)
    if not hmac.compare_digest(confirm, plan["planDigest"]):
        return error(
            "m1-plan-digest-mismatch",
            "The confirmation does not match the freshly computed plan; nothing was changed.",
            "Review argus m1 sync output and pass its plan digest to --confirm.",
            exit_code=EXIT_REFUSAL,
            data={"command": "m1.sync", "plan": plan},
        )
    if any(plan[store]["drift"] for store in STORES) and any(plan[store]["add"] for store in STORES):
        return error(
            "m1-plan-needs-legacy-path",
            "Rows are both missing and drifted; the insert-only registration refuses drift.",
            "Resolve drift with scripts/argus-m1-reconcile-retired-workloads first, then re-run argus m1 sync.",
            exit_code=EXIT_REFUSAL,
        )
    try:
        # Acknowledgements are implied by the matching digest.
        if not any(plan[store]["drift"] for store in STORES):
            reconcile_onboarded_workloads(repo, apply=True)
        reconcile_retired_workloads(repo, apply=True)
        final = build_plan(repo)
    except (RetirementReconcileError, OSError, sqlite3.Error) as exc:
        return error("m1-apply-failed", f"M1 apply failed: {exc}", "Inspect the journal under runtime/argus/m1 and use the legacy reconcile scripts to recover.", exit_code=EXIT_INTERNAL)
    return success("m1.sync", applied=True, changes=_has_changes(final), plan=plan, nextAction="Run argus m1 verify.")


def verify_command(repo: Path, *, error: Error, success: Success) -> dict[str, Any]:
    if not on_server(repo):
        return _off_server(error, "verify --json")
    try:
        return success("m1.verify", **verify_m1_state(repo))
    except (VerificationError, OSError, sqlite3.Error) as exc:
        return error("m1-verify-failed", f"M1 verification failed: {exc}", "Run argus m1 sync to see drift.", exit_code=EXIT_INTERNAL)


def dispatch(args: Any, repo: Path, *, error: Error, success: Success) -> dict[str, Any]:
    if args.m1_command == "sync":
        return sync_command(repo, args.apply, args.confirm, error=error, success=success)
    return verify_command(repo, error=error, success=success)


def register(commands: Any, leaf: Callable[..., Any], description: Callable[..., str], parser_class: Any) -> None:
    m1 = commands.add_parser("m1", help="reconcile and verify private M1 state (server only)")
    sub = m1.add_subparsers(dest="m1_command", required=True, parser_class=parser_class)
    sync = leaf(
        sub,
        "sync",
        help_text="plan or apply registry-to-M1 convergence",
        contract=description(
            "Diff reviewed config against private M1 rows (add, remove, drift) and print a plan digest.",
            "server read-only; server mutation with --apply --confirm",
            "root on the server with private M1 state",
            "--apply registers onboarded and removes retired workloads only when --confirm matches the fresh plan digest",
            "per-store add/remove/drift ids and the plan digest",
            "argus m1 sync, then argus m1 sync --apply --confirm sha256:<digest>",
            "legacy scripts/argus-m1-reconcile-* scripts remain the fallback",
        ),
    )
    sync.add_argument("--apply", action="store_true", help="apply the plan")
    sync.add_argument("--confirm", default="", help="plan digest from the preview")
    leaf(
        sub,
        "verify",
        help_text="verify deployed M1 state",
        contract=description(
            "Verify deployed M1 private state (wraps argus-m1-verify).",
            "server read-only",
            "root on the server with private M1 state",
            "none",
            "verification summary without workload details",
            "argus m1 verify --json",
            "run argus m1 sync to see drift",
        ),
    )


def render(data: dict[str, Any], stdout: TextIO) -> None:
    if data["command"] != "m1.sync":
        print(json.dumps(data, indent=2, sort_keys=True), file=stdout)
        return
    plan = data["plan"]
    for store in STORES:
        for sign, kind in (("+", "add"), ("-", "remove"), ("~", "drift")):
            for workload_id in plan[store][kind]:
                print(f"{sign} {store} {workload_id}", file=stdout)
    print(f"PLAN_DIGEST {plan['planDigest']}", file=stdout)
    print(f"APPLIED {str(data['applied']).lower()} CHANGES {str(data['changes']).lower()}", file=stdout)
    print(f"NEXT {data['nextAction']}", file=stdout)
