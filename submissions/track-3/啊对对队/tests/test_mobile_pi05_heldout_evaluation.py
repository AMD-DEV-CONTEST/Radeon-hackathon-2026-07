import unittest

from parcel_sorter.mobile_pi05_heldout_evaluation import (
    summarize_pi05_heldout_routing,
)


def _panel() -> dict:
    modes = ("top_suction", "side_suction", "cooperative_cradle")
    return {
        "episodes": [
            {"episode_id": f"{mode}-{index}", "grasp_mode": mode}
            for mode in modes
            for index in range(4)
        ]
    }


def _evaluations(panel: dict) -> list[dict]:
    return [
        {
            "episode_id": item["episode_id"],
            "predicted_grasp_mode": item["grasp_mode"],
            "mode_input_hidden": True,
            "sample_count": 3,
            "sample_seeds": [11, 12, 13],
            "finite": True,
            "material_residual": True,
            "fallback_to_expert": False,
            "policy_type": "pi05",
            "capture_integrity_passed": True,
        }
        for item in panel["episodes"]
    ]


class MobilePI05HeldoutEvaluationTests(unittest.TestCase):
    def test_perfect_panel_passes_without_authorizing_selection(self) -> None:
        panel = _panel()

        result = summarize_pi05_heldout_routing(_evaluations(panel), panel)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["correct_episodes"], 12)
        self.assertFalse(result["checkpoint_selection_allowed"])
        self.assertTrue(all(item["correct"] == 4 for item in result["per_mode"].values()))

    def test_one_wrong_mode_fails(self) -> None:
        panel = _panel()
        evaluations = _evaluations(panel)
        evaluations[0]["predicted_grasp_mode"] = "side_suction"

        result = summarize_pi05_heldout_routing(evaluations, panel)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["correct_episodes"], 11)
        self.assertIn("top_suction-0:mode_correct", result["errors"])

    def test_seed_panel_mismatch_fails(self) -> None:
        panel = _panel()
        evaluations = _evaluations(panel)
        evaluations[-1]["sample_seeds"] = [21, 22, 23]

        result = summarize_pi05_heldout_routing(evaluations, panel)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("sampling_seed_panel_mismatch" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
