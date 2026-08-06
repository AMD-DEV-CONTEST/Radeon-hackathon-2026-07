from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-generative-generalization-matrix-v1.json"


class GTMGeneralizationMatrixV1Tests(unittest.TestCase):
    def test_matrix_covers_surfaces_models_lifecycles_and_nonrepeating_waves(self) -> None:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(payload["surface_count"], 13)
        self.assertEqual(payload["context_count"], 104)
        self.assertEqual(payload["compiled_blueprint_count"], 1664)
        self.assertEqual(set(payload["business_models"]), {"b2b", "b2c"})
        self.assertEqual(set(payload["lifecycles"]), {"pre_pmf", "launch", "growth", "mature"})
        self.assertEqual(set(payload["budgets"]), {"zero", "small", "scaled", "enterprise"})
        self.assertTrue(payload["all_next_waves_zero_overlap"])
        self.assertTrue(payload["all_batches_diverse"])
        self.assertEqual(payload["generated_content_count"], 0)
        self.assertEqual(payload["external_action_count"], 0)
        self.assertEqual(payload["breakout_claim_count"], 0)
        self.assertTrue(all(row["next_wave_overlap_count"] == 0 for row in payload["contexts"]))
        self.assertTrue(all(row["minimum_first_wave_axis_distance"] >= 3 for row in payload["contexts"]))


if __name__ == "__main__":
    unittest.main()
