import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RenderModelBaselineTests(unittest.TestCase):
    def test_renderer_emits_svg_from_public_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.svg"
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts" / "render_model_baseline.py"),
                    "--input",
                    str(ROOT / "evidence" / "radeon-baseline.json"),
                    "--output",
                    str(output),
                ],
                check=True,
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertTrue(rendered.startswith("<svg"))
            self.assertIn("Gemma", rendered)
            self.assertIn("86.5 tok/s", rendered)

    def test_public_evidence_has_unique_candidate_profiles(self):
        payload = json.loads((ROOT / "evidence" / "radeon-baseline.json").read_text(encoding="utf-8"))
        profiles = [candidate["profile_id"] for candidate in payload["candidates"]]
        self.assertEqual(len(profiles), len(set(profiles)))
        self.assertEqual(sum(item["decision"] == "selected_baseline" for item in payload["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()
