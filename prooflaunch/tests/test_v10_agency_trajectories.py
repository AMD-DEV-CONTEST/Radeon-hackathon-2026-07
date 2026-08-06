from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgencyTrajectoryCorpusTests(unittest.TestCase):
    def test_independent_replay_proves_exact_1000_visible_source_bound_trajectories(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/agency-trajectories-1000-independent-replay.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_exact_1000_visible_replay_not_training")
        self.assertEqual(report["trajectory_count"], 1_000)
        self.assertEqual(report["reused_existing_count"], 456)
        self.assertEqual(report["newly_constructed_count"], 544)
        self.assertEqual(report["train_count"], 900)
        self.assertEqual(report["validation_count"], 100)
        self.assertEqual(report["generated_replay_count"], 544)
        self.assertEqual(report["unique_trace_count"], 1_000)
        self.assertEqual(report["outcome_kind_count"], 6)
        self.assertTrue(report["group_safe_split"])
        self.assertTrue(report["all_generated_events_replayed"])
        self.assertEqual(report["hidden_chain_of_thought_count"], 0)
        self.assertEqual(report["rights_failure_count"], 0)
        self.assertEqual(report["failure_count"], 0)
        self.assertFalse(report["model_teacher_used"])
        self.assertFalse(report["human_reviewed"])
        self.assertFalse(report["training_observed"])


if __name__ == "__main__":
    unittest.main()
