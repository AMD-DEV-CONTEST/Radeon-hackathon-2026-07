from __future__ import annotations

import copy
import unittest

from scripts.compile_gtm_multimodal_production_contract_v2 import fixture
from prooflaunch_remix.gtm_multimodal_production_contract_v2 import evaluate_multimodal_production, verify_multimodal_production_evaluation


class GTMMultimodalProductionContractV2Tests(unittest.TestCase):
    def test_complete_bundle_passes_contract_but_has_no_release_authority(self) -> None:
        result = evaluate_multimodal_production(fixture()); verify_multimodal_production_evaluation(result)
        self.assertEqual(result["status"], "multimodal_contract_ready_for_release_authorization")
        self.assertEqual(result["asset_count"], 1)
        self.assertFalse(result["external_release_authorized"])

    def test_missing_proof_video_plan_and_silent_downgrade_fail(self) -> None:
        raw = fixture(); raw["proof_objects"] = []; raw["assets"][0]["video_spec"] = {}; raw["downgrade_disclosure"] = None
        defects = evaluate_multimodal_production(raw)["defects"]
        self.assertIn("missing_bundle_proof_objects", defects)
        self.assertIn("incomplete_video_plan:video-1", defects)
        self.assertIn("silent_quality_downgrade", defects)

    def test_homogeneity_crop_and_provenance_failures_are_visible(self) -> None:
        raw = fixture(); raw["assets"][0]["homogeneity_comparison"]["axes"]["color"]["distinct_enough"] = False
        raw["assets"][0]["adaptation"]["source_asset_crop_only"] = True
        raw["assets"][0]["provenance"].pop("final_sha256")
        defects = evaluate_multimodal_production(raw)["defects"]
        self.assertIn("homogeneity_failure:video-1", defects)
        self.assertIn("platform_copy_or_crop_adaptation:video-1", defects)
        self.assertIn("incomplete_asset_provenance:video-1", defects)

    def test_tampering_fails(self) -> None:
        result = evaluate_multimodal_production(fixture()); broken = copy.deepcopy(result); broken["external_release_authorized"] = True
        with self.assertRaises(Exception): verify_multimodal_production_evaluation(broken)


if __name__ == "__main__": unittest.main()
