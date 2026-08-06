from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgencyCorpusDatasetCardTests(unittest.TestCase):
    def test_published_card_binds_all_counts_and_keeps_human_runtime_gates_open(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/agency-corpus-v2-dataset-card-audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_published_pre_release_card_not_frozen")
        self.assertEqual(report["component_count"], 9)
        self.assertEqual(report["headline_counts"]["cpt_tokens"], 15_000_000)
        self.assertEqual(report["headline_counts"]["visible_trajectories"], 1_000)
        self.assertEqual(report["headline_counts"]["repair_episodes"], 500)
        self.assertEqual(report["headline_counts"]["planned_human_reviews"], 2_250)
        self.assertEqual(report["human_reviews_observed"], 0)
        self.assertIsNone(report["human_mean_score"])
        self.assertFalse(report["training_observed"])
        self.assertFalse(report["radeon_inference_observed"])
        self.assertFalse(report["corpus_frozen"])
        self.assertTrue(report["all_component_hashes_recomputed"])
        self.assertEqual(report["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
