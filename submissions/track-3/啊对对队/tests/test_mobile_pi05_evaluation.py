import unittest

from parcel_sorter.mobile_pi05_evaluation import (
    compare_paired_pi05_runs,
    exact_binomial_greater_p,
    exact_mcnemar_p,
    required_exact_binomial_successes,
)


def _run(index: int, success: bool, *, qualified: bool = True) -> dict:
    return {
        "episode_id": f"episode-{index:03d}",
        "success": success,
        "suction": {"max_contact_force_n": 10.0},
        "vla_qualified": qualified,
        "material_pi05_residual": True,
        "policy_authority": "hybrid_expert_reference_plus_vla_residual",
        "expert_reference_used": True,
        "policy": {"expert_fallback_count": 0, "emergency_stop_count": 0},
    }


class MobilePI05EvaluationTests(unittest.TestCase):
    def test_exact_mcnemar_is_one_without_discordant_pairs(self) -> None:
        self.assertEqual(exact_mcnemar_p(0, 0), 1.0)

    def test_105_trial_gate_requires_ninety_five_successes(self) -> None:
        baseline = [_run(index, index < 90) for index in range(105)]
        candidate = [_run(index, index < 95) for index in range(105)]
        result = compare_paired_pi05_runs(baseline, candidate)
        self.assertEqual(result["required_successes"], 95)
        self.assertEqual(result["candidate_successes"], 95)
        self.assertTrue(result["promotion_gate_passed"])
        self.assertFalse(result["paper_claim"]["gate_passed"])

    def test_105_trial_paper_claim_requires_one_hundred_successes(self) -> None:
        self.assertEqual(required_exact_binomial_successes(105), 100)
        self.assertGreaterEqual(exact_binomial_greater_p(99, 105), 0.05)
        self.assertLess(exact_binomial_greater_p(100, 105), 0.05)
        baseline = [_run(index, index < 90) for index in range(105)]
        candidate = [_run(index, index < 100) for index in range(105)]
        result = compare_paired_pi05_runs(baseline, candidate)
        self.assertTrue(result["paper_claim"]["gate_passed"])
        self.assertFalse(result["pure_vla_paper_claim"]["gate_passed"])
        self.assertEqual(
            result["paper_claim"]["claim_scope"],
            "hybrid_expert_reference_plus_vla_residual",
        )

    def test_pure_vla_claim_requires_absolute_authority_without_reference(self) -> None:
        baseline = [_run(index, index < 90) for index in range(105)]
        candidate = [_run(index, index < 100) for index in range(105)]
        for run in candidate:
            run["policy_authority"] = "absolute_vla_action_candidate"
            run["expert_reference_used"] = False
            run["system_control_class"] = "pure_vla"
            run["policy"]["absolute_full_authority"] = True
            run["policy"]["task_action_correction_count"] = 0

        result = compare_paired_pi05_runs(baseline, candidate)

        self.assertTrue(result["paper_claim"]["gate_passed"])
        self.assertTrue(result["pure_vla_paper_claim"]["gate_passed"])
        self.assertEqual(result["candidate_pure_absolute_vla_runs"], 105)

    def test_external_stage_routing_blocks_pure_vla_claim(self) -> None:
        baseline = [_run(index, index < 90) for index in range(105)]
        candidate = [_run(index, index < 100) for index in range(105)]
        for run in candidate:
            run["policy_authority"] = "absolute_vla_action_candidate"
            run["expert_reference_used"] = False
            run["system_control_class"] = "shielded_vla"
            run["policy"]["absolute_full_authority"] = False

        result = compare_paired_pi05_runs(baseline, candidate)

        self.assertFalse(result["pure_vla_paper_claim"]["gate_passed"])
        self.assertEqual(result["candidate_pure_absolute_vla_runs"], 0)

    def test_fallback_blocks_promotion(self) -> None:
        baseline = [_run(index, True) for index in range(10)]
        candidate = [_run(index, True) for index in range(10)]
        candidate[0]["policy"]["expert_fallback_count"] = 1
        result = compare_paired_pi05_runs(baseline, candidate)
        self.assertFalse(result["promotion_gate_passed"])

    def test_emergency_stop_and_all_force_channels_block_promotion(self) -> None:
        baseline = [_run(index, True) for index in range(10)]
        candidate = [_run(index, True) for index in range(10)]
        candidate[0]["policy"]["emergency_stop_count"] = 1
        self.assertFalse(
            compare_paired_pi05_runs(baseline, candidate)["promotion_gate_passed"]
        )
        candidate[0]["policy"]["emergency_stop_count"] = 0
        candidate[0]["cradle"] = {"physical": {"max_contact_force_n": 35.0}}
        self.assertFalse(
            compare_paired_pi05_runs(baseline, candidate)["promotion_gate_passed"]
        )

    def test_campaign_requires_material_residual_evidence(self) -> None:
        baseline = [_run(index, True) for index in range(10)]
        candidate = [_run(index, True) for index in range(10)]
        candidate[0]["material_pi05_residual"] = False
        self.assertFalse(
            compare_paired_pi05_runs(baseline, candidate)["promotion_gate_passed"]
        )

    def test_unknown_policy_authority_blocks_promotion(self) -> None:
        baseline = [_run(index, True) for index in range(10)]
        candidate = [_run(index, True) for index in range(10)]
        candidate[0].pop("policy_authority")

        result = compare_paired_pi05_runs(baseline, candidate)

        self.assertFalse(result["promotion_gate_passed"])

    def test_requires_identical_episode_order(self) -> None:
        with self.assertRaises(ValueError):
            compare_paired_pi05_runs([_run(0, True)], [_run(1, True)])


if __name__ == "__main__":
    unittest.main()
