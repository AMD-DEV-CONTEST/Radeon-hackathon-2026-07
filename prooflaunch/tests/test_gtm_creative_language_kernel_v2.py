from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_creative_language_kernel_v2 import build_creative_language_kernel, evaluate_creative_campaign, verify_creative_campaign_evaluation, verify_creative_language_kernel


H = "a" * 64


def pack(model: str = "b2b") -> dict:
    roles = ("engineering", "operations", "finance", "procurement", "executive", "channel_partner") if model == "b2b" else ("identity", "usage_context", "maturity", "price_sensitivity", "lifecycle")
    return {
        "campaign_id": f"campaign-{model}", "business_model": model,
        "proof_objects": [{"proof_type": "product_behavior", "content_sha256": H}],
        "creative_territory": "documented_reality", "narrative_structure": "suspense_proof",
        "brand_memory": {"language_code": "precise operator language", "visual_code": "annotated evidence frame", "sound_code": "quiet tactile signal", "character_code": "skeptical operator", "interaction_code": "claim evidence verdict"},
        "growth_pattern": "public_proof", "deception_controls": {key: False for key in ("fake_comments", "fake_scarcity", "fake_identity", "impersonation", "harassment", "dark_posting", "manipulation", "unsupported_competitor_attack")},
        "audience_adaptations": {role: f"Specific evidence and decision language for the {role} context." for role in roles},
        "platform_assets": [{"platform": "linkedin", "text": "One operator rejected the polished claim because its evidence could not survive a buying review. Here is the exact proof boundary.", "competitor_substitution_test_passed": True, "standard_elements_present": ["point_of_view", "proof", "role_relevance"]}],
    }


class GTMCreativeLanguageKernelV2Tests(unittest.TestCase):
    def test_kernel_has_required_territories_structures_platforms_and_integrity_libraries(self) -> None:
        kernel = build_creative_language_kernel(); verify_creative_language_kernel(kernel)
        self.assertEqual(len(kernel["creative_territories"]), 7)
        self.assertEqual(len(kernel["narrative_structures"]), 6)
        self.assertEqual(len(kernel["platform_writing_standards"]), 8)
        self.assertEqual(len(kernel["legitimate_unconventional_growth_patterns"]), 6)
        self.assertEqual(len(kernel["deception_prohibitions"]), 8)

    def test_clean_b2b_and_b2c_packs_reach_human_review_not_auto_publish(self) -> None:
        for model in ("b2b", "b2c"):
            result = evaluate_creative_campaign(pack(model)); verify_creative_campaign_evaluation(result)
            self.assertEqual(result["status"], "creative_integrity_ready_for_human_review")
            self.assertFalse(result["automatic_publish_or_spend_allowed"])

    def test_generic_language_missing_role_and_deception_are_detected(self) -> None:
        raw = pack(); raw["platform_assets"][0]["text"] = "Act now. Unlock potential with our revolutionary world-class solution. Learn more today."
        raw["audience_adaptations"].pop("finance")
        raw["deception_controls"]["fake_scarcity"] = True
        result = evaluate_creative_campaign(raw)
        self.assertEqual(result["status"], "creative_integrity_gap")
        self.assertTrue(any("empty_superlatives" in value for value in result["defects"]))
        self.assertIn("incomplete_audience_adaptation", result["defects"])
        self.assertIn("deception_or_missing_deception_control", result["defects"])

    def test_tampering_fails(self) -> None:
        result = evaluate_creative_campaign(pack()); broken = copy.deepcopy(result); broken["observed_effect_claim_allowed"] = True
        with self.assertRaises(Exception): verify_creative_campaign_evaluation(broken)


if __name__ == "__main__": unittest.main()
