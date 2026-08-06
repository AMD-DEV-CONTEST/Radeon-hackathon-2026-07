from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.compile_gtm_last_mile_quality_benchmark import build_benchmark, render_markdown


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-last-mile-production-quality-v1.json"
REPORT = ROOT / "docs/product/GTM_LAST_MILE_PRODUCTION_QUALITY_V1.md"


class GTMLastMileQualityBenchmarkTests(unittest.TestCase):
    def test_sealed_outputs_match_compiler(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed, build_benchmark())
        self.assertEqual(REPORT.read_text(encoding="utf-8"), render_markdown(sealed))

    def test_all_requested_last_mile_lanes_are_artifact_bound(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        expected = {
            "integrated_gtm_strategy", "organic_social_copy", "landing_page",
            "lifecycle_email", "visual_system", "video", "audio", "content_schedule",
            "seo", "geo", "advertising", "analytics", "employee_agent",
            "cross_device_memory",
        }
        self.assertEqual(sealed["lane_count"], 14)
        self.assertEqual({row["lane_id"] for row in sealed["lanes"]}, expected)
        for row in sealed["lanes"]:
            self.assertTrue(row["mechanical_ready"], row["lane_id"])
            self.assertTrue(row["artifacts"], row["lane_id"])
            self.assertTrue(all(item["verified"] for item in row["artifacts"]))
            self.assertEqual(len(row["quality_axes"]), 7)
            if row["deterministic_copy_defect_scan_applicable"]:
                self.assertTrue(row["deterministic_copy_defect_scan_passed"])
                self.assertEqual(row["deterministic_copy_defect_hits"], [])

    def test_quality_and_business_axes_fail_closed_independently(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(
            sealed["effect_definition"]["primary"],
            "last_mile_generated_execution_quality",
        )
        self.assertTrue(sealed["portfolio"]["mechanical_pack_assembled"])
        self.assertFalse(
            sealed["portfolio"]["last_mile_execution_quality_alignment_achieved"]
        )
        self.assertFalse(sealed["portfolio"]["business_outcome_observed"])
        self.assertFalse(sealed["portfolio"]["four_a_quality_proven"])
        self.assertEqual(sealed["portfolio"]["human_reviewed_lane_count"], 0)
        self.assertEqual(
            sealed["portfolio"]["copy_defect_scan_applicable_lane_count"], 11
        )
        self.assertEqual(
            sealed["portfolio"]["copy_defect_scan_passed_lane_count"], 11
        )
        self.assertIsNone(sealed["lanes"][0]["human_quality_scores"])
        ladder = sealed["quality_ladder"]
        self.assertEqual(ladder["current_state"], "mechanically_ready")
        self.assertTrue(ladder["gates"]["G0_contract"]["passed"])
        self.assertFalse(ladder["gates"]["G1_professional_editor"]["passed"])
        self.assertFalse(ladder["gates"]["G2_same_brief_blind_pk"]["passed"])
        self.assertFalse(ladder["gates"]["G3_production_effect"]["passed"])
        self.assertFalse(ladder["promotion_allowed"])

    def test_protocol_forbids_model_only_promotion(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        protocol = sealed["pk_protocol"]
        self.assertIn("At least five qualified reviewers", protocol["reviewers"])
        self.assertIn("Wilson lower bound", protocol["promotion_threshold"])
        self.assertIn("cannot select or release", protocol["judge_boundary"])
        self.assertIn("does not assign aesthetic scores", sealed["truth_boundary"])

    def test_current_run_internal_challenger_is_ready_but_not_a_top_product_baseline(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(
            sealed["portfolio"]["same_brief_internal_challenger_compiled_lane_count"],
            14,
        )
        review = sealed["current_review_evidence"]
        self.assertEqual(review["current_run_internal_expected"], 55)
        self.assertEqual(review["current_run_internal_submitted"], 0)
        self.assertEqual(
            review["current_run_internal_review_admission_status"],
            "ready_for_named_human_review",
        )
        self.assertFalse(review["current_run_internal_top_product_baseline"])
        self.assertEqual(review["unified_lane_count"], 14)
        self.assertEqual(review["unified_pair_count"], 16)
        self.assertEqual(review["unified_expected"], 80)
        self.assertEqual(review["unified_submitted"], 0)
        self.assertFalse(review["unified_top_product_baselines_present"])
        self.assertTrue(
            all(row["top_product_baseline_present"] is False for row in sealed["lanes"])
        )

    def test_digest_covers_scorecard(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        supplied = sealed.pop("content_sha256")
        encoded = json.dumps(sealed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(supplied, hashlib.sha256(encoded.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
