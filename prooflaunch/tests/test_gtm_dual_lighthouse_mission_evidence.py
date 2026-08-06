from __future__ import annotations

import unittest

from scripts.compile_gtm_dual_lighthouse_mission_evidence import (
    compile_evidence,
    verify_evidence,
)


class GTMDualLighthouseMissionEvidenceTests(unittest.TestCase):
    def test_current_b2b_b2c_missions_are_hash_bound_but_quality_unproven(self) -> None:
        payload = compile_evidence()
        verify_evidence(payload)
        self.assertEqual(payload["scenarios"], ["b2b", "b2c"])
        self.assertEqual(payload["verified_event_chain_count"], 2)
        self.assertEqual(payload["candidate_count"], 6)
        self.assertEqual(payload["blind_pair_count"], 12)
        self.assertEqual(payload["human_review_task_count"], 60)
        self.assertEqual(payload["submitted_human_review_count"], 0)
        self.assertEqual(payload["craft_quality_advisory_pass_count"], 0)
        self.assertEqual(payload["critic_contract_failure_treated_as_quality_pass_count"], 0)
        self.assertFalse(payload["last_mile_execution_quality_proven"])
        self.assertEqual(payload["external_publish_executed_count"], 0)
        self.assertEqual(payload["named_product_pk_completed_count"], 0)
        self.assertEqual(payload["production_effect_observed_count"], 0)
        self.assertEqual({row["scenario"] for row in payload["missions"]}, {"b2b", "b2c"})


if __name__ == "__main__":
    unittest.main()
