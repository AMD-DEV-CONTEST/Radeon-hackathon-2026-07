from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgencyCorpusFreezeTests(unittest.TestCase):
    def test_freeze_gate_keeps_v2_open_until_real_five_human_gold_pass(self) -> None:
        root = ROOT / "data/v10_agency_corpus_v2"
        gate = json.loads((root / "freeze-gate.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["status"], "not_frozen_pending_required_evidence")
        self.assertFalse(gate["frozen"])
        self.assertTrue(all(row["passed"] for row in gate["component_audits"]))
        self.assertFalse(gate["human_requirements"]["five_distinct_human_reviewers"])
        self.assertFalse(gate["human_requirements"]["all_2250_reviews_complete"])
        self.assertFalse(gate["human_requirements"]["all_450_cases_complete"])
        self.assertFalse(gate["human_requirements"]["mean_at_least_4_7"])
        self.assertFalse(gate["human_requirements"]["human_promotion_passed"])
        self.assertGreaterEqual(gate["blocker_count"], 5)
        self.assertFalse(gate["training_observed"])
        self.assertFalse(gate["radeon_inference_observed"])
        self.assertFalse((root / "freeze-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
