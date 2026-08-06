from __future__ import annotations

import unittest

from prooflaunch_remix.v10_submission_flows import FLOW_PROFILES, build_flow_preflight


class SubmissionFlowPreflightTests(unittest.TestCase):
    def test_four_profiles_preserve_exact_source_order_and_distinct_requirements(self) -> None:
        self.assertEqual(tuple(item.todo_id for item in FLOW_PROFILES), ("1181", "1182", "1183", "1184"))
        self.assertEqual(FLOW_PROFILES[0].vertical, "physical_product")
        self.assertEqual(FLOW_PROFILES[1].vertical, "ai_agent_product")
        self.assertEqual(FLOW_PROFILES[2].mode, "rapid")
        self.assertEqual(FLOW_PROFILES[3].mode, "quality")
        self.assertEqual(len({item.digest for item in FLOW_PROFILES}), 4)

    def test_each_mechanical_flow_runs_create_approve_bundle_without_external_release(self) -> None:
        report = build_flow_preflight()
        self.assertEqual(report["mechanical_pass_count"], 4)
        self.assertEqual(report["canonical_complete_count"], 0)
        for receipt in report["receipts"]:
            self.assertEqual(receipt["pre_approval_status"], "awaiting_approval")
            self.assertEqual(receipt["post_approval_status"], "bundle_ready")
            self.assertFalse(receipt["external_release_executed"])
            self.assertEqual(len(receipt["bundle_sha256"]), 64)

    def test_real_model_radeon_media_latency_and_independent_quality_remain_hard_gates(self) -> None:
        report = build_flow_preflight()
        for receipt in report["receipts"]:
            self.assertFalse(receipt["canonical_todo_complete"])
            self.assertFalse(receipt["real_model_observed"])
            self.assertFalse(receipt["radeon_observed"])
            self.assertIn("real_model_outputs", receipt["missing_acceptance_evidence"])
            self.assertIn("radeon_execution_trace", receipt["missing_acceptance_evidence"])
            self.assertIn("independent_quality_evaluation", receipt["missing_acceptance_evidence"])


if __name__ == "__main__":
    unittest.main()
