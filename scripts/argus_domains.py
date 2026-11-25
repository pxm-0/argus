"""The D030 trust-domain registry: every cell, its kind and its role.

config/argus/domains.json is the only list of cells. `rootless` marks the
cells provisioned as rootless Docker runtimes on the host.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

KINDS = ("management", "legacy", "workload")
ROLES = ("sandbox", "staging", "prod", "quarantine")
# D030: images move only staging -> prod; dev images are never promoted.
PROMOTION = {"staging": "prod"}
DOMAIN_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "argus" / "domains.json"


class DomainRegistryError(ValueError):
    """The registry is missing, malformed or names an unknown cell."""


def parse(payload: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("domains"), list):
        raise DomainRegistryError("trust-domain registry must be schemaVersion 1 with a domains list")
    seen: set[str] = set()
    roles: set[str] = set()
    domains = []
    for item in payload["domains"]:
        if not isinstance(item, dict) or set(item) != {"id", "kind", "role", "rootless"}:
            raise DomainRegistryError("trust-domain entries need exactly id, kind, role and rootless")
        domain_id, kind, role, rootless = item["id"], item["kind"], item["role"], item["rootless"]
        if not isinstance(domain_id, str) or not domain_id or not set(domain_id) <= DOMAIN_ID_CHARS or domain_id in seen:
            raise DomainRegistryError("trust-domain ids must be unique lowercase names")
        if kind not in KINDS or (role is not None and role not in ROLES) or not isinstance(rootless, bool):
            raise DomainRegistryError(f"trust domain {domain_id} has an invalid kind, role or rootless flag")
        if role is not None and role in roles:
            raise DomainRegistryError(f"role {role} is assigned to more than one trust domain")
        if rootless and kind != "workload":
            raise DomainRegistryError(f"trust domain {domain_id} cannot be rootless unless it is a workload cell")
        seen.add(domain_id)
        if role is not None:
            roles.add(role)
        domains.append(dict(item))
    return tuple(domains)


@lru_cache(maxsize=None)
def load(path: Path = DEFAULT_PATH) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DomainRegistryError(f"trust-domain registry {path.name} is unreadable") from exc
    return parse(payload)


def ids(*, kind: str | None = None, rootless: bool | None = None, path: Path = DEFAULT_PATH) -> tuple[str, ...]:
    """Cell ids in registry order, optionally filtered."""
    return tuple(
        item["id"] for item in load(path)
        if (kind is None or item["kind"] == kind) and (rootless is None or item["rootless"] is rootless)
    )


def entry(domain_id: str, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    for item in load(path):
        if item["id"] == domain_id:
            return dict(item)
    raise DomainRegistryError(f"unknown trust domain: {domain_id}")


def cell(role_name: str, path: Path = DEFAULT_PATH) -> str:
    """The one cell holding a role."""
    for item in load(path):
        if item["role"] == role_name:
            return item["id"]
    raise DomainRegistryError(f"no trust domain holds role {role_name}")


def role(domain_id: str, path: Path = DEFAULT_PATH) -> str | None:
    return entry(domain_id, path)["role"]


def label(domain_id: str, path: Path = DEFAULT_PATH) -> str:
    """`role (cell)`, so operators never confuse a role with a cell id."""
    domain_role = role(domain_id, path)
    return f"{domain_role} ({domain_id})" if domain_role else domain_id


def promotion_refusal(source_domain: str, target_domain: str, path: Path = DEFAULT_PATH) -> str | None:
    """None when source -> target is an allowed promotion, else the reason it is not."""
    try:
        source_role, target_role = role(source_domain, path), role(target_domain, path)
    except DomainRegistryError as exc:
        return str(exc)
    if source_role is None or target_role is None or PROMOTION.get(source_role) != target_role:
        return (f"promotion runs only staging -> prod; {label(source_domain, path)} -> "
                f"{label(target_domain, path)} is not allowed")
    return None
