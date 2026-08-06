from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_final_acceptance_matrix_v2 import B2B_GOLD, B2C_GOLD, compile_final_acceptance_matrix, verify_final_acceptance_matrix


H = "a" * 64


class GTMFinalAcceptanceMatrixV2Tests(unittest.TestCase):
    def test_current_zero_evidence_fails_all_release_gates(self) -> None:
        coverage = {"complete_subvertical_ids": [], "content_sha256": H}
        named = {"row_count": 130, "completed_product_pk_rows": 0, "candidate_win_count": 0, "submitted_human_review_count": 0, "content_sha256": H}
        lifecycle = {"scenario_count": 1976, "production_outcomes_observed": 0, "content_sha256": H}
        todo = {"completion_claim_allowed": False, "content_sha256": H}
        payload = compile_final_acceptance_matrix(coverage, named, lifecycle, todo, production_gold_stress_pass_count=0, traceable_claim_count=0, total_claim_count=0)
        verify_final_acceptance_matrix(payload)
        self.assertEqual(payload["passed_gate_count"], 0)
        self.assertFalse(payload["final_release_allowed"])
        self.assertEqual(payload["gates"]["T096_gold_lifecycle_budget_stress"]["synthetic_lifecycle_scenarios_not_credited"], 1976)

    def test_complete_hypothetical_inputs_demonstrate_exact_release_logic(self) -> None:
        extras_b2b = [f"b2b.synthetic.{i}" for i in range(36)]
        extras_b2c = [f"b2c.synthetic.{i}" for i in range(35)]
        ids = list(B2B_GOLD) + list(B2C_GOLD) + extras_b2b + extras_b2c
        payload = compile_final_acceptance_matrix(
            {"complete_subvertical_ids": ids, "content_sha256": H},
            {"row_count": 130, "completed_product_pk_rows": 130, "candidate_win_count": 130, "submitted_human_review_count": 650, "content_sha256": H},
            {"production_outcomes_observed": 1, "scenario_count": 200, "content_sha256": H},
            {"completion_claim_allowed": True, "content_sha256": H},
            production_gold_stress_pass_count=200, traceable_claim_count=100, total_claim_count=100,
        )
        verify_final_acceptance_matrix(payload)
        self.assertTrue(payload["final_release_allowed"])
        self.assertEqual(payload["passed_gate_count"], 10)

    def test_tampering_fails(self) -> None:
        payload = compile_final_acceptance_matrix({"complete_subvertical_ids": [], "content_sha256": H}, {"content_sha256": H}, {"content_sha256": H}, {"content_sha256": H}, production_gold_stress_pass_count=0, traceable_claim_count=0, total_claim_count=0)
        broken = copy.deepcopy(payload); broken["final_release_allowed"] = True
        with self.assertRaises(Exception): verify_final_acceptance_matrix(broken)


if __name__ == "__main__": unittest.main()
