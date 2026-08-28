#!/usr/bin/env python3
"""Loopback-only Argus private control API."""

from __future__ import annotations

import faulthandler
import grp
import hashlib
import json
import os
import pwd
import re
import secrets
import socketserver
import stat
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(os.environ.get("ARGUS_ROOT", Path(__file__).resolve().parents[2])).resolve()
RUNTIME = Path(os.environ.get("ARGUS_RUNTIME", ROOT / "runtime" / "argus" / "m5"))
TOKEN_FILE = Path(os.environ.get("ARGUS_TOKEN_FILE", "/etc/argus/control-token"))
OPERATORS_FILE = Path(os.environ.get("ARGUS_OPERATORS_FILE", "/etc/argus/operators.json"))
PROXY_TOKEN_FILE = Path(os.environ.get("ARGUS_PROXY_TOKEN_FILE", "/etc/argus/operator-proxy-token"))
SESSION_DB = Path(os.environ.get("ARGUS_SESSION_DB", RUNTIME / "sessions.sqlite3"))
OPERATIONS_DB = Path(
    os.environ.get("ARGUS_OPERATIONS_DB", RUNTIME / "operations.sqlite3")
)
HOST = "127.0.0.1"
PORT = int(os.environ.get("ARGUS_API_PORT", "8099"))
SESSION_COOKIE = "argus_session"
CSRF_COOKIE = "argus_csrf"
TAILSCALE_IDENTITY_HEADER = "X-Argus-Tailnet-Login"
PROXY_TOKEN_HEADER = "X-Argus-Proxy-Token"
CSRF_BOOTSTRAP_HEADER = "X-Argus-CSRF-Bootstrap"
SAFE_REQUEST_NONCE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
PREVIEW_TTL_SECONDS = 60
sys.path.insert(0, str(ROOT / "scripts"))

from argus_actions import (  # noqa: E402
    backup_preview,
    logs_preview,
    migration_preflight,
    restart_preview,
)
from argus_access_runtime import route_contract  # noqa: E402
from argus_admission import AdmissionDecision, evaluate_current  # noqa: E402
from argus_common import audit, by_id, dashboard_state, load_json, policy_decision  # noqa: E402
from argus_estate_refresh import (  # noqa: E402
    EstateRefreshError,
    create_request as create_estate_refresh_request,
    read_request as read_estate_refresh_request,
    read_status as read_estate_refresh_status,
    status_summary as estate_refresh_status,
)
from argus_ipc import request as ipc_request  # noqa: E402
from argus_migrations import (  # noqa: E402
    MigrationError,
    migration_preview,
    public_migration,
    read_draft as read_migration_draft,
)
from argus_observations import ObservationError, ObservationRepository, load_registry  # noqa: E402
from argus_operations import (  # noqa: E402
    MUTATIONS,
    PRIVILEGED_MUTATIONS,
    OperationConflict,
    OperationLedger,
    OperationValidationError,
    digest,
    parse_timestamp,
    validate_typed_parameters,
)
from argus_reconciliation import reconcile  # noqa: E402
from argus_sessions import (  # noqa: E402
    Session,
    SessionRestoration,
    SessionStore,
    parse_cookie,
    public_session,
)


DIAGNOSTIC_DELAY = os.environ.get("ARGUS_DIAGNOSTIC_TRACEBACK_SECONDS", "")
if DIAGNOSTIC_DELAY:
    faulthandler.dump_traceback_later(float(DIAGNOSTIC_DELAY), repeat=False)

SESSIONS = SessionStore(SESSION_DB)
LEDGER = OperationLedger(
    OPERATIONS_DB,
    require_existing=os.environ.get("ARGUS_LEDGER_REQUIRE_EXISTING") == "1",
    migrate_schema=os.environ.get("ARGUS_LEDGER_REQUIRE_EXISTING") != "1",
)


def bootstrap_token() -> str:
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def proxy_token() -> str:
    try:
        value = PROXY_TOKEN_FILE.read_text().strip()
    except OSError:
        return ""
    prefix = "ARGUS_OPERATOR_PROXY_TOKEN="
    return value.removeprefix(prefix).strip() if value.startswith(prefix) else value


def operator_origin() -> str:
    configured = os.environ.get("ARGUS_OPERATOR_ORIGIN", "").strip()
    if configured:
        return configured
    try:
        return str(load_json("routes.json").get("dashboard", {}).get("url", "")).rstrip("/")
    except (OSError, ValueError):
        return ""


def operator_status(identity: str) -> tuple[dict[str, str] | None, str]:
    try:
        payload = json.loads(OPERATORS_FILE.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "session-store-unavailable"
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schemaVersion", "operators"}
        or payload.get("schemaVersion") != 1
        or not isinstance(payload.get("operators"), list)
    ):
        return None, "session-store-unavailable"
    operators = payload["operators"]
    normalized = identity.strip().lower()
    for item in operators:
        if (
            not isinstance(item, dict)
            or set(item) != {"tailnetLogin", "role", "enabled"}
            or not isinstance(item["tailnetLogin"], str)
            or not isinstance(item["role"], str)
            or not isinstance(item["enabled"], bool)
        ):
            return None, "session-store-unavailable"
        login = str(item.get("tailnetLogin", "")).strip().lower()
        role = str(item.get("role", ""))
        if login == normalized and role == "owner" and item.get("enabled") is True:
            return {"identity": login, "role": role}, ""
    return None, "operator-disabled"


def enabled_operator(identity: str) -> dict[str, str] | None:
    return operator_status(identity)[0]


def trusted_login(headers: Any, peer_host: str) -> str:
    if peer_host not in {"127.0.0.1", "::1"}:
        return ""
    expected_marker = proxy_token()
    supplied_marker = str(headers.get(PROXY_TOKEN_HEADER, ""))
    if not expected_marker or not secrets.compare_digest(supplied_marker, expected_marker):
        return ""
    return str(headers.get(TAILSCALE_IDENTITY_HEADER, "")).strip().lower()


def trusted_operator(headers: Any, peer_host: str) -> dict[str, str] | None:
    identity = trusted_login(headers, peer_host)
    return enabled_operator(identity) if identity else None


def bootstrap_valid(supplied: str) -> bool:
    expected = bootstrap_token()
    return bool(expected) and secrets.compare_digest(supplied, expected)


