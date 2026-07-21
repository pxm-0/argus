"""Fail-closed builder and verifier for the isolated Argus public portfolio."""

from __future__ import annotations

import base64
import hashlib
import html
import ipaddress
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class PortfolioError(ValueError):
    """Raised when a portfolio input, artifact, or promotion proof is unsafe."""


PUBLIC_FILES = {"index.html", "portfolio.json", "provenance.json", "provenance.sig", "style.css"}
PUBLIC_PROJECT_FIELDS = {"synthetic", "title", "summary", "tags", "status"}
DENIED_FIELD_MARKERS = ("token", "secret", "credential", "password", "audit", "finding", "backup", "host", "path", "port", "ip", "address", "route", "endpoint", "api", "log")
DENIED_VALUE_PATTERNS = (
    re.compile(r"\b(?:localhost|docker\.sock|tailscale|cloudflare|oreochiserver)\b", re.I),
    re.compile(r"\b(?:https?|wss?)://", re.I),
    re.compile(r"(?:^|[^\w])/(?:[\w.-]+/)+"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\b(?:sk|ghp|glpat)_[A-Za-z0-9_-]+\b", re.I),
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PortfolioError(f"invalid JSON: {path}") from exc


def _assert_safe_value(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 280 or value != value.strip():
        raise PortfolioError("public text must be a trimmed, non-empty string of at most 280 characters")
    for pattern in DENIED_VALUE_PATTERNS:
        if pattern.search(value):
            raise PortfolioError("public text contains a denied private value pattern")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return
    raise PortfolioError("public text must not be an IP address")


def validate_snapshot(snapshot: Any) -> dict[str, Any]:
    """Validate an explicit, synthetic-only public snapshot schema."""
    if not isinstance(snapshot, dict) or set(snapshot) != {"version", "projects"} or snapshot["version"] != 1:
        raise PortfolioError("public snapshot must contain exactly version=1 and projects")
    projects = snapshot["projects"]
    if not isinstance(projects, list) or len(projects) > 24:
        raise PortfolioError("projects must be a list with at most 24 entries")
    clean = []
    for project in projects:
        if not isinstance(project, dict) or set(project) != PUBLIC_PROJECT_FIELDS or project.get("synthetic") is not True:
            raise PortfolioError("every project must use exactly the public fields and synthetic=true")
        for key in project:
            if any(marker in key.lower() for marker in DENIED_FIELD_MARKERS):
                raise PortfolioError("public snapshot contains a denied field")
        for key in ("title", "summary", "status"):
            _assert_safe_value(project[key])
        if not isinstance(project["tags"], list) or not project["tags"] or len(project["tags"]) > 8:
            raise PortfolioError("tags must contain one to eight strings")
        for tag in project["tags"]:
            _assert_safe_value(tag)
        clean.append({key: project[key] for key in sorted(PUBLIC_PROJECT_FIELDS)})
    return {"version": 1, "projects": clean}


def _artifact_payload(snapshot: dict[str, Any]) -> dict[str, bytes]:
    cards = "".join(
        "<article><h2>{}</h2><p>{}</p><p class=\"meta\">{} · {}</p></article>".format(
            html.escape(project["title"]), html.escape(project["summary"]),
            html.escape(project["status"]), html.escape(", ".join(project["tags"])),
        )
        for project in snapshot["projects"]
    ) or "<p>No public projects are currently listed.</p>"
    index = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
             "<title>Argus Portfolio</title><link rel=\"stylesheet\" href=\"style.css\"><main><h1>Argus Portfolio</h1>"
             "<p>Synthetic public project summaries only.</p>" + cards + "</main></html>").encode("utf-8")
    style = b"body{font:16px system-ui;margin:0;background:#10131a;color:#eef2ff}main{max-width:760px;margin:auto;padding:3rem 1.5rem}article{border-top:1px solid #394150;padding:1rem 0}.meta{color:#b6c2dd}"
    return {"index.html": index, "portfolio.json": _canonical_bytes(snapshot) + b"\n", "style.css": style}


def _openssl(args: list[str]) -> None:
    if shutil.which("openssl") is None:
        raise PortfolioError("OpenSSL is required for signed portfolio provenance")
    result = subprocess.run(["openssl", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise PortfolioError("OpenSSL provenance operation failed")


def _sign(data: bytes, key: Path) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        source, signature = Path(directory) / "provenance.json", Path(directory) / "provenance.sig"
        source.write_bytes(data)
        _openssl(["pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(source), "-out", str(signature)])
        return signature.read_bytes()


def _verify_signature(data: bytes, signature: bytes, key: Path) -> None:
    with tempfile.TemporaryDirectory() as directory:
        source, signed = Path(directory) / "provenance.json", Path(directory) / "provenance.sig"
        source.write_bytes(data)
        signed.write_bytes(signature)
        _openssl(["pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(key), "-in", str(source), "-sigfile", str(signed)])


def _scan_bytes(name: str, data: bytes) -> None:
    lower = data.lower()
    if name.endswith(".map") or b"sourcemappingurl" in lower or b"fetch(" in lower or b"xmlhttprequest" in lower:
        raise PortfolioError("artifact contains debugging or live API behavior")
    if name != "provenance.sig":
        text = data.decode("utf-8", errors="ignore")
        for pattern in DENIED_VALUE_PATTERNS:
            if pattern.search(text):
                raise PortfolioError("artifact contains a denied private value pattern")


def build_artifact(snapshot: dict[str, Any], destination: Path, signing_key: Path, public_key: Path) -> dict[str, Any]:
    """Write a complete signed static artifact, refusing a non-empty output path."""
    snapshot = validate_snapshot(snapshot)
    if destination.exists() and any(destination.iterdir()):
        raise PortfolioError("artifact destination must be empty")
    if not signing_key.is_file() or not public_key.is_file():
        raise PortfolioError("private and public provenance keys outside the repository are required")
    destination.mkdir(parents=True, exist_ok=True)
    payload = _artifact_payload(snapshot)
    artifact_digest = _sha256(b"".join(name.encode() + b"\0" + payload[name] for name in sorted(payload)))
    provenance = {
        "schemaVersion": 1,
        "artifactDigest": artifact_digest,
        "files": {name: _sha256(data) for name, data in sorted(payload.items())},
        "sourceSnapshotDigest": _sha256(_canonical_bytes(snapshot)),
    }
    provenance_bytes = _canonical_bytes(provenance) + b"\n"
    signature = _sign(provenance_bytes, signing_key)
    files = {**payload, "provenance.json": provenance_bytes, "provenance.sig": base64.b64encode(signature) + b"\n"}
    for name, data in files.items():
        _scan_bytes(name, data)
        (destination / name).write_bytes(data)
    return verify_artifact(destination, public_key)


def verify_artifact(artifact: Path, public_key: Path) -> dict[str, Any]:
    """Verify exact files, byte safety, content digests, and signed provenance."""
    if not artifact.is_dir() or {item.name for item in artifact.iterdir() if item.is_file()} != PUBLIC_FILES:
        raise PortfolioError("artifact contains an unexpected or missing file")
    if not public_key.is_file():
        raise PortfolioError("a public provenance key is required")
    files = {name: (artifact / name).read_bytes() for name in PUBLIC_FILES}
    for name, data in files.items():
        _scan_bytes(name, data)
    provenance = _read_json(artifact / "provenance.json")
    if not isinstance(provenance, dict) or set(provenance) != {"schemaVersion", "artifactDigest", "files", "sourceSnapshotDigest"} or provenance["schemaVersion"] != 1:
        raise PortfolioError("artifact provenance schema is invalid")
    if not isinstance(provenance["files"], dict) or set(provenance["files"]) != {"index.html", "portfolio.json", "style.css"}:
        raise PortfolioError("provenance file allowlist is invalid")
    for name, digest in provenance["files"].items():
        if digest != _sha256(files[name]):
            raise PortfolioError("artifact file digest mismatch")
    expected = _sha256(b"".join(name.encode() + b"\0" + files[name] for name in sorted(provenance["files"])))
    if provenance["artifactDigest"] != expected:
        raise PortfolioError("artifact digest mismatch")
    snapshot = _read_json(artifact / "portfolio.json")
    if _sha256(_canonical_bytes(validate_snapshot(snapshot))) != provenance["sourceSnapshotDigest"]:
        raise PortfolioError("source snapshot provenance mismatch")
    try:
        signature = base64.b64decode(files["provenance.sig"].strip(), validate=True)
    except ValueError as exc:
        raise PortfolioError("provenance signature encoding is invalid") from exc
    _verify_signature(files["provenance.json"], signature, public_key)
    return {"artifactDigest": expected, "provenanceDigest": _sha256(files["provenance.json"]), "verified": True}


def validate_mirror(artifact: Path, public_key: Path, receipt: Path) -> dict[str, Any]:
    """Create a digest-bound proof for a separately provisioned, no-route mirror."""
    proof = verify_artifact(artifact, public_key)
    if receipt.exists():
        raise PortfolioError("mirror receipt already exists")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(_canonical_bytes({"schemaVersion": 1, "noRoute": True, **proof}) + b"\n")
    return proof


def validate_promotion(artifact: Path, public_key: Path, receipt: Path) -> dict[str, Any]:
    """Fail closed unless the exact verified mirror artifact is being promoted."""
    proof = verify_artifact(artifact, public_key)
    mirror = _read_json(receipt)
    if mirror != {"schemaVersion": 1, "noRoute": True, **proof}:
        raise PortfolioError("artifact is not the exact no-route mirror result")
    return proof
