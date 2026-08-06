from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_amd_public_export import select_public_files  # noqa: E402
from validate_amd_public_export import scan_high_confidence_secret  # noqa: E402


class AMDPublicExportTests(unittest.TestCase):
    def test_selection_is_explicit_and_excludes_private_roots(self) -> None:
        relative = {path.relative_to(ROOT).as_posix() for path in select_public_files()}
        self.assertIn("README.md", relative)
        self.assertIn("docs/ProofLaunch_Submission_Deck.pptx", relative)
        self.assertIn("demos/run_track1_demo.py", relative)
        self.assertIn("evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json", relative)
        for path in relative:
            self.assertNotIn(".prooflaunch-secrets", path)
            self.assertNotIn(".prooflaunch-runtime", path)
            self.assertNotIn(".super-site-10x", path)
            self.assertNotIn("node_modules", path)
            self.assertNotIn("__pycache__", path)
            self.assertFalse(path.startswith("data/tokenfactory_teacher_v10/"))

    def test_high_confidence_secret_scanner(self) -> None:
        self.assertEqual(scan_high_confidence_secret(b"PROOFLAUNCH_TOKEN="), [])
        self.assertIn(
            "github_token",
            scan_high_confidence_secret(b"ghp_" + b"1234567890abcdefghijklmnop"),
        )


if __name__ == "__main__":
    unittest.main()
