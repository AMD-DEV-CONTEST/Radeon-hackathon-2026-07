from __future__ import annotations

import unittest

from scripts.evaluate_grasp_scorer import latency_rows


class GraspScorerEvaluationTests(unittest.TestCase):
    def test_selects_one_real_group_for_latency(self) -> None:
        rows = [
            {"group_id": "profile:1", "candidate_id": "a"},
            {"group_id": "profile:1", "candidate_id": "b"},
            {"group_id": "profile:2", "candidate_id": "c"},
        ]

        selected = latency_rows(rows, "profile:1")

        self.assertEqual([row["candidate_id"] for row in selected], ["a", "b"])

    def test_preserves_all_rows_when_group_is_unspecified(self) -> None:
        rows = [{"group_id": "profile:1", "candidate_id": "a"}]

        self.assertIs(latency_rows(rows, None), rows)

    def test_rejects_unknown_latency_group(self) -> None:
        rows = [{"group_id": "profile:1", "candidate_id": "a"}]

        with self.assertRaisesRegex(ValueError, "absent"):
            latency_rows(rows, "profile:2")


if __name__ == "__main__":
    unittest.main()
