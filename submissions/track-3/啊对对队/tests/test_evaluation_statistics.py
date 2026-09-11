import unittest

from parcel_sorter.evaluation_statistics import (
    build_campaign_evaluation,
    exact_mcnemar_test,
    paired_mean_difference,
)


def _run(successes: tuple[bool, ...], forces: tuple[float, ...]) -> dict:
    episodes = []
    for index, (success, force) in enumerate(zip(successes, forces, strict=True)):
        episodes.append(
            {
                "episode_index": index,
                "sample": {
                    "episode_index": index,
                    "profile_id": "small" if index % 2 == 0 else "large",
                },
                "result": {
                    "success": success,
                    "dropped": False,
                    "max_contact_force_n": force,
                    "duration_seconds": 10.0 + index,
                    "inference_latency_ms": [1.0, 2.0],
                },
                "safety_summary": {
                    "grasp_plan_attempts": 1,
                    "grasp_plan_compute_ms_total": 4.0,
                },
            }
        )
    return {
        "config": {"task": {"max_contact_force_n": 35.0}},
        "summary": {"successful_parcels_per_hour": 100.0},
        "episodes": episodes,
    }


class EvaluationStatisticsTests(unittest.TestCase):
    def test_exact_mcnemar_uses_discordant_pairs(self) -> None:
        result = exact_mcnemar_test(
            (False, False, False, True, True),
            (True, True, True, False, True),
        )
        self.assertEqual(result["baseline_only_positive"], 1)
        self.assertEqual(result["candidate_only_positive"], 3)
        self.assertEqual(result["discordant_pairs"], 4)
        self.assertEqual(result["p_value_two_sided_exact"], 0.625)

    def test_paired_mean_difference_is_deterministic(self) -> None:
        first = paired_mean_difference((1.0, 2.0), (2.0, 3.0), bootstrap_samples=50)
        second = paired_mean_difference((1.0, 2.0), (2.0, 3.0), bootstrap_samples=50)
        self.assertEqual(first, second)
        self.assertEqual(first["mean_difference_candidate_minus_baseline"], 1.0)
        self.assertEqual(first["bootstrap_ci95_low"], 1.0)

    def test_campaign_report_contains_matched_and_stratified_statistics(self) -> None:
        baseline = _run((False, True, False, True), (50.0, 20.0, 45.0, 15.0))
        candidate = _run((True, True, True, True), (20.0, 18.0, 22.0, 14.0))
        result = build_campaign_evaluation(
            {"historical": baseline, "geometry": candidate},
            "historical",
        )

        self.assertEqual(result["episode_count"], 4)
        comparison = result["comparisons_to_reference"]["geometry"]
        self.assertEqual(
            comparison["binary_metrics"]["success"]["mcnemar"][
                "candidate_only_positive"
            ],
            2,
        )
        self.assertEqual(set(comparison["by_profile"]), {"large", "small"})
        geometry = result["runs"]["geometry"]["overall"]
        self.assertEqual(geometry["success"]["count"], 4)
        self.assertEqual(geometry["grasp_planning"]["attempts"], 4)
        self.assertEqual(geometry["grasp_planning"]["compute_ms_per_attempt"], 4.0)

    def test_campaign_report_rejects_unmatched_samples(self) -> None:
        baseline = _run((True,), (10.0,))
        candidate = _run((True,), (10.0,))
        candidate["episodes"][0]["sample"]["profile_id"] = "different"
        with self.assertRaisesRegex(ValueError, "different randomized sample"):
            build_campaign_evaluation(
                {"historical": baseline, "geometry": candidate},
                "historical",
            )


if __name__ == "__main__":
    unittest.main()