def workload(workload_id: str) -> dict[str, Any] | None:
    return by_id().get(workload_id)


def validate_body_keys(
    body: dict[str, Any],
    allowed: set[str],
) -> None:
    unknown = set(body) - allowed
    if unknown:
        raise OperationValidationError(
            f"unknown request field(s): {','.join(sorted(unknown))}"
        )


def session_hash(session: Session) -> str:
    """Bind an authority-changing parent to one session without storing its ID."""
    return hashlib.sha256(session.session_id.encode("utf-8")).hexdigest()


def trust_domain(workload_id: str) -> str:
    classification_path = ROOT / "config" / "argus" / "workload-classification.json"
    try:
        data = json.loads(classification_path.read_text())
    except (OSError, json.JSONDecodeError):
        return "legacy-rootful"
    if isinstance(data, dict):
        classified = data.get("workloads", {})
        if isinstance(classified, dict) and isinstance(classified.get(workload_id), dict):
            return str(classified[workload_id].get("trustDomain", "legacy-rootful"))
    return "legacy-rootful"


def runtime_domain(workload_id: str) -> str:
    """Resolve effective placement from canonical seed plus fenced outcomes."""
    fallback = trust_domain(workload_id)
    manifest_path = ROOT / "workloads" / workload_id / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        migration = manifest.get("migration", {})
        seeded = migration.get("runtimeTrustDomain")
        if isinstance(seeded, str) and seeded:
            fallback = seeded
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return LEDGER.runtime_domain(workload_id, fallback)


def operation_domain(
    workload_id: str, operation_type: str, parameters: dict[str, Any]
) -> str:
    domain = runtime_domain(workload_id)
    if operation_type == "production.promote":
        return str(parameters.get("targetTrustDomain", domain))
    if operation_type == "migration.cutover":
        reference = LEDGER.get(str(parameters.get("preflightOperationId", "")))
        if reference:
            return str(reference.get("parameters", {}).get("targetTrustDomain", domain))
    if operation_type in {"migration.rollback", "production.rollback"}:
        field = (
            "cutoverOperationId"
            if operation_type == "migration.rollback"
            else "promotionOperationId"
        )
        reference = LEDGER.get(str(parameters.get(field, "")))
        if reference:
            return str(reference.get("trust_domain", domain))
    return domain


def agent_available(domain: str) -> bool:
    socket_root = Path(
        os.environ.get(
            "ARGUS_DOMAIN_SOCKET_ROOT",
            "/run/argus/domains",
        )
    )
    socket_path = socket_root / domain / "agent.sock"
    owner = "oreo" if domain == "legacy-rootful" else f"argus-{domain}"
    try:
        metadata = socket_path.stat()
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o660
            or metadata.st_uid != pwd.getpwnam(owner).pw_uid
            or metadata.st_gid != grp.getgrnam("argus-control").gr_gid
        ):
            return False
        response = ipc_request(
            str(socket_path),
            {"method": "agent.status"},
            timeout_seconds=10,
        )
    except (KeyError, OSError, RuntimeError, ValueError):
        return False
    return response == {
        "ok": True,
        "status": "available",
        "trustDomain": domain,
    }


def privileged_agent_available(domain: str) -> bool:
    socket_path = Path(os.environ.get("ARGUS_PRIVILEGED_LIFECYCLE_SOCKET", "/run/argus/privileged-lifecycle/agent.sock"))
    try:
        metadata = socket_path.stat()
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o660
            or metadata.st_uid != pwd.getpwnam("root").pw_uid
            or metadata.st_gid != grp.getgrnam("argus-control").gr_gid
        ):
            return False
        response = ipc_request(str(socket_path), {"method": "agent.status", "trustDomain": domain}, timeout_seconds=10)
    except (KeyError, OSError, RuntimeError, ValueError):
        return False
    return response == {"ok": True, "status": "available", "trustDomain": domain}


def confirmation_phrase(
    workload_id: str,
    operation_type: str,
    parameters: dict[str, Any],
    trust_domain_id: str = "",
) -> str:
    phrases = {
        "workload.restart": workload_id,
        "backup.create": workload_id,
        "access.apply": workload_id,
        "workload.deploy": f"deploy {workload_id} {parameters.get('targetRevision', '')}",
        "workload.start": f"start {workload_id}",
        "workload.stop": f"stop {workload_id}",
        "backup.restore": f"restore {workload_id} {parameters.get('artifactId', '')}",
        "migration.cutover": f"migrate {workload_id} to {trust_domain_id}",
        "migration.rollback": f"rollback migration {workload_id}",
        "production.promote": f"promote {workload_id} to production",
        "production.rollback": f"rollback production {workload_id}",
    }
    return phrases.get(operation_type, "")


def private_dashboard_state() -> dict[str, Any]:
    state = dashboard_state()
    active_domains: set[str] = set()
    domain_availability: dict[str, bool] = {}
    for node in state.get("topology", {}).get("nodes", []):
        if node.get("kind") != "workload":
            continue
        declared = str(node.get("trustDomain", "legacy-rootful"))
        domain = runtime_domain(str(node.get("id", "")))
        node["runtimeTrustDomain"] = domain
        node["placementDrift"] = domain != declared
        if domain not in domain_availability:
            domain_availability[domain] = agent_available(domain)
        available = domain_availability[domain]
        node["agentAvailable"] = available
        if available:
            active_domains.add(domain)
    state.get("topology", {}).get("summary", {})["domainAgentsAvailable"] = len(active_domains)
    state["reconciliation"] = estate_reconciliation()
    state["estateRefresh"] = estate_refresh_status(ROOT)
    return state


def estate_reconciliation() -> dict[str, Any]:
    """Return only the current sanitized configured-estate decision evidence."""
    registry_path = ROOT / "config" / "argus" / "observation-sources.json"
    database = Path(
        os.environ.get(
            "ARGUS_OBSERVATIONS_DB",
            ROOT / "runtime" / "argus" / "observations.sqlite3",
        )
    )
    try:
        registry = load_registry(registry_path, ROOT)
        if not database.is_file():
            raise OSError("observation repository is unavailable")
        with ObservationRepository(database, read_only=True) as repository:
            return reconcile(ROOT, repository, registry)
    except (ObservationError, OSError, ValueError):
        return {
            "schemaVersion": 1,
            "status": "unavailable",
            "observationState": "incomplete",
            "coverage": {
                "status": "not-configured",
                "configuredSources": 0,
                "freshSources": 0,
                "sources": [],
            },
            "workloads": [],
            "blockers": [{"code": "observation-repository-unavailable"}],
            "safeToMoveWorkloads": False,
            "mutationAuthority": "none",
        }


