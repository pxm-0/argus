from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_common  # noqa: E402
from argus_access_state import AccessStateError, load_access, merge_access, orphans, read_overlay  # noqa: E402


TRACKED = {
    "version": 1,
    "states": ["none", "local", "tailnet", "cloudflare-protected"],
    "workloads": {
        "site": {"desired": "cloudflare-protected", "effective": "none", "urls": {"local": "x"}, "lastAppliedAt": "", "lastError": ""},
        "tool": {"desired": "tailnet", "effective": "tailnet", "urls": {}, "lastAppliedAt": "a", "lastError": ""},
    },
}
ENTRY = {"effective": "cloudflare-protected", "lastAppliedAt": "2026-11-01T00:00:00Z", "lastError": ""}


def overlay(**workloads: dict) -> dict:
    return {"version": 1, "workloads": workloads}


class AccessStateTests(unittest.TestCase):
    def write(self, directory: Path, value: object) -> None:
        (directory / "access.effective.json").write_text(value if isinstance(value, str) else json.dumps(value))

    def test_missing_overlay_gives_the_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "access.json").write_text(json.dumps(TRACKED))
            self.assertEqual(TRACKED, load_access(Path(directory)))

    def test_only_the_three_fields_are_overridden_and_orphans_are_ignored(self) -> None:
        merged = merge_access(TRACKED, overlay(site=ENTRY, gone=ENTRY))
        self.assertEqual({**TRACKED["workloads"]["site"], **ENTRY}, merged["workloads"]["site"])
        self.assertEqual(TRACKED["workloads"]["tool"], merged["workloads"]["tool"])
        self.assertNotIn("gone", merged["workloads"])
        self.assertEqual(["gone"], orphans(TRACKED, overlay(site=ENTRY, gone=ENTRY)))

    def test_inputs_are_not_mutated(self) -> None:
        tracked, layer = copy.deepcopy(TRACKED), overlay(site=ENTRY)
        merged = merge_access(tracked, layer)
        merged["workloads"]["site"]["urls"]["local"] = "changed"
        self.assertEqual(TRACKED, tracked)
        self.assertEqual(overlay(site=ENTRY), layer)

    def test_invalid_overlays_raise(self) -> None:
        cases = {
            "malformed JSON": "{",
            "wrong version": {"version": 2, "workloads": {}},
            "extra top-level key": {"version": 1, "workloads": {}, "desired": {}},
            "extra entry key": overlay(site={**ENTRY, "desired": "tailnet"}),
            "missing entry key": overlay(site={"effective": "none"}),
            "non-string value": overlay(site={**ENTRY, "lastError": None}),
            "not an object": [],
        }
        for name, value in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                self.write(Path(directory), value)
                with self.assertRaises(AccessStateError):
                    read_overlay(Path(directory))

    def test_state_outside_the_tracked_states_raises(self) -> None:
        with self.assertRaises(AccessStateError):
            merge_access(TRACKED, overlay(site={**ENTRY, "effective": "cloudflare-public"}))

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_unreadable_overlay_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.write(Path(directory), overlay())
            (Path(directory) / "access.effective.json").chmod(0)
            with self.assertRaisesRegex(AccessStateError, "unreadable"):
                read_overlay(Path(directory))

    def test_common_loader_merges_access_and_refuses_to_save_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ARGUS_ROOT": directory}):
            config = Path(directory) / "config"
            config.mkdir()
            (config / "access.json").write_text(json.dumps(TRACKED))
            self.write(config, overlay(site=ENTRY))
            self.assertEqual("cloudflare-protected", argus_common.load_json("access.json")["workloads"]["site"]["effective"])
            with self.assertRaises(SystemExit):
                argus_common.save_json("access.json", TRACKED)
            self.assertEqual(TRACKED, json.loads((config / "access.json").read_text()))
            self.assertEqual("", argus_common.desired_change_refusal("site", "cloudflare-protected"))
            self.assertIn("reviewed pull request", argus_common.desired_change_refusal("site", "tailnet"))
            self.write(config, overlay(site={**ENTRY, "effective": "bogus"}))
            with self.assertRaises(SystemExit):
                argus_common.load_json("access.json")

    def test_tracked_config_never_holds_a_cloudflare_effective(self) -> None:
        tracked = json.loads((ROOT / "config" / "access.json").read_text())
        cloudflare = [key for key, item in tracked["workloads"].items() if str(item.get("effective", "")).startswith("cloudflare")]
        self.assertEqual([], cloudflare)


if __name__ == "__main__":
    unittest.main()
