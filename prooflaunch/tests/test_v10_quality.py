from __future__ import annotations

import unittest

from prooflaunch_remix.quality_contract import QualityTier, contract_for


class CortexXV10QualityTests(unittest.TestCase):
    @staticmethod
    def passing_evidence() -> dict:
        return {
            "schema": "ProofLaunchCortexXV10CompiledEvidenceV1",
            "four_a_overall_mean": 4.8,
            "four_a_min_dimension": 4.6,
            "directly_publishable_rate": 0.97,
            "baseline_count": 5,
            "human_raters": 5,
            "publish_preferred_count": 130,
            "publish_comparison_count": 150,
            "gtm_gain_vs_base": 0.45,
            "gtm_gain_vs_v9": 0.20,
            "general_multimodal_regression": 0.005,
            "agent_success_rate": 0.99,
            "tool_error_rate": 0.0019,
            "structured_output_valid_rate": 0.998,
            "critical_unsupported_claim_count": 0,
            "claim_locator_coverage": 1.0,
            "rights_locator_coverage": 1.0,
            "approval_coverage": 1.0,
            "ocr_accuracy": 0.9995,
            "brand_delta_e": 1.0,
            "product_identity_rate": 0.995,
            "temporal_gain_vs_base": 0.30,
            "audio_video_alignment": 0.96,
            "simulated_business_claim_count": 0,
            "radeon_core_evidence_coverage": 1.0,
            "breakthrough_evidence_count": 12,
            "breakthrough_promoted_count": 3,
            "repair_budget_max": 2,
        }

    def test_exact_v10_measured_contract_passes(self) -> None:
        contract = contract_for(QualityTier.CORTEX_X_V10)
        self.assertEqual(len(contract.metrics), 28)
        report = contract.evaluate(self.passing_evidence())
        self.assertTrue(report.passed)
        self.assertGreater(
            report.derived_metrics["publish_preference_lower_95"],
            0.70,
        )

    def test_uncompiled_v10_aggregate_fails_closed(self) -> None:
        evidence = self.passing_evidence()
        evidence.pop("schema")
        report = contract_for(QualityTier.CORTEX_X_V10).evaluate(evidence)
        self.assertFalse(report.passed)
        self.assertTrue(all(item.actual is None for item in report.metrics))

    def test_tool_error_ceiling_is_strictly_less_than_point_two_percent(self) -> None:
        evidence = self.passing_evidence()
        evidence["tool_error_rate"] = 0.002
        report = contract_for(QualityTier.CORTEX_X_V10).evaluate(evidence)
        self.assertFalse(report.passed)
        tool = next(item for item in report.metrics if item.key == "tool_error_rate")
        self.assertFalse(tool.passed)

    def test_raw_counts_are_required_for_preference_confidence(self) -> None:
        evidence = self.passing_evidence()
        evidence.pop("publish_preferred_count")
        evidence.pop("publish_comparison_count")
        evidence["publish_preference_rate"] = 1.0
        evidence["publish_preference_lower_95"] = 1.0
        report = contract_for(QualityTier.CORTEX_X_V10).evaluate(evidence)
        self.assertFalse(report.passed)


if __name__ == "__main__":
    unittest.main()
