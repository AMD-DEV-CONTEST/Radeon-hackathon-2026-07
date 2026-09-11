import unittest

from parcel_sorter.repeatability import analyze_repeatability_campaign


CONDITIONS = ("baseline", "candidate")


def _summary(
    episode_id: int,
    *,
    success: bool,
    force: float,
    active: bool,
) -> dict:
    return {
        "config": {"task": {"max_contact_force_n": 35.0}},
        "episodes": [
            {
                "episode_index": episode_id,
                "sample": {"episode_index": episode_id, "profile_id": "box"},
                "result": {
                    "success": success,
                    "dropped": False,
                    "max_contact_force_n": force,
                },
                "terminal_stage": "complete" if success else "abort",
                "safety_summary": {
                    "geometry_aware_grasp_planning_active": active,
                    "grasp_plan_attempts": 1 if active else 0,
                },
            }
        ],
    }


class RepeatabilityAnalysisTests(unittest.TestCase):
    def test_reports_nested_instability_without_inferential_sample_claim(self) -> None:
        schedule = {
            "schedule_seed": 7,
            "repeats_per_episode_condition": 2,
            "conditions": list(CONDITIONS),
            "blocks": [
                {
                    "run_index": 1,
                    "repeat_index": 1,
                    "episode_id": 10,
                    "condition_order": ["baseline", "candidate"],
                },
                {
                    "run_index": 2,
                    "repeat_index": 2,
                    "episode_id": 10,
                    "condition_order": ["candidate", "baseline"],
                },
            ],
        }
        summaries = {
            (1, "baseline"): _summary(10, success=True, force=10.0, active=False),
            (1, "candidate"): _summary(10, success=False, force=50.0, active=True),
            (2, "baseline"): _summary(10, success=False, force=45.0, active=False),
            (2, "candidate"): _summary(10, success=False, force=48.0, active=True),
        }

        result = analyze_repeatability_campaign(schedule, summaries)

        self.assertEqual(result["experimental_unit_count"], 1)
        self.assertEqual(result["total_execution_observations"], 4)
        self.assertEqual(result["condition_first_counts"], {"baseline": 1, "candidate": 1})
        self.assertEqual(
            result["instability"]["baseline"]["success_unstable_episode_ids"],
            [10],
        )
        positions = result["episodes"]["10"]["conditions"]["baseline"][
            "by_condition_position"
        ]
        self.assertEqual(
            positions["1"],
            {"trials": 1, "success_count": 1, "force_abort_count": 0},
        )
        self.assertEqual(
            positions["2"],
            {"trials": 1, "success_count": 0, "force_abort_count": 1},
        )
        self.assertIn("not_independent", result["inference_boundary"])

    def test_rejects_a_changed_sample_within_an_episode(self) -> None:
        schedule = {
            "schedule_seed": 7,
            "repeats_per_episode_condition": 1,
            "conditions": list(CONDITIONS),
            "blocks": [
                {
                    "run_index": 1,
                    "repeat_index": 1,
                    "episode_id": 10,
                    "condition_order": list(CONDITIONS),
                }
            ],
        }
        summaries = {
            (1, "baseline"): _summary(10, success=True, force=10.0, active=False),
            (1, "candidate"): _summary(10, success=True, force=10.0, active=False),
        }
        summaries[(1, "candidate")]["episodes"][0]["sample"]["mass_kg"] = 1.0

        with self.assertRaisesRegex(ValueError, "sample changed"):
            analyze_repeatability_campaign(schedule, summaries)


if __name__ == "__main__":
    unittest.main()
