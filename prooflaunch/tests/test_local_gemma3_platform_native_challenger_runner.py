from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts/run_local_gemma3_platform_native_challenger.py"
SPEC = importlib.util.spec_from_file_location("platform_native_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load platform-native runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class LocalGemma3PlatformNativeRunnerTests(unittest.TestCase):
    def test_repair_prompt_binds_prior_draft_and_preserves_passing_fields(self) -> None:
        raw = '{"hook":"A passing hook stays fixed","progression":["thin"]}'
        prompt = RUNNER._repair_prompt(
            "ORIGINAL_CONTRACT",
            raw,
            ("progression_beat_is_a_label_not_an_editorial_move",),
        )
        self.assertIn("PRIOR_DRAFT=" + raw, prompt)
        self.assertIn("edit only the fields implicated", prompt)
        self.assertIn("preserve every passing field verbatim", prompt)
        self.assertIn("at least nine words", prompt)
        self.assertNotIn("Rewrite the complete JSON from scratch", prompt)


if __name__ == "__main__":
    unittest.main()
