from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "evidence/v10/delete-one-line-three-lane-named-pk-portfolio-v1.json"


class DeleteOneLineNamedPKPortfolioTests(unittest.TestCase):
    def test_three_lanes_bind_thirty_named_rows_without_claiming_results(self) -> None:
        payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(payload["lane_count"], 3)
        self.assertEqual(payload["named_product_row_count"], 30)
        self.assertEqual(len(payload["rows"]), 30)
        self.assertEqual(len({row["row_id"] for row in payload["rows"]}), 30)
        self.assertEqual({row["category_id"] for row in payload["rows"]}, {"text_content_generation", "content_scheduling_operations", "gtm_lifecycle_orchestration"})
        self.assertTrue(all(row["opponent_specific_stress_test"] for row in payload["rows"]))
        self.assertTrue(all(not row["authorized_named_product_baseline_present"] for row in payload["rows"]))
        self.assertTrue(all(not row["candidate_won"] for row in payload["rows"]))
        self.assertEqual(payload["completed_named_product_pk_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        self.assertEqual(payload["effect_aligned_lane_count"], 0)
        for lane in payload["lanes"]:
            for binding in [lane["candidate_binding"], *lane["support_bindings"]]:
                path = ROOT / binding["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), binding["sha256"])


if __name__ == "__main__":
    unittest.main()
