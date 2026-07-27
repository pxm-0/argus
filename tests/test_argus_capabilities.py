from __future__ import annotations

import subprocess
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from argus_capabilities import (  # noqa: E402
    Ed25519Signer,
    Ed25519Verifier,
    ReplayStore,
    build_envelope,
    validate_envelope,
)
from argus_capability_issuer import CapabilityIssuer  # noqa: E402
from argus_operations import OperationLedger, digest  # noqa: E402


def generate_keypair(directory: Path) -> tuple[Path, Path]:
    private_key = directory / "ed25519.key"
    public_key = directory / "issuer.pub"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "ED25519",
            "-out",
            str(private_key),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return private_key, public_key


class CapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.directory.name)
        self.private_key, self.public_key = generate_keypair(self.root)
        self.ledger = OperationLedger(self.root / "operations.sqlite3")
        preview = {
            "workloadId": "demo",
            "trustDomain": "personal-sandbox",
            "operationType": "workload.restart",
            "parameters": {},
            "expectedRevision": "revision",
            "policyVersion": "policy",
        }
        self.operation, _ = self.ledger.create(
            workload_id="demo",
            trust_domain="personal-sandbox",
            operation_type="workload.restart",
            requested_by="operator@example.com",
            parameters={},
            preview_digest=digest(preview),
            expected_revision="revision",
            policy_version="policy",
            idempotency_key="idem",
        )
        self.ledger.transition(
            str(self.operation["operation_id"]),
            {"awaiting-approval"},
            "queued",
            approved_at=int(time.time()),
        )
        self.operation = self.ledger.claim(str(self.operation["operation_id"]))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_issuer_signs_exact_worker_claimed_operation(self) -> None:
        issuer = CapabilityIssuer(
            self.ledger,
            Ed25519Signer(self.private_key),
        )
        signed = issuer.issue(
            str(self.operation["operation_id"]),
            "personal-sandbox",
        )
        envelope = Ed25519Verifier([self.public_key]).verify(signed)
        validate_envelope(
            envelope,
            self.operation,
            trust_domain="personal-sandbox",
        )
        self.assertEqual(1, envelope["schemaVersion"])
        self.assertEqual(43, len(envelope["nonce"]))
        self.assertNotIn("parameters", envelope)

    def test_signature_domain_expiry_and_operation_binding_fail_closed(self) -> None:
        signer = Ed25519Signer(self.private_key)
        verifier = Ed25519Verifier([self.public_key])
        envelope = build_envelope(self.operation, now=1_000_000)
        signed = signer.sign(envelope)
        modified = {
            "envelope": {**envelope, "trustDomain": "other"},
            "signature": signed["signature"],
        }
        with self.assertRaisesRegex(ValueError, "invalid capability signature"):
            verifier.verify(modified)
        verified = verifier.verify(signed)
        with self.assertRaisesRegex(ValueError, "wrong capability domain"):
            validate_envelope(
                verified,
                self.operation,
                trust_domain="other",
                now=1_000_001,
            )
        with self.assertRaisesRegex(ValueError, "expired capability"):
            validate_envelope(
                verified,
                self.operation,
                trust_domain="personal-sandbox",
                now=1_000_061,
            )
        different = {**self.operation, "idempotency_key": "different"}
        with self.assertRaisesRegex(ValueError, "operation mismatch"):
            validate_envelope(
                verified,
                different,
                trust_domain="personal-sandbox",
                now=1_000_001,
            )

    def test_previous_public_key_expires_after_rotation_overlap(self) -> None:
        previous_root = self.root / "previous"
        previous_root.mkdir()
        previous_private, previous_public = generate_keypair(previous_root)
        signed = Ed25519Signer(previous_private).sign(
            build_envelope(self.operation, now=1_000_000)
        )
        os.utime(previous_public, (1_000_000, 1_000_000))
        current = [1_000_599]
        verifier = Ed25519Verifier(
            [self.public_key, previous_public],
            clock=lambda: current[0],
        )
        self.assertEqual(
            self.operation["operation_id"],
            verifier.verify(signed)["operationId"],
        )
        current[0] = 1_000_601
        with self.assertRaisesRegex(ValueError, "invalid capability signature"):
            verifier.verify(signed)

    def test_domain_local_replay_store_consumes_id_and_nonce_atomically(self) -> None:
        replay = ReplayStore(self.root / "domain" / "capabilities.sqlite3")
        envelope = build_envelope(self.operation)
        self.assertTrue(
            replay.consume(
                str(envelope["capabilityId"]),
                str(envelope["nonce"]),
                str(envelope["expiresAt"]),
            )
        )
        self.assertFalse(
            replay.consume(
                str(envelope["capabilityId"]),
                "different-nonce",
                str(envelope["expiresAt"]),
            )
        )
        self.assertFalse(
            replay.consume(
                "different-capability",
                str(envelope["nonce"]),
                str(envelope["expiresAt"]),
            )
        )

    def test_issuer_rejects_unapproved_mutation_and_wrong_domain(self) -> None:
        preview = {
            "workloadId": "other",
            "trustDomain": "personal-sandbox",
            "operationType": "workload.restart",
            "parameters": {},
            "expectedRevision": "revision",
            "policyVersion": "policy",
        }
        unapproved, _ = self.ledger.create(
            workload_id="other",
            trust_domain="personal-sandbox",
            operation_type="workload.restart",
            requested_by="operator@example.com",
            parameters={},
            preview_digest=digest(preview),
            expected_revision="revision",
            policy_version="policy",
            idempotency_key="unapproved",
        )
        self.ledger.transition(
            str(unapproved["operation_id"]),
            {"awaiting-approval"},
            "queued",
        )
        self.ledger.claim(str(unapproved["operation_id"]))
        issuer = CapabilityIssuer(
            self.ledger,
            Ed25519Signer(self.private_key),
        )
        with self.assertRaisesRegex(ValueError, "no persisted approval"):
            issuer.issue(str(unapproved["operation_id"]), "personal-sandbox")
        with self.assertRaisesRegex(ValueError, "wrong operation domain"):
            issuer.issue(str(self.operation["operation_id"]), "other")

    def test_activation_is_acknowledged_private_and_reversible(self) -> None:
        script_path = ROOT / "scripts" / "argus-m5-capability-issuer"
        script = script_path.read_text()
        self.assertTrue(script_path.stat().st_mode & 0o111)
        self.assertIn("--acknowledge-m5-capability-issuer", script)
        self.assertIn("/var/backups/argus-m5-phase1/capability-issuer", script)
        self.assertIn("trap rollback_on_exit EXIT", script)
        self.assertIn("openssl genpkey -algorithm ED25519", script)
        self.assertIn("runuser -u oreo -- test ! -r", script)
        self.assertIn("publicExposureChanged=false", script)
        self.assertIn("secretsPrinted=false", script)
        self.assertNotIn("cloudflared", script.lower())
        self.assertNotIn("tailscale funnel", script.lower())


if __name__ == "__main__":
    unittest.main()
