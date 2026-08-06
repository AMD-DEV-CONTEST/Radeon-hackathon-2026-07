from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "evidence/v10/local-multimodal-qualification.json"


class LocalMultimodalQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_receipt_and_every_artifact_are_content_addressed(self) -> None:
        payload = dict(self.payload)
        digest = payload.pop("content_sha256")
        observed = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, observed)
        for artifact in self.payload["artifacts"].values():
            path = ROOT / artifact["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
            self.assertEqual(path.stat().st_size, artifact["size_bytes"])

    def test_local_execution_is_real_but_never_promoted_to_product_quality(self) -> None:
        execution = self.payload["execution"]
        self.assertTrue(execution["local_model_inference_observed"])
        self.assertFalse(execution["local_model_training_observed"])
        self.assertFalse(execution["radeon_local_inference_observed"])
        self.assertEqual(execution["cloud_api_calls"], 0)
        self.assertEqual(execution["network_downloads"], 0)
        gates = self.payload["quality_gates"]
        self.assertTrue(gates["speech_48khz_stereo_24bit_delivery"])
        self.assertTrue(gates["video_subject_recognizable_after_bounded_repair"])
        self.assertFalse(gates["speech_named_human_listening_review"])
        self.assertFalse(gates["video_delivery_gate_passed"])
        self.assertFalse(gates["four_a_effect_claim_eligible"])
        self.assertFalse(gates["product_admission_passed"])

    def test_rights_and_blind_selection_fail_closed(self) -> None:
        self.assertTrue(
            self.payload["models"]["speech"][
                "production_rights_cleared_for_this_synthetic_probe"
            ]
        )
        self.assertFalse(self.payload["models"]["video"]["production_rights_cleared"])
        self.assertFalse(
            self.payload["campaign_binding"]["blind_selected_territory_used"]
        )
        self.assertFalse(self.payload["models"]["video"]["operator_entity_revenue_verified"])

    def test_video_technical_shortfall_is_explicit(self) -> None:
        one_stage = self.payload["artifacts"]["video_one_stage"]
        gates = self.payload["quality_gates"]
        self.assertLess(one_stage["width"], gates["video_minimum_width"])
        self.assertLess(
            one_stage["duration_seconds"], gates["video_minimum_duration_seconds"]
        )
        self.assertEqual(
            self.payload["attempts"][-1]["visual_review"],
            "single_evidence_card_recognizable",
        )


if __name__ == "__main__":
    unittest.main()
