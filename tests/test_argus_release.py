from __future__ import annotations

import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_release as release  # noqa: E402
from argus_cli import run  # noqa: E402

OLD_ID = "sha256:" + "1" * 64
NEW_ID = "sha256:" + "2" * 64
DIGEST = "sha256:" + "d" * 64
REF = f"ghcr.io/pxm-0/nodens@{DIGEST}"
COMPOSE = """# reviewed
name: {name}

services:
  nodens:
    image: {pin}  # {comment}
    restart: unless-stopped
  argus-ingress:
    image: sha256:{caddy}  # caddy
    volumes:
      - source: /var/lib/argus/managed-ingress/{name}
    secrets:
      - {name}-token
networks:
  internal:
    internal: true
"""


def compose(name: str, pin: str, comment: str = "old", caddy: str = "c" * 64) -> str:
    return COMPOSE.format(name=name, pin=pin, comment=comment, caddy=caddy)


def workload(workload_id: str, **extra: object) -> dict[str, object]:
    return {"id": workload_id, "runtime": {"service": "nodens"},
            "migration": {"targetTrustDomain": "personal-managed"}, **extra}


class RewriteTests(unittest.TestCase):
    def test_rewrite_changes_only_the_service_image_line(self) -> None:
        text = compose("nodens-staging", OLD_ID)
        out = release.rewrite_image(text, "nodens", NEW_ID, REF)
        self.assertEqual(f"    image: {NEW_ID}  # {REF}", out.splitlines()[5])
        self.assertEqual(text.splitlines()[:5] + text.splitlines()[6:], out.splitlines()[:5] + out.splitlines()[6:])

    def test_zero_matches_refused(self) -> None:
        text = compose("nodens-staging", OLD_ID).replace(f"    image: {OLD_ID}  # old\n", "")
        with self.assertRaises(release.ReleaseError) as caught:
            release.rewrite_image(text, "nodens", NEW_ID, REF)
        self.assertEqual("compose-image-line-count", caught.exception.code)

    def test_two_matches_refused(self) -> None:
        text = compose("nodens-staging", OLD_ID).replace("    restart", f"    image: {OLD_ID}\n    restart")
        with self.assertRaises(release.ReleaseError) as caught:
            release.rewrite_image(text, "nodens", NEW_ID, REF)
        self.assertIn("found 2", str(caught.exception))

    def test_missing_service_refused(self) -> None:
        with self.assertRaises(release.ReleaseError) as caught:
            release.rewrite_image(compose("x", OLD_ID), "other", NEW_ID, REF)
        self.assertEqual("compose-service-not-found", caught.exception.code)

    def test_ref_validation(self) -> None:
        self.assertTrue(release.valid_ref(REF))
        for bad in ("ghcr.io/pxm-0/nodens:latest", f"ghcr.io/other/nodens@{DIGEST}", f"docker.io/library/nginx@{DIGEST}", REF + "x"):
            with self.subTest(bad=bad):
                self.assertFalse(release.valid_ref(bad))


class DriftTests(unittest.TestCase):
    def test_allowed_fields_and_pin_may_differ(self) -> None:
        staging, production = compose("nodens-staging", NEW_ID, "a"), compose("nodens-production", "sha256:PENDING-x", "b")
        production = production.replace("nodens-production-token", "other-secret")
        self.assertEqual([], release.compose_drift(staging, production, "nodens-staging", "nodens-production", "nodens"))

    def test_other_image_drift_detected(self) -> None:
        drift = release.compose_drift(compose("nodens-staging", NEW_ID), compose("nodens-production", NEW_ID, caddy="e" * 64),
                                      "nodens-staging", "nodens-production", "nodens")
        self.assertTrue(drift)

    def test_repo_promotion_pairs_have_no_compose_drift(self) -> None:
        registry = release.load_registry(ROOT)
        for staging_id, item in registry.items():
            production_id = item.get("promotesTo")
            if not production_id:
                continue
            with self.subTest(staging=staging_id):
                texts = [(ROOT / "workloads" / i / "source" / "compose.yml").read_text() for i in (staging_id, production_id)]
                self.assertEqual([], release.compose_drift(texts[0], texts[1], staging_id, production_id, "nodens"))
                for text in texts:
                    self.assertRegex(release.read_pin(text, "nodens")[0], r"^sha256:([0-9a-f]{64}|PENDING[A-Za-z0-9-]*)$")

    def test_repo_registers_the_nodens_promotion(self) -> None:
        self.assertEqual("nodens-production", release.load_registry(ROOT)["nodens-staging"]["promotesTo"])


