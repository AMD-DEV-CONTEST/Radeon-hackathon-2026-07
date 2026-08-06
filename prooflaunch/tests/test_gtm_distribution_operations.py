from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_content_calendar import compile_content_calendar
from prooflaunch_remix.gtm_distribution_operations import (
    DistributionOperationsError,
    compile_distribution_operations,
    verify_distribution_operations,
)
from tests.test_gtm_production_pack import compile_pack


class DistributionOperationsTests(unittest.TestCase):
    def build(self):
        request, strategy, pack = compile_pack()
        calendar = compile_content_calendar(
            request,
            strategy,
            pack.channel_portfolio,
            source_draft_ids={
                pack.primary_copy.channel: pack.primary_copy.draft_id,
                pack.secondary_copy.channel: pack.secondary_copy.draft_id,
            },
            compiled_at="2026-08-05T12:00:00Z",
            schedule_timezone="America/New_York",
        )
        return compile_distribution_operations(
            request,
            strategy,
            channel_portfolio=pack.channel_portfolio,
            content_calendar=calendar,
        )

    def test_focus_timing_seven_day_and_manual_operations_are_complete(self) -> None:
        receipt = self.build()

        self.assertEqual(receipt["launch_focus"]["scheduled_platform_count"], 2)
        self.assertTrue(receipt["launch_focus"]["cold_start_focus_gate_passed"])
        self.assertEqual(len(receipt["timing_hypotheses"]), 7)
        self.assertTrue(all(row["factors"]["account_history"] == "not_supplied" for row in receipt["timing_hypotheses"]))
        self.assertEqual(len(receipt["seven_day_flight"]), 7)
        self.assertTrue(all(row["interaction_action"] and row["reuse_logic"] and row["stop_condition"] for row in receipt["seven_day_flight"]))
        self.assertFalse(receipt["comment_operator"]["automatic_reply_enabled"])
        self.assertFalse(receipt["community_entry_protocol"]["link_first_entry_allowed"])
        self.assertFalse(receipt["partner_growth_protocol"]["follower_count_primary_dimension"])
        verify_distribution_operations(receipt)

    def test_every_experiment_variant_changes_at_most_one_declared_axis(self) -> None:
        receipt = self.build()
        contract = receipt["single_variable_experiment_contract"]
        self.assertEqual(contract["maximum_changed_variables_per_variant"], 1)
        variants = [cell for cell in contract["cells"] if cell["cell_id"] != "control"]
        self.assertEqual(
            {cell["changed_variable"] for cell in variants},
            {"hook", "proof", "format", "cta", "publish_time"},
        )
        self.assertFalse(contract["causal_claim_allowed_before_qualified_result"])

    def test_tampering_fails_closed(self) -> None:
        receipt = self.build()
        tampered = copy.deepcopy(receipt)
        tampered["automatic_publish_enabled"] = True
        with self.assertRaises(DistributionOperationsError):
            verify_distribution_operations(tampered)


if __name__ == "__main__":
    unittest.main()
