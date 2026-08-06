from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_promotion_governance import (
    PromotionGovernanceError,
    compile_promotion_governance,
    verify_promotion_governance,
)


class PromotionGovernanceTests(unittest.TestCase):
    def build(self, *, g0: bool = True):
        return compile_promotion_governance(
            strategy_id="strategy-001",
            campaign_id="campaign-001",
            candidate_revision="candidate-001",
            stable_revision="stable-001",
            g0_contract_passed=g0,
        )

    def test_five_single_axis_judges_remain_uncalibrated_and_non_decisional(self) -> None:
        receipt = self.build()
        judges = receipt["single_axis_binary_judges"]

        self.assertEqual(receipt["judge_count"], 5)
        self.assertEqual(len({row["single_axis"] for row in judges}), 5)
        self.assertTrue(all(row["human_calibration_label_count"] == 0 for row in judges))
        self.assertTrue(all(not row["calibration_gate_passed"] for row in judges))
        self.assertTrue(all(not row["production_decision_allowed"] for row in judges))
        self.assertFalse(receipt["promotion_allowed"])
        self.assertFalse(receipt["promotion_executed"])
        verify_promotion_governance(receipt)

    def test_g0_regression_rejects_candidate_and_targets_stable_internal_revision(self) -> None:
        receipt = self.build(g0=False)
        policy = receipt["internal_rollback_policy"]

        self.assertTrue(receipt["regression_detected"])
        self.assertEqual(policy["current_decision"], "reject_candidate_keep_stable")
        self.assertEqual(policy["target"], "stable-001")
        self.assertTrue(policy["automatic_internal_alias_rollback_enabled"])
        self.assertFalse(policy["external_publish_send_or_spend_action_allowed"])

    def test_tampered_promotion_decision_fails_closed(self) -> None:
        receipt = self.build()
        tampered = copy.deepcopy(receipt)
        tampered["promotion_allowed"] = True
        with self.assertRaises(PromotionGovernanceError):
            verify_promotion_governance(tampered)


if __name__ == "__main__":
    unittest.main()