FAKE_SSH = """#!/bin/sh
echo "$@" >> "$FAKE_LOG/ssh"
echo '{{"ok": true, "imageId": "{id}"}}'
"""
FAKE_GH = """#!/bin/sh
echo "$@" >> "$FAKE_LOG/gh"
echo https://github.com/pxm-0/argus/pull/999
"""


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo, self.bin, self.log = base / "repo", base / "bin", base / "log"
        for path in (self.repo / "config", self.repo / "scripts", self.bin, self.log):
            path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", str(base / "origin.git")], check=True)
        registry = {"workloads": [workload("nodens-staging", promotesTo="nodens-production"), workload("nodens-production")]}
        (self.repo / "config" / "workloads.json").write_text(json.dumps(registry))
        (self.repo / "config" / "routes.json").write_text(json.dumps({"dashboard": {"url": "https://127.0.0.1:1"}}))
        self.write_compose("nodens-staging", compose("nodens-staging", OLD_ID, REF))
        self.write_compose("nodens-production", compose("nodens-production", "sha256:PENDING-x"))
        self.script("scripts/argus-check", "#!/bin/sh\nexit ${FAKE_CHECK_EXIT:-0}\n", self.repo)
        self.script("ssh", FAKE_SSH.format(id=OLD_ID), self.bin)
        self.script("gh", FAKE_GH, self.bin)
        for args in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                     ["remote", "add", "origin", str(base / "origin.git")]):
            subprocess.run(["git", *args], cwd=self.repo, check=True)
        env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_LOG": str(self.log), "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def script(self, name: str, content: str, parent: Path) -> None:
        path = parent / name
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def write_compose(self, workload_id: str, text: str) -> None:
        path = self.repo / "workloads" / workload_id / "source" / "compose.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def invoke(self, *argv: str) -> tuple[int, dict, str]:
        out, err = io.StringIO(), io.StringIO()
        code = run([*argv, "--json"], repo=self.repo, stdout=out, stderr=err)
        return code, json.loads(out.getvalue()), err.getvalue()

    def calls(self, name: str) -> list[str]:
        path = self.log / name
        return path.read_text().splitlines() if path.exists() else []

    def test_pin_imports_commits_and_opens_pr(self) -> None:
        self.script("ssh", FAKE_SSH.format(id=NEW_ID), self.bin)
        code, payload, _ = self.invoke("release", "pin", "nodens-staging", "--image", REF)
        self.assertEqual(0, code, payload)
        data = payload["data"]
        self.assertEqual(f"release/nodens-staging-{NEW_ID[7:19]}", data["branch"])
        self.assertEqual("https://github.com/pxm-0/argus/pull/999", data["prUrl"])
        self.assertEqual([f"oreochiserver sudo -n argus-image-import --domain personal-managed --image {REF}"], self.calls("ssh"))
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.assertEqual(data["branch"], branch)
        self.assertIn(f"image: {NEW_ID}", (self.repo / "workloads/nodens-staging/source/compose.yml").read_text())
        gh = (self.log / "gh").read_text()
        self.assertTrue(gh.startswith("pr create --base main"))
        self.assertIn(f"argus workload deploy nodens-staging --revision {NEW_ID}", gh)
        for section in ("## P0 Scope", "## Summary", "## Verification", "## Safety Checklist", "## Notes", "## Rollback"):
            self.assertIn(section, gh)

    def test_ssh_host_comes_from_environment(self) -> None:
        with patch.dict(os.environ, {"ARGUS_SSH_HOST": "ops@box"}):
            self.invoke("release", "import", "nodens-staging", "--image", REF)
        self.assertTrue(self.calls("ssh")[0].startswith("ops@box sudo -n"))
        with patch.dict(os.environ, {"ARGUS_SSH_HOST": "-oProxyCommand=x"}):
            code, payload, _ = self.invoke("release", "import", "nodens-staging", "--image", REF)
        self.assertEqual(2, code)
        self.assertEqual("ssh-host-invalid", payload["error"]["code"])

    def test_dry_run_prints_diff_and_touches_nothing(self) -> None:
        before = (self.repo / "workloads/nodens-staging/source/compose.yml").read_text()
        code, payload, _ = self.invoke("release", "pin", "nodens-staging", "--image", REF, "--dry-run")
        self.assertEqual(0, code)
        self.assertIn("+    image: sha256:<image-id-from-import>", payload["data"]["diff"])
        self.assertEqual([], self.calls("ssh") + self.calls("gh"))
        self.assertEqual(before, (self.repo / "workloads/nodens-staging/source/compose.yml").read_text())

    def test_invalid_refs_never_reach_ssh(self) -> None:
        for image in ("ghcr.io/pxm-0/nodens:latest", f"ghcr.io/evil/nodens@{DIGEST}"):
            code, payload, _ = self.invoke("release", "pin", "nodens-staging", "--image", image)
            self.assertEqual((2, "image-ref-invalid"), (code, payload["error"]["code"]))
        self.assertEqual([], self.calls("ssh"))

    def test_failed_check_restores_file_and_opens_nothing(self) -> None:
        self.script("ssh", FAKE_SSH.format(id=NEW_ID), self.bin)
        before = (self.repo / "workloads/nodens-staging/source/compose.yml").read_text()
        with patch.dict(os.environ, {"FAKE_CHECK_EXIT": "1"}):
            code, payload, _ = self.invoke("release", "pin", "nodens-staging", "--image", REF)
        self.assertEqual((1, "repository-check-failed"), (code, payload["error"]["code"]))
        self.assertEqual(before, (self.repo / "workloads/nodens-staging/source/compose.yml").read_text())
        self.assertEqual([], self.calls("gh"))

    def test_dirty_tree_refused(self) -> None:
        (self.repo / "stray").write_text("x")
        code, payload, _ = self.invoke("release", "pin", "nodens-staging", "--image", REF)
        self.assertEqual((3, "worktree-dirty"), (code, payload["error"]["code"]))
        self.assertEqual([], self.calls("gh"))

    def promote_refusal(self, *extra: str) -> str:
        code, payload, _ = self.invoke("promote", "nodens-staging", "nodens-production", *extra)
        self.assertEqual(3, code, payload)
        self.assertEqual([], self.calls("gh"))
        return payload["error"]["code"]

    def test_promote_refuses_without_evidence(self) -> None:
        self.assertEqual("promote-evidence-unavailable", self.promote_refusal())
        self.assertEqual([], self.calls("ssh"))

    def test_promote_refuses_when_staging_lacks_a_succeeded_deploy_of_the_id(self) -> None:
        with patch.object(release, "deploy_evidence", return_value=False):
            self.assertEqual("promote-staging-not-deployed", self.promote_refusal())

    def test_promote_refuses_unregistered_target_and_unpinned_staging(self) -> None:
        registry = json.loads((self.repo / "config/workloads.json").read_text())
        del registry["workloads"][0]["promotesTo"]
        (self.repo / "config/workloads.json").write_text(json.dumps(registry))
        self.assertEqual("promote-target-unregistered", self.promote_refusal("--skip-evidence-check"))

    def test_promote_refuses_unpinned_staging(self) -> None:
        self.write_compose("nodens-staging", compose("nodens-staging", "sha256:PENDING-x"))
        self.assertEqual("promote-staging-unpinned", self.promote_refusal("--skip-evidence-check"))

    def test_promote_refuses_compose_differences(self) -> None:
        self.write_compose("nodens-production", compose("nodens-production", "sha256:PENDING-x").replace("unless-stopped", "always"))
        self.assertEqual("promote-compose-differs", self.promote_refusal("--skip-evidence-check"))
        self.assertEqual([], self.calls("ssh"))

    def test_promote_refuses_when_production_import_reports_another_id(self) -> None:
        self.script("ssh", FAKE_SSH.format(id=NEW_ID), self.bin)
        self.assertEqual("promote-image-id-mismatch", self.promote_refusal("--skip-evidence-check"))

    def test_promote_opens_pr_with_identical_pins(self) -> None:
        code, payload, _ = self.invoke("promote", "nodens-staging", "nodens-production", "--skip-evidence-check")
        self.assertEqual(0, code, payload)
        text = (self.repo / "workloads/nodens-production/source/compose.yml").read_text()
        self.assertEqual(OLD_ID, release.read_pin(text, "nodens")[0])
        self.assertEqual([f"oreochiserver sudo -n argus-image-import --domain personal-managed --image {REF}"], self.calls("ssh"))
        self.assertIn(f"nodens-production: image: {OLD_ID} (was sha256:PENDING-x)", (self.log / "gh").read_text())

    def test_promote_dry_run_prints_diff_only(self) -> None:
        code, payload, _ = self.invoke("promote", "nodens-staging", "nodens-production", "--skip-evidence-check", "--dry-run")
        self.assertEqual(0, code)
        self.assertIn(f"+    image: {OLD_ID}", payload["data"]["diff"])
        self.assertEqual([], self.calls("ssh") + self.calls("gh"))

    def test_deploy_evidence_matches_only_succeeded_deploys_of_the_id(self) -> None:
        def fetch(operations: list[dict]) -> bool:
            body = io.BytesIO(json.dumps({"operations": operations}).encode())
            with patch("urllib.request.urlopen", return_value=body), patch.object(body, "__enter__", lambda *_: body, create=True):
                return release.deploy_evidence(self.repo, "nodens-staging", OLD_ID)
        deploy = {"operation_type": "workload.deploy", "state": "succeeded", "parameters": {"targetRevision": OLD_ID}}
        self.assertTrue(fetch([deploy]))
        self.assertFalse(fetch([{**deploy, "state": "failed"}]))
        self.assertFalse(fetch([{**deploy, "parameters": {"targetRevision": NEW_ID}}]))


if __name__ == "__main__":
    unittest.main()
