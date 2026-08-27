from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BackupRestoreTests(unittest.TestCase):
    def artifact(self, root: Path, workload: str = "demo", artifact_id: str = "run-1") -> Path:
        artifact = root / workload / artifact_id
        artifact.mkdir(parents=True)
        with tarfile.open(artifact / "files.tar.gz", "w:gz") as bundle:
            content = b"restored\n"
            member = tarfile.TarInfo("data/value.txt")
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
        (artifact / "backup-summary.json").write_text(json.dumps({"workloadId": workload}))
        rows = []
        for name in ("files.tar.gz", "backup-summary.json"):
            rows.append(f"{hashlib.sha256((artifact / name).read_bytes()).hexdigest()}  {name}")
        (artifact / "checksums.sha256").write_text("\n".join(rows) + "\n")
        return artifact

    def test_restore_is_checksum_verified_isolated_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact = self.artifact(base / "backups")
            state = base / "state"
            script = (ROOT / "scripts" / "argus-backup-restore").read_text()
            relocated = base / "restore"
            relocated.write_text(script.replace("/srv/argus/runtime/backups", str(base / "backups")))
            relocated.chmod(0o755)
            env = {**os.environ, "ARGUS_RESTORE_STATE": str(state)}
            command = [str(relocated), "--workload", "demo", "--artifact-id", artifact.name, "--acknowledge-isolated-restore"]
            first = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
            second = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            payload = json.loads(first.stdout)
            self.assertTrue(payload["verified"])
            self.assertFalse(payload["liveStateChanged"])
            self.assertEqual("restored\n", (state / "run-1" / "candidate" / "data" / "value.txt").read_text())

    def test_checksum_mismatch_fails_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact = self.artifact(base / "backups")
            (artifact / "files.tar.gz").write_bytes(b"tampered")
            script = (ROOT / "scripts" / "argus-backup-restore").read_text()
            relocated = base / "restore"
            relocated.write_text(script.replace("/srv/argus/runtime/backups", str(base / "backups")))
            relocated.chmod(0o755)
            state = base / "state"
            result = subprocess.run(
                [str(relocated), "--workload", "demo", "--artifact-id", "run-1", "--acknowledge-isolated-restore"],
                env={**os.environ, "ARGUS_RESTORE_STATE": str(state)}, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((state / "run-1" / "candidate").exists())


if __name__ == "__main__":
    unittest.main()
