from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "argus-backup-snapshot"
SECRET = "S3CR3T-TOKEN-VALUE-do-not-print"
RECIPIENT = "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq\n"


def make_db(path: Path, value: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("create table t (v text)")
    connection.execute("insert into t values (?)", (value,))
    connection.commit()
    connection.close()


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root, self.etc, self.state, self.out = base / "argus", base / "etc", base / "var", base / "out"
        runtime = self.root / "runtime" / "argus"
        make_db(runtime / "m1" / "state.sqlite3")
        make_db(runtime / "entity-store.sqlite3")
        make_db(runtime / "audit.sqlite3")
        (runtime / "m1" / "access-journal.jsonl").write_text("{}\n")
        (runtime / "audit-checkpoint.json").write_text("{}")
        make_db(self.state / "control" / "operations.sqlite3")
        make_db(self.state / "control" / "session.sqlite3")
        make_db(self.state / "personal-managed" / "capabilities.sqlite3")
        (self.etc / "domain-keys").mkdir(parents=True)
        (self.etc / "control-token").write_text(SECRET)
        (self.etc / "domain-keys" / "k.pem").write_text(SECRET + "-key")
        verify = self.root / "scripts" / "argus-m1-verify"
        verify.parent.mkdir(parents=True)
        verify.write_text('#!/bin/sh\necho \'{"ok": true}\'\n')
        verify.chmod(0o755)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        bindir = base / "bin"
        bindir.mkdir()
        for name, body in {
            "nft": "echo 'table inet x'", "tailscale": "echo '{}'", "systemctl": "echo '[{\"unit\":\"argus-a.service\"}]'",
            "age": 'if [ "$1" = "-d" ]; then cat "$4"; else cat "$5" > "$4"; fi',
        }.items():
            (bindir / name).write_text(f"#!/bin/sh\n{body}\n")
            (bindir / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        self.env.pop("ARGUS_SNAPSHOT_AGE_RECIPIENTS", None)

    def run_cli(self, *extra: str, plaintext: bool = True) -> subprocess.CompletedProcess:
        argv = [str(SCRIPT), "--root", str(self.root), "--etc-dir", str(self.etc), "--state-dir", str(self.state),
                "--out-dir", str(self.out), *extra]
        if plaintext:
            argv.append("--allow-plaintext")
        return subprocess.run(argv, capture_output=True, text=True, env=self.env)

    def snapshot(self, reason: str = "t") -> Path:
        result = self.run_cli("--reason", reason, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(json.loads(result.stdout)["archive"])

    def test_snapshot_contents_mode_and_no_secret_output(self) -> None:
        result = self.run_cli("--reason", "baseline", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        archive = Path(json.loads(result.stdout)["archive"])
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(archive) as tar:
            names = set(tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))
        for expected in ("db/m1-state.sqlite3", "db/operations.sqlite3", "db/session.sqlite3",
                         "db/capabilities-personal-managed.sqlite3", "etc-argus/control-token",
                         "etc-argus/domain-keys/k.pem", "m1/access-journal.jsonl", "m1/audit-checkpoint.json",
                         "state/git-head.txt", "state/nft-ruleset.nft", "state/tailscale-serve.json",
                         "state/systemd-argus-units.json", "state/m1-verify.json"):
            self.assertIn(expected, names)
            self.assertEqual(len(manifest["members"][expected]["sha256"]), 64)
        verified = self.run_cli("--verify", str(archive), plaintext=False)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertNotIn(SECRET, verified.stdout + verified.stderr)

    def test_refuses_plaintext_without_flag_or_recipient(self) -> None:
        result = self.run_cli("--reason", "t", plaintext=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--allow-plaintext", result.stderr)
        self.assertFalse(self.out.exists() and list(self.out.glob("*.tar*")))

    def test_encrypted_with_recipient_file(self) -> None:
        recipients = Path(self._tmp.name) / "recipients.txt"
        recipients.write_text(RECIPIENT)
        result = self.run_cli("--recipient-file", str(recipients), "--json", plaintext=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = Path(json.loads(result.stdout)["archive"])
        self.assertTrue(archive.name.endswith(".tar.age"))
        identity = Path(self._tmp.name) / "id.txt"
        identity.write_text("unused")
        check = self.run_cli("--verify", str(archive), "--identity", str(identity), plaintext=False)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_corrupt_staged_tar_aborts_encrypted_create(self) -> None:
        from importlib.machinery import SourceFileLoader
        mod = SourceFileLoader("snapmod", str(SCRIPT)).load_module()
        real = mod.write_tar

        def corrupt(archive, workdir, manifest):
            first = next(iter(manifest["members"].values()))
            first["sha256"] = "0" * 64
            real(archive, workdir, manifest)

        recipients = Path(self._tmp.name) / "recipients.txt"
        recipients.write_text(RECIPIENT)
        args = mod.argparse.Namespace(reason="t", recipient_file=recipients, allow_plaintext=False, root=self.root,
                                      etc_dir=self.etc, state_dir=self.state, out_dir=self.out)
        mod.write_tar = corrupt
        old_path = os.environ["PATH"]
        os.environ["PATH"] = self.env["PATH"]
        try:
            with self.assertRaises(mod.SnapshotError):
                mod.create(args)
        finally:
            mod.write_tar = real
            os.environ["PATH"] = old_path
        self.assertEqual(list(self.out.glob("*.tar*")), [])

    def test_private_key_in_recipient_file_is_refused(self) -> None:
        recipients = Path(self._tmp.name) / "recipients.txt"
        recipients.write_text("AGE-SECRET-KEY-1ABCDEF\n")
        result = self.run_cli("--recipient-file", str(recipients), plaintext=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("ABCDEF", result.stdout + result.stderr)

    def test_verify_detects_tampering(self) -> None:
        archive = self.snapshot()
        tampered = archive.with_name("tampered.tar")
        with tarfile.open(archive) as src, tarfile.open(tampered, "w") as dst:
            for member in src:
                data = src.extractfile(member).read()
                if member.name == "etc-argus/control-token":
                    data, member.size = b"changed", 7
                dst.addfile(member, io.BytesIO(data))
        result = self.run_cli("--verify", str(tampered), plaintext=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256 mismatch: etc-argus/control-token", result.stderr)

    def test_m1_verify_failure_aborts_without_archive(self) -> None:
        verify = self.root / "scripts" / "argus-m1-verify"
        verify.write_text("#!/bin/sh\nexit 3\n")
        result = self.run_cli("--reason", "t")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(list(self.out.glob("*.tar*")), [])

    def test_retention_keeps_newest_14_and_pinned(self) -> None:
        self.out.mkdir()
        for day in range(1, 21):
            (self.out / f"202601{day:02d}T000000Z-old.tar").write_bytes(b"x")
        (self.out / "20260101T000000Z-old.tar.pinned").write_text("")
        self.snapshot("new")
        remaining = sorted(p.name for p in self.out.glob("*.tar"))
        self.assertEqual(len(remaining), 15)  # 14 newest + pinned oldest
        self.assertIn("20260101T000000Z-old.tar", remaining)
        self.assertNotIn("20260102T000000Z-old.tar", remaining)

    def test_list_and_restore_plan_are_read_only(self) -> None:
        archive = self.snapshot("plan")
        before = sorted(p.name for p in self.out.iterdir())
        plan = self.run_cli("--restore-plan", str(archive), plaintext=False)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertIn("nothing is restored", plan.stdout)
        self.assertNotIn(SECRET, plan.stdout)
        listing = self.run_cli("--list", plaintext=False)
        self.assertIn(archive.name, listing.stdout)
        self.assertEqual(before, sorted(p.name for p in self.out.iterdir()))


if __name__ == "__main__":
    unittest.main()
