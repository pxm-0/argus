"""Stdlib TOTP (RFC 6238: HMAC-SHA1, 6 digits, 30 s) for the operator second factor.

The secrets file maps an operator login to a base32 secret and the SHA-256
hashes of its single-use recovery codes. Nothing here logs or returns a secret
except `new_enrollment`, whose caller shows it once on a terminal.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

DIGITS = 6
PERIOD = 30
SKEW_STEPS = 1
SECRET_BYTES = 20
RECOVERY_CODE_COUNT = 10
RECOVERY_LENGTH = 10
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SCHEMA_VERSION = 1
DEFAULT_FILE = Path("/etc/argus/operator-totp.json")


class TotpError(ValueError):
    """Malformed secrets file or enrollment input; the message never includes a secret."""


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode()


def _key(secret_b32: str) -> bytes:
    try:
        return base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8), casefold=True)
    except (binascii.Error, ValueError):
        raise TotpError("secret is not valid base32") from None


def hotp(secret_b32: str, counter: int) -> str:
    digest = hmac.new(_key(secret_b32), counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 10**DIGITS:0{DIGITS}d}"


def counter_at(now: float) -> int:
    return int(now) // PERIOD


def matching_counter(secret_b32: str, code: str, now: float) -> int | None:
    """Highest counter in t-1..t+1 whose code equals `code`; every candidate is compared."""
    supplied = code.strip().encode()
    found: int | None = None
    center = counter_at(now)
    for counter in range(center - SKEW_STEPS, center + SKEW_STEPS + 1):
        if hmac.compare_digest(hotp(secret_b32, counter).encode(), supplied):
            found = counter
    return found


def normalize_recovery(code: str) -> str:
    return "".join(code.split()).replace("-", "").upper()


def is_recovery_shape(code: str) -> bool:
    normalized = normalize_recovery(code)
    return len(normalized) == RECOVERY_LENGTH and all(c in RECOVERY_ALPHABET for c in normalized)


def recovery_hash(login: str, code: str) -> str:
    return hashlib.sha256(f"{login.strip().lower()}:{normalize_recovery(code)}".encode()).hexdigest()


def generate_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def otpauth_uri(login: str, secret_b32: str) -> str:
    safe = b"@.-_" + bytes(range(48, 58)) + bytes(range(65, 91)) + bytes(range(97, 123))
    label = "".join(chr(b) if b in safe else f"%{b:02X}" for b in login.encode())
    return (
        f"otpauth://totp/Argus:{label}"
        f"?secret={secret_b32}&issuer=Argus&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def new_enrollment(login: str) -> tuple[dict[str, Any], list[str]]:
    codes = generate_recovery_codes()
    entry = {"secret": generate_secret(), "recoveryCodeHashes": [recovery_hash(login, c) for c in codes]}
    return entry, codes


def _validate_entry(entry: Any) -> dict[str, Any]:
    hashes = entry.get("recoveryCodeHashes") if isinstance(entry, dict) else None
    if (
        not isinstance(entry, dict)
        or set(entry) != {"secret", "recoveryCodeHashes"}
        or not isinstance(entry["secret"], str)
        or not isinstance(hashes, list)
        or not all(isinstance(h, str) for h in hashes)
    ):
        raise TotpError("operator entry is malformed")
    _key(entry["secret"])
    return entry


def load_operators(path: Path) -> dict[str, dict[str, Any]]:
    """Return {login: entry}. FileNotFoundError propagates (not enrolled); other faults raise TotpError/OSError."""
    try:
        payload = json.loads(path.read_text())
    except (UnicodeError, json.JSONDecodeError):
        raise TotpError("secrets file is not valid JSON") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schemaVersion", "operators"}
        or payload["schemaVersion"] != SCHEMA_VERSION
        or not isinstance(payload["operators"], dict)
    ):
        raise TotpError("secrets file has an unexpected shape")
    return {str(login).strip().lower(): _validate_entry(entry) for login, entry in payload["operators"].items()}


def write_operators(path: Path, operators: dict[str, dict[str, Any]]) -> None:
    """Atomic 0600 replace; the temp file is created exclusively and fsynced before the rename."""
    document = json.dumps({"schemaVersion": SCHEMA_VERSION, "operators": operators}, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class EnrollRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _enabled_logins(operators_file: Path) -> list[str]:
    try:
        payload = json.loads(operators_file.read_text())
        return [
            str(item["tailnetLogin"]).strip().lower()
            for item in payload["operators"]
            if item.get("enabled") is True and item.get("role") == "owner"
        ]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        raise EnrollRefused("totp-operators-unreadable", "The operator registry could not be read.") from None


def enroll(
    *,
    login: str,
    rotate: bool,
    tty: Any,
    euid: int,
    stdin_is_tty: bool,
    secrets_file: Path = DEFAULT_FILE,
    operators_file: Path = Path("/etc/argus/operators.json"),
    now: Any = None,
) -> str:
    """Enrol or rotate one operator; returns the login. Secrets are written only to `tty`."""
    clock = now or time.time
    if euid != 0:
        raise EnrollRefused("totp-root-required", "Enrolment writes a root-only file; run it with sudo.")
    if tty is None or not stdin_is_tty:
        raise EnrollRefused("totp-tty-required", "Enrolment shows secrets once and needs an interactive terminal.")
    enabled = _enabled_logins(operators_file)
    login = login.strip().lower() or (enabled[0] if len(enabled) == 1 else "")
    if not login or login not in enabled:
        raise EnrollRefused("totp-operator-unknown", "Pass --operator with an enabled owner login from the operator registry.")
    try:
        existing = load_operators(secrets_file)
    except FileNotFoundError:
        existing = {}
    except (OSError, TotpError):
        raise EnrollRefused("totp-store-unreadable", "The existing secrets file is unreadable or malformed; fix it first.") from None
    if login in existing and not rotate:
        raise EnrollRefused("totp-already-enrolled", "That operator is already enrolled; pass --rotate to replace the secret.")
    entry, codes = new_enrollment(login)
    tty.write(f"\nAuthenticator URI (add on a device other than the one holding the bootstrap token):\n  {otpauth_uri(login, entry['secret'])}\n")
    tty.write("\nRecovery codes (each works once; store them offline, they are not shown again):\n")
    tty.write("".join(f"  {code}\n" for code in codes))
    for _ in range(3):
        if matching_counter(entry["secret"], tty.read_line("\nEnter the current authenticator code to confirm: "), clock()) is not None:
            write_operators(secrets_file, {**existing, login: entry})
            tty.write("Enrolled. Restart argus-control-api to load the new secrets.\n")
            return login
        tty.write("Code did not match.\n")
    raise EnrollRefused("totp-confirmation-failed", "No valid code was entered; nothing was written.")
