from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_multimodal_director import (
    MultimodalDirectorError,
    select_image_best_of_n,
    verify_multimodal_direction_receipt,
)
from tests.test_gtm_production_pack import SHA, compile_pack


class MultimodalDirectorTests(unittest.TestCase):
    def test_real_pack_has_visual_grammar_identity_video_audio_and_consistency_contracts(self) -> None:
        _, _, pack = compile_pack()
        receipt = pack.multimodal_direction_receipt

        self.assertEqual(len(receipt["visual_grammars"]), 3)
        self.assertEqual(
            receipt["identity_lock"]["locked_elements"],
            ["product_structure", "logo", "packaging", "interface", "critical_text"],
        )
        self.assertTrue(receipt["first_frame_three_second_gate"]["brief_gate_passed"])
        self.assertEqual(
            set(receipt["shot_function_coverage"]),
            {"tension", "proof", "turn", "product_demonstration", "action"},
        )
        self.assertTrue(receipt["cross_modal_consistency"]["claim_id_shared"])
        self.assertTrue(receipt["cross_modal_consistency"]["cta_shared"])
        self.assertEqual(receipt["rendered_asset_count"], 0)
        self.assertFalse(receipt["rendered_asset_quality_observed"])
        verify_multimodal_direction_receipt(receipt)

    def test_image_best_of_n_hard_gates_before_creative_score(self) -> None:
        receipt = select_image_best_of_n(
            (
                {
                    "candidate_id": "beautiful-but-wrong",
                    "identity_lock_passed": False,
                    "claim_text_ocr_passed": True,
                    "rights_receipt_present": True,
                    "claim_id": "claim-001",
                    "evidence_sha256": SHA,
                    "creative_score": 0.99,
                },
                {
                    "candidate_id": "eligible-b",
                    "identity_lock_passed": True,
                    "claim_text_ocr_passed": True,
                    "rights_receipt_present": True,
                    "claim_id": "claim-001",
                    "evidence_sha256": SHA,
                    "creative_score": 0.82,
                },
                {
                    "candidate_id": "eligible-a",
                    "identity_lock_passed": True,
                    "claim_text_ocr_passed": True,
                    "rights_receipt_present": True,
                    "claim_id": "claim-001",
                    "evidence_sha256": SHA,
                    "creative_score": 0.82,
                },
            ),
            claim_id="claim-001",
            evidence_sha256=SHA,
        )

        self.assertEqual(receipt["hard_gate_eligible_count"], 2)
        self.assertEqual(receipt["mechanically_selected_candidate_id"], "eligible-a")
        self.assertFalse(receipt["rendered_asset_publishable"])
        self.assertIsNone(receipt["human_creative_selection"])

    def test_tampered_render_claim_fails_closed(self) -> None:
        _, _, pack = compile_pack()
        tampered = copy.deepcopy(pack.multimodal_direction_receipt)
        tampered["rendered_asset_count"] = 1
        with self.assertRaises(MultimodalDirectorError):
            verify_multimodal_direction_receipt(tampered)


if __name__ == "__main__":
    unittest.main()
