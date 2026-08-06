from __future__ import annotations

import math
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.lerobot_dense_gate import audit_dense_rows


ROOT = Path(__file__).resolve().parents[1]
GATE = load_json(ROOT / "configs/dense-dataset-gate-v1.json")


class LeRobotDenseGateTests(unittest.TestCase):
    def rows(self, *, frame_gap: bool = False):
        rows = []
        index = 0
        for episode in range(2):
            for frame in range(40):
                actual_frame = frame + 1 if frame_gap and episode == 1 and frame >= 20 else frame
                action = [0.01 * math.sin(frame / 4.0 + joint) for joint in range(16)]
                rows.append(
                    {
                        "index": index,
                        "episode_index": episode,
                        "frame_index": actual_frame,
                        "timestamp": frame / 30.0,
                        "observation.state": [value * 0.9 for value in action],
                        "action": action,
                    }
                )
                index += 1
        return rows

    def outcomes(self):
        return {
            "episodes": [
                {
                    "episode_index": episode,
                    "task_id": "stack_bowls_three",
                    "protocol": "competition_strict_v1",
                    "success": True,
                    "safety_failures": 0,
                    "physics_divergence": False,
                }
                for episode in range(2)
            ]
        }

    def test_dense_strict_expert_dataset_passes(self) -> None:
        receipt = audit_dense_rows(
            self.rows(),
            gate=GATE,
            expected_total_frames=80,
            expected_total_episodes=2,
            outcomes=self.outcomes(),
        )
        self.assertTrue(receipt["dense_demonstration_gate_pass"])
        self.assertEqual(receipt["successful_outcomes"], 2)

    def test_frame_gap_is_rejected(self) -> None:
        receipt = audit_dense_rows(
            self.rows(frame_gap=True),
            gate=GATE,
            expected_total_frames=80,
            expected_total_episodes=2,
            outcomes=self.outcomes(),
        )
        self.assertFalse(receipt["dense_demonstration_gate_pass"])
        self.assertTrue(
            any(issue.startswith("frame_index_discontinuity") for issue in receipt["issues"])
        )

    def test_missing_strict_outcomes_is_rejected(self) -> None:
        receipt = audit_dense_rows(
            self.rows(),
            gate=GATE,
            expected_total_frames=80,
            expected_total_episodes=2,
            outcomes={},
        )
        self.assertFalse(receipt["dense_demonstration_gate_pass"])
        self.assertIn("episode_outcomes_missing", receipt["issues"])
        self.assertIn("episode_outcome_coverage_mismatch", receipt["issues"])


if __name__ == "__main__":
    unittest.main()
