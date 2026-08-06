from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_organic_signal_sampling_standard import (
    OrganicSignalSamplingStandardError,
    build_global_organic_signal_sampling_standard,
    compile_global_organic_signal_coverage_receipt,
    verify_global_organic_signal_sampling_standard,
)


class GlobalOrganicSignalSamplingStandardTests(unittest.TestCase):
    def test_covers_b2b_b2c_markets_scales_lifecycle_and_platforms(self) -> None:
        result = build_global_organic_signal_sampling_standard()
        verify_global_organic_signal_sampling_standard(result)
        self.assertEqual(result["coverage_truth"]["segment_market_cell_count"], 140)
        self.assertEqual(result["coverage_truth"]["platform_market_lane_count"], 168)
        self.assertEqual(len(result["platform_contracts"]), 12)
        self.assertEqual(result["learning_memory_contract"]["automatic_write_count"], 0)
        self.assertTrue(result["sample_design"]["absolute_cross_account_ranking_forbidden"])
        self.assertTrue(any(row["market"] == "hong_kong" for row in result["segment_market_cells"]))
        self.assertTrue(any(row["market"] == "southern_africa_english" for row in result["segment_market_cells"]))

    def test_tampering_fails_closed(self) -> None:
        result = build_global_organic_signal_sampling_standard()
        result["learning_memory_contract"]["automatic_write_count"] = 1
        with self.assertRaisesRegex(OrganicSignalSamplingStandardError, "seal"):
            verify_global_organic_signal_sampling_standard(result)

    def test_empty_evidence_never_claims_global_coverage(self) -> None:
        standard = build_global_organic_signal_sampling_standard()
        receipt = compile_global_organic_signal_coverage_receipt(standard, [])
        self.assertEqual(receipt["qualified_segment_market_cell_count"], 0)
        self.assertEqual(receipt["observed_segment_market_cell_count"], 0)
        self.assertEqual(receipt["qualified_platform_market_lane_count"], 0)
        self.assertFalse(receipt["global_coverage_complete"])
        self.assertEqual(receipt["automatic_learning_memory_write_count"], 0)


if __name__ == "__main__":
    unittest.main()
