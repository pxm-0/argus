from __future__ import annotations
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from argus_m4 import MigrationError, validate_stateful_migration  # noqa: E402


def evidence() -> dict:
    return {
        "workloadId": "pilot", "logicalVolume": "app-data",
        "sourceRuntimeRef": "sha256:source-runtime", "targetRuntimeRef": "sha256:target-runtime",
        "sourceVolumeRef": "sha256:source-volume", "targetVolumeRef": "sha256:target-volume",
        "sourceUidGid": "1000:1000", "targetUidGid": "2000:2000",
        "sourceChecksum": "sha256:data", "targetChecksum": "sha256:data",
        "backupVerified": True, "restoreVerified": True, "sourceFenced": True,
        "targetFencedBeforeRollback": True, "healthVerified": True, "accessVerified": True,
        "isolationVerified": True, "rollbackVerified": True,
    }


class ArgusM4Test(unittest.TestCase):
    def test_stateful_migration_requires_all_safety_evidence(self) -> None:
        self.assertTrue(validate_stateful_migration(evidence())["accepted"])
        changed = evidence()
        changed["targetChecksum"] = "sha256:other"
        with self.assertRaises(MigrationError):
            validate_stateful_migration(changed)
        changed = evidence()
        changed["sourceFenced"] = False
        with self.assertRaises(MigrationError):
            validate_stateful_migration(changed)
