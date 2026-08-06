from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_multimodal_breakout_factory import verify_multimodal_breakout_factory


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-multimodal-breakout-factory-v1.json"


class GTMMultimodalBreakoutFactoryV1Tests(unittest.TestCase):
    def test_b2b_b2c_zero_budget_factories_bind_text_image_video_and_named_stress(self) -> None:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(payload["context_count"], 4)
        self.assertEqual(payload["candidate_campaign_count"], 12)
        self.assertEqual(payload["model_ready_work_order_count"], 36)
        self.assertEqual(payload["zero_budget_context_count"], 4)
        for factory in payload["factories"]:
            verify_multimodal_breakout_factory(factory)
            self.assertEqual(factory["active_named_product_stress_count"], 120)
            self.assertEqual(factory["active_capability_category_count"], 12)
            self.assertTrue(factory["zero_budget_mode"])
            for candidate in factory["candidate_campaigns"]:
                self.assertEqual(candidate["zero_budget_distribution_request"]["paid_media_spend"], 0)
                self.assertIn("text_generation_request", candidate)
                self.assertIn("image_generation_request", candidate)
                self.assertIn("video_generation_request", candidate)
                self.assertEqual(candidate["produced_asset_count"], 0)


if __name__ == "__main__":
    unittest.main()
