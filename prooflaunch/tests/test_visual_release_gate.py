from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.visual_release_gate import evaluate_visual_release, fuzzy_contains


ROOT = Path(__file__).resolve().parents[1]


class VisualReleaseGateTests(unittest.TestCase):
    def test_fuzzy_contains_tolerates_one_ocr_error(self) -> None:
        score = fuzzy_contains("OUR AI PROMISED V1RAL", "OUR AI PROMISED VIRAL")
        self.assertGreaterEqual(score, 0.9)

    def test_gate_blocks_canvas_extra_copy_and_repetition(self) -> None:
        observation = {
            "width": 1072,
            "height": 1344,
            "full_text": "NO WITNESS PUBLIC SELF CROSS EXAMINATION PUT YOUR CLAIM ON TRIAL PUT YOUR CLAIM ON TRIAL",
            "luminance_dynamic_range": 0.8,
            "observations": [{"confidence": 0.98}],
        }
        result = evaluate_visual_release(
            artifact_id="fixture",
            expected_width=1080,
            expected_height=1350,
            observation=observation,
            required_phrases=["NO WITNESS"],
            forbidden_phrases=["PUBLIC SELF CROSS EXAMINATION"],
            maximum_occurrences={"PUT YOUR CLAIM ON TRIAL": 1},
        )
        self.assertFalse(result["release_ready"])
        self.assertEqual({failure["gate"] for failure in result["failures"]}, {"exact_canvas", "forbidden_copy", "duplicate_copy"})

    def test_real_audit_is_sealed_and_keeps_effect_boundary(self) -> None:
        path = ROOT / "evidence/v10/claim-trial-visual-release-gate-v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(supplied, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(payload["artifact_count"], 3)
        self.assertIn("not a preference vote", payload["truth_boundary"].lower())


if __name__ == "__main__":
    unittest.main()
