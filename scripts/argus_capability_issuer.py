from __future__ import annotations

import os
import socketserver
from pathlib import Path
from typing import Any

from argus_capabilities import Ed25519Signer, build_envelope
from argus_ipc import receive_frame, send_frame
from argus_operations import MUTATIONS, OperationLedger, digest


class CapabilityIssuer:
    def __init__(
        self,
        ledger: OperationLedger,
        signer: Ed25519Signer,
    ) -> None:
        self.ledger = ledger
        self.signer = signer

    def issue(
        self,
        operation_id: str,
        trust_domain: str,
    ) -> dict[str, Any]:
        operation = self.ledger.get(operation_id)
        if not operation:
            raise ValueError("unknown operation")
        if operation["state"] != "running":
            raise ValueError("operation is not worker-claimed")
        if operation["trust_domain"] != trust_domain:
            raise ValueError("wrong operation domain")
        if operation["operation_type"] in MUTATIONS and not operation["approved_at"]:
            raise ValueError("mutation has no persisted approval")
        if not operation["requested_by"]:
            raise ValueError("operation has no operator identity")
        if digest(operation["parameters"]) != operation["parameters_digest"]:
            raise ValueError("operation parameter binding is invalid")
        preview = {
            "workloadId": operation["workload_id"],
            "trustDomain": operation["trust_domain"],
            "operationType": operation["operation_type"],
            "parameters": operation["parameters"],
            "expectedRevision": operation["expected_revision"],
            "policyVersion": operation["policy_version"],
        }
        if digest(preview) != operation["preview_digest"]:
            raise ValueError("operation preview binding is invalid")
        envelope = build_envelope(operation)
        signed = self.signer.sign(envelope)
        print(
            "CAPABILITY_ISSUED "
            f"capabilityId={envelope['capabilityId']} "
            f"operationId={operation_id}",
            flush=True,
        )
        return signed


class IssuerRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            request = receive_frame(self.request)
            if set(request) != {"method", "operationId", "trustDomain"}:
                raise ValueError("only capability.issue is accepted")
            if request["method"] != "capability.issue":
                raise ValueError("only capability.issue is accepted")
            signed = self.server.issuer.issue(  # type: ignore[attr-defined]
                str(request["operationId"]),
                str(request["trustDomain"]),
            )
            response = {"ok": True, "signedCapability": signed}
        except Exception as exc:  # noqa: BLE001
            response = {"ok": False, "error": exc.__class__.__name__}
        send_frame(self.request, response)


def verify_public_key_distribution(
    private_key: Path,
    public_keys: list[Path],
) -> None:
    import subprocess

    result = subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-outform",
            "DER",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError("issuer public-key derivation failed")
    for public_key in public_keys:
        distributed = subprocess.run(
            [
                "openssl",
                "pkey",
                "-pubin",
                "-in",
                str(public_key),
                "-outform",
                "DER",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
        if distributed.returncode != 0 or distributed.stdout != result.stdout:
            raise RuntimeError("issuer public-key distribution is incomplete")


def main() -> int:
    ledger_path = Path(
        os.environ.get(
            "ARGUS_OPERATIONS_DB",
            "/var/lib/argus/control/operations.sqlite3",
        )
    )
    private_key = Path(
        os.environ.get(
            "ARGUS_ISSUER_PRIVATE_KEY",
            "/etc/argus/capability-issuer/ed25519.key",
        )
    )
    socket_path = Path(
        os.environ.get(
            "ARGUS_ISSUER_SOCKET",
            "/run/argus/capability-issuer.sock",
        )
    )
    public_keys = [
        Path(value)
        for value in os.environ.get("ARGUS_ISSUER_PUBLIC_KEYS", "").split(":")
        if value
    ]
    if not public_keys:
        raise SystemExit("distributed issuer public keys are required")
    signer = Ed25519Signer(private_key)
    verify_public_key_distribution(private_key, public_keys)
    ledger = OperationLedger(
        ledger_path,
        require_existing=True,
        migrate_schema=False,
        read_only=True,
    )
    issuer = CapabilityIssuer(ledger, signer)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(
        str(socket_path),
        IssuerRequestHandler,
    ) as server:
        server.issuer = issuer  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o660)
        print("Argus capability issuer active", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
