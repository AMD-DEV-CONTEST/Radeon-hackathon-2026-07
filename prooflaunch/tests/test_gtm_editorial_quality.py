from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_editorial_quality import (
    EditorialQualityError,
    compile_editorial_quality_receipt,
    verify_editorial_quality_receipt,
)
from prooflaunch_remix.gtm_strategy import BusinessModel, StrategyCompiler
from tests.test_gtm_production_pack import compile_pack, make_request


class EditorialQualityTests(unittest.TestCase):
    def test_real_pack_runs_hook_slop_b2b_humor_longform_and_spoken_screens(self) -> None:
        _, _, pack = compile_pack()
        receipt = pack.editorial_quality_receipt

        self.assertEqual(receipt["business_model_editor"], "b2b")
        self.assertEqual(len(receipt["hook_classification"]), 2)
        self.assertEqual(receipt["anti_ai_slop_findings"], [])
        self.assertEqual(receipt["humor_boundary"]["status"], "not_used")
        self.assertIn(receipt["long_form_editor"]["status"], {"not_applicable_short_draft", "mechanically_screened_human_review_required"})
        self.assertIsNone(receipt["human_editor_pass"])
        self.assertFalse(receipt["direct_publishability_observed"])
        verify_editorial_quality_receipt(receipt)

    def test_slop_and_spoken_readout_defects_are_named_not_hidden(self) -> None:
        request = make_request(business_model=BusinessModel.B2C)
        strategy = StrategyCompiler().compile(request, at="2026-08-02T12:00:00Z")
        primary = {
            "hook": "In today's fast-paced digital world, unlock the power of change.",
            "body": [strategy.proof, request.audience.core_problem, request.audience.desired_outcome],
            "call_to_action": strategy.call_to_action,
            "native_format": "short_video",
        }
        secondary = {
            "hook": "Challenge the evidence?",
            "body": [strategy.proof, request.audience.buying_context],
            "call_to_action": strategy.call_to_action,
            "native_format": "community_post",
        }
        receipt = compile_editorial_quality_receipt(
            request,
            strategy,
            primary_copy=primary,
            secondary_copy=secondary,
            video_hook=" ".join(["This"] * 30) + ".",
            long_form_blocks=(strategy.proof,),
        )

        self.assertIn("generic_era_opening", {row["pattern_id"] for row in receipt["anti_ai_slop_findings"]})
        self.assertIn("empty_unlock", {row["pattern_id"] for row in receipt["anti_ai_slop_findings"]})
        self.assertIn("anti_ai_slop", receipt["mechanical_failed_check_ids"])
        self.assertEqual(receipt["spoken_native_editor"]["status"], "revision_required")
        self.assertFalse(receipt["mechanical_screen_passed"])

    def test_tampering_or_synthetic_human_pass_fails_closed(self) -> None:
        _, _, pack = compile_pack()
        tampered = copy.deepcopy(pack.editorial_quality_receipt)
        tampered["human_editor_pass"] = True
        with self.assertRaises(EditorialQualityError):
            verify_editorial_quality_receipt(tampered)


if __name__ == "__main__":
    unittest.main()
