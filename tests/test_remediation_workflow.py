from __future__ import annotations

import os
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RemediationWorkflowTests(unittest.TestCase):
    def run_guard(self, body: str, *, base: str = "main") -> subprocess.CompletedProcess[str]:
        workflow = (ROOT / ".github" / "workflows" / "p0-pr-guard.yml").read_text()
        embedded = workflow.split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
        environment = os.environ.copy()
        environment.update({"PR_BASE": base, "PR_BODY": body})
        return subprocess.run(
            ["python3", "-c", textwrap.dedent(embedded)],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    def valid_body(self) -> str:
        return """## P0 Scope
## Verification
## Safety Checklist
- [x] This PR is phase-scoped
- [x] No secrets
- [x] No Tailscale Funnel was enabled.
- [x] No Cloudflare tunnel was started or enabled.
- [x] No DNS records were created.
- [x] No router ports were opened.
- [x] No public route was exposed.
Acceptance summaries
- [x] Acceptance summary N/A (docs-only or no server evidence required); reason documented in Notes.
## Notes
- Local-only code and documentation; no server evidence required.
"""

    def test_p0_guard_requires_remediation_branches_to_target_main(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "p0-pr-guard.yml").read_text()
        self.assertIn("github.base_ref", workflow)
        self.assertIn('if base != "main"', workflow)
        self.assertNotIn("head.startswith", workflow)
        self.assertIn("remediation PRs must target main", workflow)
        self.assertIn('"Acceptance summaries"', workflow)
        self.assertIn("Acceptance summary attached above", workflow)
        self.assertIn("Acceptance summary N/A", workflow)
        self.assertEqual(0, self.run_guard(self.valid_body()).returncode)
        self.assertNotEqual(0, self.run_guard(self.valid_body(), base="argus").returncode)

        attached_without_digests = self.valid_body().replace(
            "- [x] Acceptance summary N/A (docs-only or no server evidence required); reason documented in Notes.",
            "- [x] Acceptance summary attached above.",
        )
        self.assertNotEqual(0, self.run_guard(attached_without_digests).returncode)
        fake_digests = attached_without_digests.replace(
            "Acceptance summaries",
            "Acceptance summaries\nsha256:x sha256:y",
        )
        self.assertNotEqual(0, self.run_guard(fake_digests).returncode)
        valid_row = (
            "| cross-project-reachability | baseline | oreochiserver | 3/3 | fail | "
            "`sha256:" + "a" * 64 + "` | `sha256:" + "b" * 64 + "` |"
        )
        attached = attached_without_digests.replace("Acceptance summaries", "Acceptance summaries\n" + valid_row)
        self.assertEqual(0, self.run_guard(attached).returncode)

    def test_current_documentation_has_distinct_paths(self) -> None:
        index = (ROOT / "docs" / "README.md").read_text()
        for heading in ("## Operator", "## Contributor", "## Architecture", "## Historical Record"):
            self.assertIn(heading, index)
        operations = (ROOT / "docs" / "OPERATIONS.md").read_text()
        self.assertIn("argus dashboard url", operations)
        self.assertIn("argus workload show <id>", operations)
        self.assertIn("argus workload move preview <id>", operations)
        self.assertNotIn("scripts/argus-open intake-os --mode tailnet", operations)
        self.assertNotIn("http://<tailscale-ip>:8088", operations)


if __name__ == "__main__":
    unittest.main()
