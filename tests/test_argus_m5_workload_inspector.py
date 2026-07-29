from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "argus_m5_dashboard_generator",
        ROOT / "control-plane" / "dashboard" / "generate_dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WorkloadInspectorTests(unittest.TestCase):
    def test_generated_inspector_preserves_private_session_and_operation_contract(self) -> None:
        generator = load_generator()
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            with patch.object(generator, "PUBLIC", public):
                self.assertEqual(0, generator.main())
            html = (public / "index.html").read_text()
            css = (public / "style.css").read_text()
            javascript = (public / "app.js").read_text()

        for marker in (
            'id="command-assurance"',
            'aria-labelledby="command-title"',
            'aria-live="polite"',
            "Durable history",
            "Declared access",
            "Observed access",
            "Effective access",
            "Health evidence",
            "Disabled operation reasons",
            "Run migration preflight",
            "migration.preflight",
            "Migration readiness",
        ):
            self.assertIn(marker, html + javascript)
        self.assertIn("document.visibilityState", javascript)
        self.assertIn("activeOperationPolls", javascript)
        self.assertIn("History temporarily unavailable.", javascript)
        self.assertIn(
            "Operator session expired; authenticate to restore history.",
            javascript,
        )
        self.assertIn("data-view-operation", javascript)
        self.assertIn("data-resume-operation", javascript)
        self.assertIn("operation approval requires", (ROOT / "control-plane" / "api" / "server.py").read_text())
        self.assertNotIn("localStorage.setItem(\"argus", javascript.replace('localStorage.setItem("argus-theme"', ""))
        self.assertNotIn("headers.Authorization", javascript)
        self.assertIn("focus({ preventScroll: true })", javascript)
        self.assertNotIn(
            'showCommandResult("Operator authentication"',
            javascript,
        )
        self.assertIn("@media(max-width:520px)", css)


if __name__ == "__main__":
    unittest.main()
