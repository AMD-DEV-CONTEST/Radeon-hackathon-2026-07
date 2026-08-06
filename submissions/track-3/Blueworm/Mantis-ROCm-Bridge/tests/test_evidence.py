from __future__ import annotations

import unittest

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.evidence import evaluate_promotion, summarize_episodes, validate_episodes


HASH = "a" * 64
TAXONOMY = ["missed_grasp", "collision_safety", "runtime_error"]


def episode(seed: int, success: bool, failure_stage: str | None = None) -> dict:
    return {
        "protocol": "g3_compare",
        "seed": seed,
        "checkpoint_sha256": HASH,
        "success": success,
        "failure_stage": failure_stage,
        "policy_steps": 100,
        "graded_score": 1.0 if success else 0.0,
    }


class EvidenceTests(unittest.TestCase):
    def test_summary_and_promotion(self) -> None:
        episodes = [episode(seed, seed < 6, None if seed < 6 else "missed_grasp") for seed in range(10)]
        validated = validate_episodes(episodes, TAXONOMY, range(10))
        summary = summarize_episodes(validated)
        promotion = evaluate_promotion(
            summary, {"minimum_success_rate": 0.6, "maximum_safety_failures": 0}
        )
        self.assertEqual(summary["successes"], 6)
        self.assertEqual(summary["safety_failures"], 0)
        self.assertTrue(promotion["passed"])

    def test_duplicate_seed_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            validate_episodes([episode(1, True), episode(1, True)], TAXONOMY)

    def test_failed_episode_requires_frozen_failure_stage(self) -> None:
        with self.assertRaises(ContractError):
            validate_episodes([episode(1, False, "unknown")], TAXONOMY)

    def test_safety_failure_blocks_promotion(self) -> None:
        episodes = [episode(seed, True) for seed in range(9)] + [
            episode(9, False, "collision_safety")
        ]
        summary = summarize_episodes(validate_episodes(episodes, TAXONOMY))
        promotion = evaluate_promotion(
            summary, {"minimum_success_rate": 0.6, "maximum_safety_failures": 0}
        )
        self.assertFalse(promotion["passed"])


if __name__ == "__main__":
    unittest.main()

