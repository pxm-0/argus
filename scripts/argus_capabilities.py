from __future__ import annotations

import base64
import os
import sqlite3
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from argus_operations import canonical_json, digest, format_timestamp, parse_timestamp


CAPABILITY_SCHEMA_VERSION = 1
MAX_CAPABILITY_TTL_SECONDS = 60
REPLAY_RETENTION_SECONDS = 24 * 60 * 60
PREVIOUS_KEY_OVERLAP_SECONDS = 10 * 60


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise ValueError("capability envelope cannot contain floating-point values")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("capability envelope keys must be strings")
            _reject_floats(item)
    elif isinstance(value, list):
        for item in value:
            _reject_floats(item)


class Ed25519Signer:
    def __init__(self, private_key: Path) -> None:
        if not private_key.is_file():
            raise ValueError("Ed25519 private key is unavailable")
        metadata = private_key.stat()
        if (
            stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise ValueError("Ed25519 private key ownership or mode is unsafe")
        self.private_key = private_key

    def sign(self, envelope: dict[str, Any]) -> dict[str, Any]:
        _reject_floats(envelope)
        encoded = canonical_json(envelope).encode("utf-8")
        with tempfile.NamedTemporaryFile(prefix="argus-capability-payload-") as payload:
            payload.write(encoded)
            payload.flush()
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-sign",
                    "-rawin",
                    "-inkey",
                    str(self.private_key),
                    "-in",
                    payload.name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        if result.returncode != 0 or len(result.stdout) != 64:
            raise RuntimeError("Ed25519 signing failed")
        return {
            "envelope": envelope,
            "signature": _base64url_encode(result.stdout),
        }


class Ed25519Verifier:
    def __init__(
        self,
        public_keys: list[Path],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.public_keys = [path for path in public_keys if path.is_file()]
        if not self.public_keys:
            raise ValueError("issuer public key is unavailable")
        self.clock = clock

    def verify(self, signed: dict[str, Any]) -> dict[str, Any]:
        if set(signed) != {"envelope", "signature"}:
            raise ValueError("malformed signed capability")
        envelope = signed["envelope"]
        if not isinstance(envelope, dict):
            raise ValueError("malformed signed capability")
        _reject_floats(envelope)
        encoded = canonical_json(envelope).encode("utf-8")
        try:
            signature = _base64url_decode(str(signed["signature"]))
        except (ValueError, TypeError) as exc:
            raise ValueError("malformed capability signature") from exc
        if len(signature) != 64:
            raise ValueError("malformed capability signature")
        with (
            tempfile.NamedTemporaryFile(prefix="argus-capability-payload-") as payload,
            tempfile.NamedTemporaryFile(prefix="argus-capability-signature-") as signature_file,
        ):
            payload.write(encoded)
            payload.flush()
            signature_file.write(signature)
            signature_file.flush()
            for index, public_key in enumerate(self.public_keys):
                if (
                    index > 0
                    and self.clock() - public_key.stat().st_mtime
                    > PREVIOUS_KEY_OVERLAP_SECONDS
                ):
                    continue
                result = subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-verify",
                        "-rawin",
                        "-pubin",
                        "-inkey",
                        str(public_key),
                        "-in",
                        payload.name,
                        "-sigfile",
                        signature_file.name,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5,
                )
                if result.returncode == 0:
                    return dict(envelope)
        raise ValueError("invalid capability signature")


class ReplayStore:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_capabilities (
                    capability_id TEXT PRIMARY KEY,
                    nonce TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
                """
            )
        os.chmod(self.path, 0o600)

    def consume(
        self,
        capability_id: str,
        nonce: str,
        expires_at: str,
    ) -> bool:
        now = int(self.clock())
        retention_cutoff = format_timestamp(now - REPLAY_RETENTION_SECONDS)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM consumed_capabilities WHERE expires_at <= ?",
                (retention_cutoff,),
            )
            try:
                connection.execute(
                    """
                    INSERT INTO consumed_capabilities (
                        capability_id, nonce, expires_at, consumed_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        capability_id,
                        nonce,
                        format_timestamp(expires_at),
                        format_timestamp(now),
                    ),
                )
            except sqlite3.IntegrityError:
                connection.rollback()
                return False
            connection.commit()
        return True


def build_envelope(
    operation: dict[str, Any],
    *,
    now: int | None = None,
    ttl_seconds: int = MAX_CAPABILITY_TTL_SECONDS,
) -> dict[str, Any]:
    if ttl_seconds <= 0 or ttl_seconds > MAX_CAPABILITY_TTL_SECONDS:
        raise ValueError("capability expiry must be at most 60 seconds")
    issued_at = int(time.time()) if now is None else int(now)
    return {
        "schemaVersion": CAPABILITY_SCHEMA_VERSION,
        "capabilityId": str(uuid.uuid4()),
        "operationId": str(operation["operation_id"]),
        "idempotencyKey": str(operation["idempotency_key"]),
        "operator": str(operation["requested_by"]),
        "workloadId": str(operation["workload_id"]),
        "trustDomain": str(operation["trust_domain"]),
        "operationType": str(operation["operation_type"]),
        "parametersDigest": str(operation["parameters_digest"]),
        "previewDigest": str(operation["preview_digest"]),
        "expectedRevision": str(operation["expected_revision"]),
        "policyVersion": str(operation["policy_version"]),
        "issuedAt": format_timestamp(issued_at),
        "expiresAt": format_timestamp(issued_at + ttl_seconds),
        "nonce": _base64url_encode(os.urandom(32)),
    }


def validate_envelope(
    envelope: dict[str, Any],
    operation: dict[str, Any],
    *,
    trust_domain: str,
    now: int | None = None,
) -> None:
    required = {
        "schemaVersion",
        "capabilityId",
        "operationId",
        "idempotencyKey",
        "operator",
        "workloadId",
        "trustDomain",
        "operationType",
        "parametersDigest",
        "previewDigest",
        "expectedRevision",
        "policyVersion",
        "issuedAt",
        "expiresAt",
        "nonce",
    }
    if set(envelope) != required or envelope["schemaVersion"] != CAPABILITY_SCHEMA_VERSION:
        raise ValueError("incomplete capability envelope")
    try:
        uuid.UUID(str(envelope["capabilityId"]))
        uuid.UUID(str(envelope["operationId"]))
    except ValueError as exc:
        raise ValueError("invalid capability identifier") from exc
    try:
        nonce = _base64url_decode(str(envelope["nonce"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid capability nonce") from exc
    if len(nonce) != 32:
        raise ValueError("invalid capability nonce")
    current = int(time.time()) if now is None else int(now)
    issued_at = parse_timestamp(str(envelope["issuedAt"]))
    expires_at = parse_timestamp(str(envelope["expiresAt"]))
    if issued_at > current + 5 or expires_at <= current:
        raise ValueError("expired capability")
    if expires_at - issued_at > MAX_CAPABILITY_TTL_SECONDS:
        raise ValueError("capability expiry exceeds 60 seconds")
    expected = {
        "operationId": operation["operation_id"],
        "idempotencyKey": operation["idempotency_key"],
        "operator": operation["requested_by"],
        "workloadId": operation["workload_id"],
        "trustDomain": operation["trust_domain"],
        "operationType": operation["operation_type"],
        "parametersDigest": operation["parameters_digest"],
        "previewDigest": operation["preview_digest"],
        "expectedRevision": operation["expected_revision"],
        "policyVersion": operation["policy_version"],
    }
    if any(str(envelope[key]) != str(value) for key, value in expected.items()):
        raise ValueError("capability operation mismatch")
    if envelope["trustDomain"] != trust_domain:
        raise ValueError("wrong capability domain")
    if digest(operation["parameters"]) != envelope["parametersDigest"]:
        raise ValueError("capability parameter digest mismatch")
