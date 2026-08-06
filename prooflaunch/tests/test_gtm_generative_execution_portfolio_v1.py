from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-generative-execution-kernel-v1.json"


class GTMGenerativeExecutionPortfolioV1Tests(unittest.TestCase):
    def test_portfolio_has_b2b_b2c_platform_and_nonrepeat_coverage(self) -> None:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(payload["context_count"], 4)
        self.assertEqual(payload["candidate_blueprint_count"], 96)
        self.assertEqual(payload["next_wave_nonrepeating_candidate_count"], 24)
        self.assertEqual(payload["next_wave_overlap_count"], 0)
        self.assertEqual(set(payload["platforms"]), {"linkedin", "reddit", "tiktok", "instagram"})
        self.assertEqual(payload["generated_content_count"], 0)
        self.assertEqual(payload["external_action_count"], 0)
        self.assertEqual(payload["named_product_win_count"], 0)
        self.assertEqual(payload["learning_memory_status"], "empty_awaiting_named_human_approved_effect_evidence")
        self.assertEqual(payload["learning_memory_binding"]["record_count"], 0)
        self.assertTrue(all(
            kernel["generalization_contract"]["learning_memory_sha256"]
            == payload["learning_memory_binding"]["content_sha256"]
            for kernel in payload["kernels"]
        ))


if __name__ == "__main__":
    unittest.main()
