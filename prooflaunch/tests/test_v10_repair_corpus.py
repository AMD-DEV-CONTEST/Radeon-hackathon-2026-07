from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepairCorpusTests(unittest.TestCase):
    def test_independent_audit_proves_exact_500_source_bound_repair_episodes(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/repair-episodes-500-independent-audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_exact_500_repair_records_not_training")
        self.assertEqual(report["repair_episode_count"], 500)
        self.assertEqual(report["train_count"], 450)
        self.assertEqual(report["validation_count"], 50)
        self.assertEqual(set(report["failure_family_counts"].values()), {50})
        self.assertEqual(len(report["failure_family_counts"]), 10)
        self.assertTrue(report["all_records_independently_reconstructed"])
        self.assertEqual(report["duplicate_id_count"], 0)
        self.assertEqual(report["duplicate_content_count"], 0)
        self.assertEqual(report["rights_failure_count"], 0)
        self.assertEqual(report["hidden_chain_of_thought_count"], 0)
        self.assertEqual(report["failure_count"], 0)
        self.assertFalse(report["teacher_model_used"])
        self.assertFalse(report["human_reviewed"])
        self.assertFalse(report["training_observed"])


if __name__ == "__main__":
    unittest.main()
