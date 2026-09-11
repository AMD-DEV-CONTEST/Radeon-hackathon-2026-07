import unittest

from parcel_sorter.harness import select_residual_candidate
from parcel_sorter.self_improvement import (
    build_failure_replay_manifest,
    promotion_gate,
)


def _episode(index: int, *, success: bool, force: float = 0.0) -> dict:
    return {
        "episode_index": index,
        "sample": {
            "profile_id": "small_carton",
            "dimensions_m": [0.16, 0.06, 0.08],
            "shape": "box",
            "orientation_mode": "yaw",
            "position_xy": [0.6, 0.0],
            "yaw_rad": 0.0,
            "mass_kg": 0.2,
            "friction": 0.8,
            "action_delay_steps": 0,
        },
        "trace": [
            {
                "stage": "complete" if success else "abort",
                "reason": "parcel sorted" if success else "grasp verification failed",
                "contact_force_n": force,
                "at_pregrasp": True,
                "grasp_contact": success,
                "parcel_lifted": success,
            }
        ],
        "terminal_stage": "complete" if success else "abort",
        "result": {"success": success, "dropped": False, "max_contact_force_n": force},
    }


class HarnessTests(unittest.TestCase):
    def test_first_attempt_quarantines_vla_residual(self) -> None:
        decision = select_residual_candidate(
            current_position_m=(0.0, 0.0, 0.0),
            expert_target_m=(0.04, 0.0, 0.0),
            vla_target_m=(0.05, 0.0, 0.0),
            residual_limit_m=0.01,
            min_progress_ratio=0.5,
            force_n=2.0,
            force_limit_n=35.0,
        )
        self.assertTrue(decision.fallback_to_expert)
        self.assertEqual(decision.selected.scale, 0.0)
        self.assertEqual(len(decision.candidates), 4)

    def test_retry_selects_verified_backoff_but_blocks_forward_amplification(self) -> None:
        backoff = select_residual_candidate(
            current_position_m=(0.0, 0.0, 0.0),
            expert_target_m=(0.04, 0.0, 0.0),
            vla_target_m=(0.03, 0.0, 0.0),
            residual_limit_m=0.01,
            min_progress_ratio=0.5,
            force_n=2.0,
            force_limit_n=35.0,
            recovery_active=True,
        )
        self.assertFalse(backoff.fallback_to_expert)
        self.assertLess(backoff.selected.target_position_m[0], 0.04)
        forward = select_residual_candidate(
            current_position_m=(0.0, 0.0, 0.0),
            expert_target_m=(0.04, 0.0, 0.0),
            vla_target_m=(0.05, 0.0, 0.0),
            residual_limit_m=0.01,
            min_progress_ratio=0.5,
            force_n=2.0,
            force_limit_n=35.0,
            recovery_active=True,
        )
        self.assertLessEqual(forward.selected.target_position_m[0], 0.04)
        self.assertLessEqual(forward.selected.progress_ratio, 1.0)

    def test_force_gate_falls_back_to_expert(self) -> None:
        decision = select_residual_candidate(
            current_position_m=(0.0, 0.0, 0.0),
            expert_target_m=(0.04, 0.0, 0.0),
            vla_target_m=(0.05, 0.0, 0.0),
            residual_limit_m=0.01,
            min_progress_ratio=0.5,
            force_n=35.0,
            force_limit_n=35.0,
        )
        self.assertTrue(decision.fallback_to_expert)
        self.assertEqual(decision.selected.scale, 0.0)


class SelfImprovementTests(unittest.TestCase):
    def test_failure_manifest_excludes_holdout_and_prioritizes_force(self) -> None:
        summary = {"episodes": [_episode(1, success=False, force=40.0), _episode(2, success=False), _episode(3, success=True)]}
        manifest = build_failure_replay_manifest(summary, holdout_episode_ids=[2])
        self.assertEqual([item["episode_index"] for item in manifest["items"]], [1])
        self.assertEqual(manifest["items"][0]["failure_mode"], "force_safety_abort")

    def test_promotion_requires_target_and_improvement(self) -> None:
        baseline = {"episodes": [_episode(index, success=index < 70) for index in range(100)]}
        candidate = {"episodes": [_episode(index, success=index < 82) for index in range(100)]}
        gate = promotion_gate(baseline, candidate, target_success_rate=0.80, min_delta=0.02)
        self.assertTrue(gate["promoted"])
        weaker = {"episodes": [_episode(index, success=index < 79) for index in range(100)]}
        self.assertFalse(promotion_gate(baseline, weaker)["promoted"])


if __name__ == "__main__":
    unittest.main()