def operation_preview(workload_id: str, operation_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
    validate_typed_parameters(operation_type, parameters)
    admission = evaluate_current(ROOT, workload_id, operation_type)
    item = (
        None
        if admission.decision_code in {"dependency-unavailable", "unknown-workload"}
        else workload(workload_id)
    )
    domain = (
        "legacy-rootful"
        if admission.decision_code == "dependency-unavailable"
        else operation_domain(workload_id, operation_type, parameters)
    )
    revision = admission.revision
    allowed, reason = operation_policy(
        workload_id,
        operation_type,
        parameters,
        _admission=admission,
    )
    rollback = {
        "health.refresh": "No mutation; no rollback required.",
        "logs.preview": "No mutation; no rollback required.",
        "migration.preflight": "No mutation; no rollback required.",
        "workload.deploy": "Apply the previously pinned revision as a new operation.",
        "workload.start": "Stop the workload as a new audited operation.",
        "workload.stop": "Start the same pinned revision as a new audited operation.",
        "backup.restore": "Live state is unchanged; discard the isolated recovery candidate.",
        "migration.cutover": "Create migration.rollback linked to this cutover operation.",
        "migration.rollback": "A new preflight and cutover are required to migrate again.",
        "production.promote": "Create production.rollback linked to this promotion.",
        "production.rollback": "A new health gate and promotion are required.",
        "workload.restart": "Restart is not data-destructive; investigate and restart the previous canonical revision.",
        "backup.create": "No live-state rollback; remove the failed or unwanted artifact through retention tooling.",
        "access.apply": "Apply the previously effective none/local/tailnet state as a new audited operation.",
    }.get(operation_type, "Unavailable.")
    impact = {
        "workload.restart": "Brief workload unavailability while the approved service restarts.",
        "backup.create": "Possible workload I/O load; service remains available.",
        "access.apply": "Reachability changes only for this workload.",
        "workload.deploy": "Brief private workload replacement while the pinned revision starts.",
        "workload.start": "Starts only the approved private workload.",
        "workload.stop": "Stops only the approved private workload.",
        "backup.restore": "I/O occurs only in an isolated recovery directory.",
        "migration.cutover": "Fences the source before starting the private target.",
        "migration.rollback": "Stops the target and restores the proven source placement.",
        "production.promote": "Fences sandbox source before starting private production.",
        "production.rollback": "Stops private production and restores the proven source.",
    }.get(operation_type, "No availability impact.")
    preview = {
        "workloadId": workload_id,
        "trustDomain": domain,
        "operationType": operation_type,
        "parameters": parameters,
        "expectedRevision": revision,
        "policyVersion": admission.policy_version,
    }
    result = {
        **preview,
        "allowed": allowed,
        "reason": reason,
        "admission": admission.as_dict(),
        "previewDigest": digest(preview),
        "expectedBlastRadius": impact,
        "healthChecks": ["canonical revision recheck", "workload health policy check"],
        "rollbackBehavior": rollback,
        "confirmationPhrase": confirmation_phrase(
            workload_id, operation_type, parameters, domain
        ),
    }
    if operation_type == "logs.preview" and result["allowed"]:
        log_result = logs_preview(workload_id, max_lines=int(parameters.get("maxLines", 100)))
        result["sanitizedLogs"] = log_result.get("lines", [])
        result["redacted"] = True
    if operation_type == "health.refresh" and item:
        result["currentHealth"] = item.get("health", {})
        result["evidenceFreshness"] = item.get("migration", {}).get("lastHealthCheck", "")
    if operation_type == "migration.preflight" and item:
        assessment = migration_preflight(workload_id, record_audit=False)
        result["migrationReadiness"] = {
            key: assessment.get(key)
            for key in (
                "readyForCutover",
                "blockers",
                "migrationStatus",
                "sourcePathRecorded",
                "targetPath",
                "composeProject",
                "backupApproved",
                "restoreApproved",
                "restoreTested",
                "backupArtifactVerified",
                "backupArtifactId",
                "healthVerified",
                "rollbackRecorded",
            )
        }
    return result


def operation_policy(
    workload_id: str,
    operation_type: str,
    parameters: dict[str, Any],
    *,
    _admission: AdmissionDecision | None = None,
) -> tuple[bool, str]:
    if operation_type in {
        "migration.cutover",
        "migration.rollback",
        "production.promote",
        "production.rollback",
    }:
        return False, "migration kernel required"
    admission = _admission or evaluate_current(
        ROOT,
        workload_id,
        operation_type,
    )
    if not admission.allowed:
        return False, admission.decision_code
    item = workload(workload_id)
    if item is None:
        return False, "unknown-workload"
    declared_domain = trust_domain(workload_id)
    effective_domain = runtime_domain(workload_id)
    domain = operation_domain(workload_id, operation_type, parameters)
    if operation_type == "production.promote":
        target = str(parameters.get("targetTrustDomain", ""))
        if target != declared_domain or not target.endswith("-managed"):
            return False, "target trust domain must match canonical managed classification"
        if target == effective_domain:
            return False, "workload is already placed in the canonical managed domain"
    available = privileged_agent_available(domain) if operation_type in PRIVILEGED_MUTATIONS else agent_available(domain)
    if not available:
        return False, f"{domain} domain agent unavailable"
    if operation_type == "health.refresh":
        if item.get("actions", {}).get("sandboxReconcileOnly") is True:
            return False, "health refresh disabled by workload policy"
        manifest_path = ROOT / "workloads" / workload_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        runtime = manifest.get("runtime", item.get("runtime", {}))
        allowed = bool(item.get("health", {}).get("enabled", False)) or (
            effective_domain != "legacy-rootful" and runtime.get("type") == "docker-compose"
        )
        return allowed, "health check not configured"
    if operation_type == "logs.preview":
        preview = logs_preview(workload_id, max_lines=int(parameters.get("maxLines", 100)))
        return bool(preview.get("allowed")), str(preview.get("reason", "logs disabled by manifest"))
    if operation_type == "migration.preflight":
        preview = migration_preflight(workload_id, record_audit=False)
        allowed = bool(preview.get("allowed"))
        if allowed:
            target = str(parameters.get("targetTrustDomain", ""))
            if target != declared_domain or not target.endswith("-managed"):
                return False, "target trust domain must match canonical managed classification"
            if target == effective_domain:
                return False, "workload is already placed in the canonical managed domain"
        return allowed, (
            "migration preflight enabled by manifest"
            if allowed
            else str(preview.get("reason", "migration preflight disabled by manifest"))
        )
    if operation_type in {"workload.deploy", "workload.start", "workload.stop", "backup.restore"}:
        return domain != "legacy-rootful", "lifecycle operation requires a sealed trust domain"
    if operation_type in PRIVILEGED_MUTATIONS:
        return True, "privileged lifecycle broker available; durable dependency checks apply"
    if operation_type == "workload.restart":
        preview = restart_preview(workload_id)
        return bool(preview.get("allowed")), str(preview.get("reason", "restart disabled by manifest"))
    if operation_type == "backup.create":
        preview = backup_preview(workload_id)
        return bool(preview.get("allowed")), str(preview.get("reason") or preview.get("summary", "backup disabled"))
    if operation_type == "access.apply":
        if item.get("actions", {}).get("sandboxReconcileOnly") is True:
            return False, "access mutation disabled by workload policy"
        desired = str(parameters.get("desired", ""))
        if desired not in {"none", "local", "tailnet"}:
            return False, "Phase 1 access state must be none, local, or tailnet"
        if desired == "tailnet":
            _, route_reason = route_contract(ROOT, item, workload_id)
            if route_reason:
                return False, route_reason
        decision = policy_decision(workload_id, desired)
        return bool(decision.get("allowed")), str(decision.get("reason", "access policy denied"))
    return False, "unsupported typed operation"


class Handler(BaseHTTPRequestHandler):
    server_version = "ArgusControl/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} {self.command} {urlparse(self.path).path} {fmt % args}")

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > 131072:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(length))

    def send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | list[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        header_items = headers.items() if isinstance(headers, dict) else (headers or [])
        for key, value in header_items:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def peer_host(self) -> str:
        address = getattr(self, "client_address", ("", 0))
        return str(address[0]) if address else ""

    def operator(self) -> dict[str, str] | None:
        return trusted_operator(self.headers, self.peer_host())

    def origin_valid(self) -> bool:
        expected = operator_origin()
        supplied = str(self.headers.get("Origin", "")).rstrip("/")
        return bool(expected) and secrets.compare_digest(supplied, expected)

    def current_session(self) -> Session | None:
        return self.session_restoration().session

    def session_restoration(self) -> SessionRestoration:
        identity = trusted_login(self.headers, self.peer_host())
        if not identity:
            return SessionRestoration(None, "identity-missing")
        operator, reason = operator_status(identity)
        if operator is None:
            if reason == "operator-disabled":
                SESSIONS.revoke_identity(identity)
            return SessionRestoration(None, reason)
        session_id = parse_cookie(self.headers.get("Cookie", "")).get(SESSION_COOKIE, "")
        return SESSIONS.restore(session_id, operator["identity"], role=operator["role"])

    def require_session(self, *, csrf: bool = False, step_up: bool = False) -> Session | None:
        session = self.current_session()
        if session is None:
            self.send_json(401, {"error": "verified tailnet identity and Argus session required"})
            return None
        cookies = parse_cookie(self.headers.get("Cookie", ""))
        session_id = cookies.get(SESSION_COOKIE, "")
        if csrf:
            cookie_token = cookies.get(CSRF_COOKIE, "")
            header_token = str(self.headers.get("X-Argus-CSRF", ""))
            if (
                not cookie_token
                or not header_token
                or not secrets.compare_digest(cookie_token, header_token)
                or not SESSIONS.csrf_valid(session_id, header_token)
            ):
                self.send_json(403, {"error": "CSRF validation failed"})
                return None
        if step_up and not session.step_up_valid:
            self.send_json(403, {"error": "step-up reauthentication required"})
            return None
        return session

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.handle_get()
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"error": exc.__class__.__name__})

    def handle_get(self) -> None:
        path = urlparse(self.path).path
        operation_match = re.fullmatch(r"/api/operations/([0-9a-f-]+)", path)
        workload_operations_match = re.fullmatch(r"/api/workloads/([^/]+)/operations", path)
        migration_match = re.fullmatch(r"/api/migrations/([0-9a-f-]{36})", path)
        workload_migrations_match = re.fullmatch(
            r"/api/workloads/([^/]+)/migrations", path
        )
        estate_refresh_match = re.fullmatch(
            r"/api/estate/refresh/(refresh-[0-9a-f-]{36})", path
        )
        if path == "/api/session":
            restoration = self.session_restoration()
            if restoration.session:
                self.send_json(200, public_session(restoration.session))
            else:
                self.send_json(
                    401,
                    {"authenticated": False, "reason": restoration.reason},
                )
        elif operation_match:
            if not self.require_session():
                return
            operation = LEDGER.get(operation_match.group(1))
            self.send_json(200 if operation else 404, operation or {"error": "not found"})
        elif workload_operations_match:
            if not self.require_session():
                return
            self.send_json(200, {"operations": LEDGER.list_for_workload(workload_operations_match.group(1))})
        elif migration_match:
            session = self.require_session()
            if not session:
                return
            migration = LEDGER.get_migration(migration_match.group(1))
            if migration is None:
                self.send_json(404, {"error": "not found"})
            elif migration.get("requested_by") != session.identity:
                self.send_json(403, {"error": "migration belongs to another operator"})
            else:
                self.send_json(200, public_migration(migration))
        elif workload_migrations_match:
            session = self.require_session()
            if not session:
                return
            migrations = [
                public_migration(migration)
                for migration in LEDGER.list_migrations_for_workload(
                    workload_migrations_match.group(1)
                )
                if migration.get("requested_by") == session.identity
            ]
            self.send_json(200, {"migrations": migrations})
        elif path == "/api/estate/coverage":
            if not self.require_session():
                return
            self.send_json(
                200,
                {
                    "reconciliation": estate_reconciliation(),
                    "refresh": estate_refresh_status(ROOT),
                },
            )
        elif estate_refresh_match:
            if not self.require_session():
                return
            status = (
                read_estate_refresh_status(ROOT, estate_refresh_match.group(1))
                or read_estate_refresh_request(ROOT, estate_refresh_match.group(1))
            )
            self.send_json(200 if status else 404, status or {"error": "not found"})
        elif path == "/api/dashboard-state":
            self.send_json(200, private_dashboard_state())
        elif path == "/api/workloads":
            state = private_dashboard_state()
            self.send_json(200, {key: state[key] for key in ["workloads", "routes", "exposure", "events"]})
        elif path == "/api/metrics":
            metrics = ROOT / "control-plane" / "dashboard" / "public" / "metrics.json"
            self.send_json(200, json.loads(metrics.read_text()) if metrics.exists() else {"error": "metrics unavailable"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.handle_post()
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid json"})
        except OperationValidationError as exc:
            self.send_json(422, {"error": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except OperationConflict as exc:
            self.send_json(409, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self.send_json(500, {"error": exc.__class__.__name__})

    def handle_post(self) -> None:
        path = urlparse(self.path).path
        if not self.origin_valid():
            self.send_json(403, {"error": "trusted operator origin required"})
            return
        body = self.read_body()
        if path == "/api/session/exchange":
            validate_body_keys(body, {"bootstrapToken"})
            self.handle_session_exchange(body)
            return
        if path == "/api/session/logout":
            validate_body_keys(body, set())
            session = self.require_session(csrf=True)
            if not session:
                return
            session_id = parse_cookie(self.headers.get("Cookie", "")).get(SESSION_COOKIE, "")
            SESSIONS.revoke(session_id)
            self.send_json(
                204,
                {},
                headers=[
                    ("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"),
                    ("Set-Cookie", f"{CSRF_COOKIE}=; Path=/; Max-Age=0; Secure; SameSite=Strict"),
                ],
            )
            return
        if path == "/api/session/step-up":
            validate_body_keys(body, {"bootstrapToken"})
            session = self.require_session(csrf=True)
            if not session:
                return
            if not bootstrap_valid(str(body.get("bootstrapToken", ""))):
                self.send_json(401, {"error": "step-up credential rejected"})
                return
            session_id = parse_cookie(self.headers.get("Cookie", "")).get(SESSION_COOKIE, "")
            if not SESSIONS.step_up(session_id):
                self.send_json(409, {"error": "session changed during step-up"})
                return
            self.send_json(200, {"ok": True})
            return
        preview_match = re.fullmatch(r"/api/workloads/([^/]+)/operations/preview", path)
        create_match = re.fullmatch(r"/api/workloads/([^/]+)/operations", path)
        migration_preview_match = re.fullmatch(
            r"/api/workloads/([^/]+)/migration/preview", path
        )
        migration_create_match = re.fullmatch(
            r"/api/workloads/([^/]+)/migrations", path
        )
        migration_approve_match = re.fullmatch(
            r"/api/migrations/([0-9a-f-]{36})/approve", path
        )
        migration_cancel_match = re.fullmatch(
            r"/api/migrations/([0-9a-f-]{36})/cancel", path
        )
        migration_rollback_match = re.fullmatch(
            r"/api/migrations/([0-9a-f-]{36})/rollback", path
        )
        migration_draft_adopt_match = re.fullmatch(
            r"/api/migration-drafts/(draft-[0-9a-f-]{36})/adopt", path
        )
        approve_match = re.fullmatch(r"/api/operations/([0-9a-f-]+)/approve", path)
        cancel_match = re.fullmatch(r"/api/operations/([0-9a-f-]+)/cancel", path)
        legacy_action_match = re.fullmatch(r"/api/workloads/([^/]+)/(logs|restart|backup)/(preview|apply)", path)
        legacy_access_match = re.fullmatch(r"/api/workloads/([^/]+)/access/(preview|apply)", path)
        compatibility_apply = bool(
            legacy_action_match and legacy_action_match.group(3) == "apply"
            or legacy_access_match and legacy_access_match.group(2) == "apply"
        )
        session = self.require_session(
            csrf=True,
            step_up=(
                bool(approve_match)
                or bool(migration_approve_match)
                or bool(migration_rollback_match)
                or compatibility_apply
            ),
        )
        if not session:
            return
        if path == "/api/estate/refresh":
            validate_body_keys(body, set())
            self.handle_estate_refresh_create(session)
        elif path == "/api/workloads/discover":
            validate_body_keys(body, set())
            self.handle_workload_discover()
        elif migration_preview_match:
            validate_body_keys(body, set())
            self.handle_migration_preview(migration_preview_match.group(1))
        elif migration_create_match:
            validate_body_keys(
                body,
                {
                    "targetTrustDomain",
                    "previewDigest",
                    "expectedRevision",
                    "policyVersion",
                    "observationDigest",
                },
            )
            self.handle_migration_create(migration_create_match.group(1), session, body)
        elif migration_approve_match:
            validate_body_keys(body, {"confirmation"})
            self.handle_migration_approve(
                migration_approve_match.group(1), session, body
            )
        elif migration_cancel_match:
            validate_body_keys(body, set())
            self.handle_migration_cancel(migration_cancel_match.group(1), session)
        elif migration_rollback_match:
            validate_body_keys(body, {"confirmation"})
            self.handle_migration_rollback(
                migration_rollback_match.group(1), session, body
            )
        elif migration_draft_adopt_match:
            validate_body_keys(body, set())
            self.handle_migration_draft_adopt(
                migration_draft_adopt_match.group(1), session
            )
        elif preview_match:
            validate_body_keys(body, {"operationType", "parameters"})
            operation_type = str(body.get("operationType", ""))
            if not isinstance(body.get("parameters", {}), dict):
                raise OperationValidationError("parameters must be an object")
            parameters = dict(body.get("parameters") or {})
            self.send_json(200, operation_preview(preview_match.group(1), operation_type, parameters))
        elif create_match:
            validate_body_keys(
                body,
                {
                    "operationType",
                    "parameters",
                    "previewDigest",
                    "expectedRevision",
                    "policyVersion",
                },
            )
            self.handle_operation_create(create_match.group(1), session, body)
        elif approve_match:
            validate_body_keys(body, {"confirmation"})
            self.handle_operation_approve(approve_match.group(1), session, body)
        elif cancel_match:
            validate_body_keys(body, set())
            self.handle_operation_cancel(cancel_match.group(1), session)
        elif legacy_action_match:
            workload_id, action, phase = legacy_action_match.groups()
            operation_type = {"logs": "logs.preview", "restart": "workload.restart", "backup": "backup.create"}[action]
            if phase == "preview":
                validate_body_keys(body, set())
                self.send_json(200, operation_preview(workload_id, operation_type, {}))
            else:
                validate_body_keys(body, {"confirmation"})
                self.handle_compatibility_apply(workload_id, operation_type, session, body)
        elif legacy_access_match:
            workload_id, phase = legacy_access_match.groups()
            validate_body_keys(
                body,
                {"desired"} if phase == "preview" else {"desired", "confirmation"},
            )
            parameters = {"desired": str(body.get("desired", ""))}
            if phase == "preview":
                self.send_json(200, operation_preview(workload_id, "access.apply", parameters))
            else:
                self.handle_compatibility_apply(workload_id, "access.apply", session, body, parameters=parameters)
        else:
            self.send_json(404, {"error": "not found"})

    def handle_estate_refresh_create(self, session: Session) -> None:
        try:
            request = create_estate_refresh_request(ROOT, requested_by=session.identity)
        except (EstateRefreshError, OSError):
            self.send_json(
                503,
                {
                    "error": "estate refresh request unavailable",
                    "safeToMoveWorkloads": False,
                },
            )
            return
        audit("estate.refresh.request", "-", "ok", actor=session.identity, runId=request["runId"])
        self.send_json(
            202,
            {
                "request": request,
                "reconciliation": estate_reconciliation(),
                "safeToMoveWorkloads": False,
            },
        )

    def handle_workload_discover(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "argus-workload-discover"), "--json"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=30,
        )
        if result.returncode != 0:
            self.send_json(500, {"ok": False, "error": "discovery failed"})
            return
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.send_json(500, {"ok": False, "error": "invalid discovery output"})
            return
        self.send_json(200, {"ok": True, **report})

    def handle_migration_preview(self, workload_id: str) -> None:
        self.send_json(200, migration_preview(ROOT, LEDGER, workload_id))

    def handle_migration_create(
        self, workload_id: str, session: Session, body: dict[str, Any]
    ) -> None:
        preview = migration_preview(ROOT, LEDGER, workload_id)
        if not preview.get("eligible"):
            self.send_json(403, preview)
            return
        bound_fields = (
            "previewDigest",
            "expectedRevision",
            "policyVersion",
            "observationDigest",
            "targetTrustDomain",
        )
        if any(body.get(field) != preview.get(field) for field in bound_fields):
            self.send_json(409, {"error": "migration preview or evidence is stale"})
            return
        idempotency_key = str(self.headers.get("Idempotency-Key", ""))
        if not idempotency_key:
            self.send_json(400, {"error": "idempotency key required"})
            return
        migration, created = LEDGER.create_migration(
            workload_id=workload_id,
            source_trust_domain=str(preview["sourceTrustDomain"]),
            target_trust_domain=str(preview["targetTrustDomain"]),
            requested_by=session.identity,
            originating_session_hash=session_hash(session),
            preview=preview,
            preview_digest=str(preview["previewDigest"]),
            expected_revision=str(preview["expectedRevision"]),
            policy_version=str(preview["policyVersion"]),
            observation_digest=str(preview["observationDigest"]),
            idempotency_key=idempotency_key,
        )
        if created:
            audit(
                "migration.intent",
                workload_id,
                "ok",
                actor=session.identity,
                migrationId=migration["migration_id"],
            )
        self.send_json(202, public_migration(migration))

    def handle_migration_approve(
        self, migration_id: str, session: Session, body: dict[str, Any]
    ) -> None:
        migration = LEDGER.get_migration(migration_id)
        if migration is None:
            self.send_json(404, {"error": "not found"})
            return
        if (
            migration.get("requested_by") != session.identity
            or migration.get("originating_session_hash") != session_hash(session)
        ):
            self.send_json(403, {"error": "migration approval requires the originating session"})
            return
        expected_confirmation = str(
            migration.get("preview", {}).get("confirmationPhrase", "")
        )
        if str(body.get("confirmation", "")) != expected_confirmation:
            self.send_json(403, {"error": "exact migration preview confirmation required"})
            return
        if int(time.time()) - parse_timestamp(str(migration["created_at"])) >= PREVIEW_TTL_SECONDS:
            migration = LEDGER.transition_migration(
                migration_id,
                {"awaiting-approval"},
                "expired",
                finished_at=int(time.time()),
                error_class="preview-expired",
                redacted_summary="Migration preview expired before dashboard approval.",
                event_detail="Approval rejected because the migration preview expired.",
            )
            self.send_json(410, public_migration(migration))
            return
        current = migration_preview(ROOT, LEDGER, str(migration["workload_id"]))
        fields = {
            "previewDigest": migration.get("preview_digest"),
            "expectedRevision": migration.get("expected_revision"),
            "policyVersion": migration.get("policy_version"),
            "observationDigest": migration.get("observation_digest"),
            "sourceTrustDomain": migration.get("source_trust_domain"),
            "targetTrustDomain": migration.get("target_trust_domain"),
        }
        if not current.get("eligible") or any(
            current.get(field) != value for field, value in fields.items()
        ):
            migration = LEDGER.transition_migration(
                migration_id,
                {"awaiting-approval"},
                "expired",
                finished_at=int(time.time()),
                error_class="preview-stale",
                redacted_summary="Migration source, target, policy, or observation evidence changed before approval.",
                event_detail="Approval rejected after migration preview drift.",
            )
            self.send_json(409, public_migration(migration))
            return
        migration = LEDGER.approve_migration(
            migration_id,
            requested_by=session.identity,
            originating_session_hash=session_hash(session),
        )
        audit(
            "migration.approved",
            str(migration["workload_id"]),
            "ok",
            actor=session.identity,
            migrationId=migration_id,
        )
        self.send_json(202, public_migration(migration))

    def handle_migration_cancel(self, migration_id: str, session: Session) -> None:
        migration = LEDGER.get_migration(migration_id)
        if migration is None:
            self.send_json(404, {"error": "not found"})
            return
        if (
            migration.get("requested_by") != session.identity
            or migration.get("originating_session_hash") != session_hash(session)
        ):
            self.send_json(403, {"error": "migration cancellation requires the originating session"})
            return
        migration = LEDGER.cancel_migration(
            migration_id,
            requested_by=session.identity,
            originating_session_hash=session_hash(session),
        )
        audit(
            "migration.cancelled",
            str(migration["workload_id"]),
            "ok",
            actor=session.identity,
            migrationId=migration_id,
        )
        self.send_json(202, public_migration(migration))

    def handle_migration_rollback(
        self, migration_id: str, session: Session, body: dict[str, Any]
    ) -> None:
        migration = LEDGER.get_migration(migration_id)
        if migration is None:
            self.send_json(404, {"error": "not found"})
            return
        if (
            migration.get("requested_by") != session.identity
            or migration.get("originating_session_hash") != session_hash(session)
        ):
            self.send_json(403, {"error": "migration rollback requires the originating session"})
            return
        expected_confirmation = str(
            migration.get("preview", {}).get("rollbackConfirmationPhrase", "")
        )
        if str(body.get("confirmation", "")) != expected_confirmation:
            self.send_json(403, {"error": "exact migration rollback confirmation required"})
            return
        migration = LEDGER.begin_migration_rollback(
            migration_id,
            requested_by=session.identity,
            originating_session_hash=session_hash(session),
        )
        audit(
            "migration.rollback-approved",
            str(migration["workload_id"]),
            "ok",
            actor=session.identity,
            migrationId=migration_id,
        )
        self.send_json(202, public_migration(migration))

    def handle_migration_draft_adopt(self, draft_id: str, session: Session) -> None:
        draft = read_migration_draft(ROOT, draft_id)
        if draft is None:
            self.send_json(404, {"error": "migration draft not found"})
            return
        if draft.get("state") == "expired":
            self.send_json(410, {"error": "migration draft expired"})
            return
        workload_id = str(draft["workloadId"])
        if draft.get("action") == "rollback":
            migration = LEDGER.get_migration(str(draft.get("migrationId", "")))
            if migration is None:
                self.send_json(404, {"error": "draft migration not found"})
                return
            if migration.get("requested_by") != session.identity:
                self.send_json(403, {"error": "draft migration belongs to another operator"})
                return
            self.send_json(
                200,
                {
                    "draft": draft,
                    "migration": public_migration(migration),
                    "nextAction": "dashboard-step-up-and-exact-rollback-confirmation",
                },
            )
            return
        preview = migration_preview(ROOT, LEDGER, workload_id)
        fields = (
            "previewDigest",
            "expectedRevision",
            "policyVersion",
            "observationDigest",
            "sourceTrustDomain",
            "targetTrustDomain",
        )
        if not preview.get("eligible") or any(
            draft.get(field) != preview.get(field) for field in fields
        ):
            self.send_json(409, {"error": "migration draft evidence is stale", "preview": preview})
            return
        migration, created = LEDGER.create_migration(
            workload_id=workload_id,
            source_trust_domain=str(preview["sourceTrustDomain"]),
            target_trust_domain=str(preview["targetTrustDomain"]),
            requested_by=session.identity,
            originating_session_hash=session_hash(session),
            preview=preview,
            preview_digest=str(preview["previewDigest"]),
            expected_revision=str(preview["expectedRevision"]),
            policy_version=str(preview["policyVersion"]),
            observation_digest=str(preview["observationDigest"]),
            idempotency_key=f"draft:{draft_id}",
        )
        if created:
            audit(
                "migration.draft-adopted",
                workload_id,
                "ok",
                actor=session.identity,
                migrationId=migration["migration_id"],
            )
        self.send_json(202, {"draft": draft, "migration": public_migration(migration)})

    def handle_compatibility_apply(
        self, workload_id: str, operation_type: str, session: Session, body: dict[str, Any],
        *, parameters: dict[str, Any] | None = None,
    ) -> None:
        if str(body.get("confirmation", "")) != workload_id:
            self.send_json(403, {"error": "typed workload confirmation required"})
            return
        approved_parameters = parameters or {}
        preview = operation_preview(workload_id, operation_type, approved_parameters)
        if not preview["allowed"]:
            self.send_json(403, preview)
            return
        idempotency_key = str(
            self.headers.get("Idempotency-Key") or f"compat-{uuid.uuid4()}"
        )
        if not SESSIONS.reserve_operation(idempotency_key, session.session_id):
            self.send_json(409, {"error": "idempotency key is bound to another session"})
            return
        operation, created = LEDGER.create(
            workload_id=workload_id,
            trust_domain=preview["trustDomain"],
            operation_type=operation_type,
            requested_by=session.identity,
            parameters=approved_parameters,
            preview_digest=preview["previewDigest"],
            expected_revision=preview["expectedRevision"],
            policy_version=preview["policyVersion"],
            idempotency_key=idempotency_key,
            preview=preview,
        )
        operation_id = str(operation["operation_id"])
        session_bound = SESSIONS.bind_operation(
            operation_id,
            session.session_id,
        ) or SESSIONS.operation_bound_to(
            operation_id,
            session.session_id,
            idempotency_key=idempotency_key,
        )
        if not session_bound:
            if created:
                LEDGER.transition(
                    operation_id,
                    {str(operation["state"])},
                    "denied",
                    finished_at=int(time.time()),
                    error_class="session-binding-failed",
                    redacted_summary="Operation session binding failed before approval.",
                )
            self.send_json(409, {"error": "operation is bound to another session"})
            return
        if created:
            audit("operation.intent", workload_id, "ok", actor=session.identity, operationId=operation_id, operationType=operation_type)
            operation = LEDGER.transition(
                operation_id,
                {"awaiting-approval"},
                "queued",
                approved_at=int(time.time()),
            )
        self.send_json(202, operation)

    def handle_session_exchange(self, body: dict[str, Any]) -> None:
        operator = self.operator()
        nonce = str(self.headers.get(CSRF_BOOTSTRAP_HEADER, ""))
        if (
            operator is None
            or not SAFE_REQUEST_NONCE.fullmatch(nonce)
            or not bootstrap_valid(str(body.get("bootstrapToken", "")))
        ):
            self.send_json(401, {"error": "verified tailnet identity and bootstrap credential required"})
            return
        session = SESSIONS.create(operator["identity"], role=operator["role"])
        audit("session.exchange", "-", "ok", actor=operator["identity"])
        self.send_json(
            201,
            public_session(session),
            headers=[
                (
                    "Set-Cookie",
                    f"{SESSION_COOKIE}={session.session_id}; Path=/; Max-Age=28800; HttpOnly; Secure; SameSite=Strict",
                ),
                (
                    "Set-Cookie",
                    f"{CSRF_COOKIE}={session.csrf_token}; Path=/; Max-Age=28800; Secure; SameSite=Strict",
                ),
            ],
        )

    def handle_operation_create(self, workload_id: str, session: Session, body: dict[str, Any]) -> None:
        operation_type = str(body.get("operationType", ""))
        parameters = dict(body.get("parameters") or {})
        preview = operation_preview(workload_id, operation_type, parameters)
        if not preview["allowed"]:
            self.send_json(403, preview)
            return
        if (
            body.get("previewDigest") != preview["previewDigest"]
            or body.get("expectedRevision") != preview["expectedRevision"]
            or body.get("policyVersion") != preview["policyVersion"]
        ):
            self.send_json(409, {"error": "preview or canonical revision is stale"})
            return
        idempotency_key = str(self.headers.get("Idempotency-Key", ""))
        if not idempotency_key:
            self.send_json(400, {"error": "idempotency key required"})
            return
        if not SESSIONS.reserve_operation(idempotency_key, session.session_id):
            self.send_json(409, {"error": "idempotency key is bound to another session"})
            return
        operation, created = LEDGER.create(
            workload_id=workload_id,
            trust_domain=preview["trustDomain"],
            operation_type=operation_type,
            requested_by=session.identity,
            parameters=parameters,
            preview_digest=preview["previewDigest"],
            expected_revision=preview["expectedRevision"],
            policy_version=preview["policyVersion"],
            idempotency_key=idempotency_key,
            preview=preview,
        )
        operation_id = str(operation["operation_id"])
        session_bound = SESSIONS.bind_operation(
            operation_id,
            session.session_id,
        ) or SESSIONS.operation_bound_to(
            operation_id,
            session.session_id,
            idempotency_key=idempotency_key,
        )
        if not session_bound:
            if created:
                LEDGER.transition(
                    operation_id,
                    {str(operation["state"])},
                    "denied",
                    finished_at=int(time.time()),
                    error_class="session-binding-failed",
                    redacted_summary="Operation session binding failed before approval.",
                )
            self.send_json(409, {"error": "operation is bound to another session"})
            return
        audit("operation.intent", workload_id, "ok", actor=session.identity, operationId=operation["operation_id"], operationType=operation_type)
        self.send_json(202, operation)

    def handle_operation_approve(self, operation_id: str, session: Session, body: dict[str, Any]) -> None:
        operation = LEDGER.get(operation_id)
        if not operation:
            self.send_json(404, {"error": "not found"})
            return
        if operation["requested_by"] != session.identity:
            self.send_json(403, {"error": "operation belongs to another operator"})
            return
        if not SESSIONS.operation_bound_to(
            operation_id,
            session.session_id,
            idempotency_key=str(operation["idempotency_key"]),
        ):
            self.send_json(403, {"error": "operation approval requires the originating session"})
            return
        expected_confirmation = str(operation.get("preview", {}).get("confirmationPhrase", ""))
        if str(body.get("confirmation", "")) != expected_confirmation:
            self.send_json(403, {"error": "exact preview confirmation required"})
            return
        if int(time.time()) - parse_timestamp(str(operation["created_at"])) >= PREVIEW_TTL_SECONDS:
            LEDGER.transition(
                operation_id,
                {"awaiting-approval"},
                "expired",
                finished_at=int(time.time()),
                error_class="preview-expired",
                redacted_summary="Preview expired before approval.",
                event_detail="Approval rejected because the preview expired.",
            )
            self.send_json(410, {"error": "preview expired; create a new operation"})
            return
        current_preview = operation_preview(
            str(operation["workload_id"]),
            str(operation["operation_type"]),
            dict(operation["parameters"]),
        )
        if (
            operation["expected_revision"] != current_preview["expectedRevision"]
            or operation["policy_version"] != current_preview["policyVersion"]
            or operation["preview_digest"] != current_preview["previewDigest"]
        ):
            LEDGER.transition(
                operation_id,
                {"awaiting-approval"},
                "expired",
                finished_at=int(time.time()),
                error_class="preview-stale",
                redacted_summary="Canonical revision, policy, or preview changed before approval.",
                event_detail="Approval rejected after canonical state drift.",
            )
            self.send_json(409, {"error": "preview, revision, or policy changed"})
            return
        if not current_preview["allowed"]:
            LEDGER.transition(
                operation_id,
                {"awaiting-approval"},
                "denied",
                finished_at=int(time.time()),
                error_class="policy-denied",
                redacted_summary=str(current_preview["reason"])[:1000],
                event_detail="Approval rejected by the current policy decision.",
            )
            self.send_json(403, current_preview)
            return
        operation = LEDGER.transition(operation_id, {"awaiting-approval"}, "queued", approved_at=int(time.time()))
        self.send_json(202, operation)

    def handle_operation_cancel(self, operation_id: str, session: Session) -> None:
        operation = LEDGER.get(operation_id)
        if not operation:
            self.send_json(404, {"error": "not found"})
            return
        if operation["requested_by"] != session.identity:
            self.send_json(403, {"error": "operation belongs to another operator"})
            return
        if not SESSIONS.operation_bound_to(
            operation_id,
            session.session_id,
            idempotency_key=str(operation["idempotency_key"]),
        ):
            self.send_json(403, {"error": "operation cancellation requires the originating session"})
            return
        operation = LEDGER.transition(
            operation_id, {"awaiting-approval", "queued"}, "denied",
            finished_at=int(time.time()), error_class="operator-cancelled",
            redacted_summary="Cancelled by operator before execution.",
        )
        audit("operation.cancel", operation["workload_id"], "ok", actor=session.identity, operationId=operation_id)
        self.send_json(200, operation)


class LoopbackHTTPServer(ThreadingHTTPServer):
    """HTTP server that never performs DNS/FQDN resolution during bind."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])


def main() -> int:
    server = LoopbackHTTPServer((HOST, PORT), Handler)
    print(f"Argus control API listening on {HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
