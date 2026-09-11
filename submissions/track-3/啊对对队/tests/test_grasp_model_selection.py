from __future__ import annotations

import copy
import unittest

from parcel_sorter.grasp_model_selection import select_grasp_scorer_candidate


PROFILES = (
    "medium_carton",
    "shoe_box_proxy",
    "large_narrow_carton",
    "near_limit_box",
)


def candidate_payload(
    *,
    successes: int = 8,
    safety_aborts: int = 0,
    baseline_successes: int = 4,
    baseline_safety_aborts: int = 4,
    latency_ms: float = 1.0,
) -> dict:
    return {
        "split": "development",
        "dataset_sha256": "d" * 64,
        "checkpoint_sha256": "c" * 64,
        "latency": {"steady_batch_p95_ms": latency_ms},
        "evaluation": {
            "group_count": 16,
            "model_successes": successes,
            "model_safety_aborts": safety_aborts,
            "baseline_successes": baseline_successes,
            "baseline_safety_aborts": baseline_safety_aborts,
            "model_mean_force_n": 12.0,
            "model_mean_duration_seconds": 8.0,
            "per_profile": {
                profile: {
                    "group_count": 4,
                    "model_safety_aborts": (
                        1 if index < safety_aborts else 0
                    ),
                    "baseline_safety_aborts": (
                        1 if index < baseline_safety_aborts else 0
                    ),
                }
                for index, profile in enumerate(PROFILES)
            },
        },
    }


class GraspModelSelectionTests(unittest.TestCase):
    def test_selects_safety_then_success_lexicographically(self) -> None:
        safer = candidate_payload(successes=5, safety_aborts=0)
        more_successful_but_less_safe = candidate_payload(
            successes=10,
            safety_aborts=1,
        )

        result = select_grasp_scorer_candidate(
            (("safer", safer), ("more-successful", more_successful_but_less_safe))
        )

        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["selected"], "safer")
        self.assertFalse(result["holdout_opened"])

    def test_rejects_per_profile_safety_regression(self) -> None:
        payload = candidate_payload()
        payload["evaluation"]["per_profile"]["medium_carton"].update(
            {"model_safety_aborts": 2, "baseline_safety_aborts": 1}
        )
        payload["evaluation"]["model_safety_aborts"] = 2

        result = select_grasp_scorer_candidate((("regressed", payload),))

        self.assertEqual(result["status"], "no_promotion")
        self.assertIn(
            "per_profile_safety_regression",
            result["candidates"][0]["reasons"],
        )

    def test_rejects_no_improvement_and_latency_failure(self) -> None:
        payload = candidate_payload(
            successes=4,
            safety_aborts=4,
            latency_ms=5.0,
        )
        for row in payload["evaluation"]["per_profile"].values():
            row["model_safety_aborts"] = 1

        result = select_grasp_scorer_candidate((("unchanged", payload),))

        reasons = result["candidates"][0]["reasons"]
        self.assertIn("no_task_or_safety_improvement", reasons)
        self.assertIn("radeon_latency_gate_failed", reasons)

    def test_requires_same_dataset(self) -> None:
        left = candidate_payload()
        right = copy.deepcopy(left)
        right["dataset_sha256"] = "e" * 64

        with self.assertRaisesRegex(ValueError, "same dataset"):
            select_grasp_scorer_candidate((("left", left), ("right", right)))


if __name__ == "__main__":
    unittest.main()
