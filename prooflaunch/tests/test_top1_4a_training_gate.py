from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.top1_4a_training_gate import (
    Top1FourATrainingContract,
    UpstreamDataSource,
)


ROOT = Path(__file__).resolve().parents[1]


def source(index: int) -> UpstreamDataSource:
    return UpstreamDataSource(
        source_id=f"source-{index}",
        repository_url=f"https://github.com/example/source-{index}",
        revision=f"{index:040x}"[-40:],
        declared_data_license="reviewed-v1",
        permitted_use="method_only",
        asset_level_rights_verified=False,
        commercial_training_allowed=False,
        mechanism_to_reuse="pinned public curation mechanism",
        truth_boundary="No source asset enters training.",
    )


def passing_evidence() -> dict:
    return {
        "training_samples": 50_000,
        "task_family_count": 12,
        "industry_count": 10,
        "channel_count": 8,
        "owned_gtm_trajectory_rate": 0.40,
        "multimodal_rate": 0.65,
        "video_rate": 0.20,
        "four_k_video_rate": 0.85,
        "audio_rate": 0.12,
        "document_screen_rate": 0.20,
        "hard_negative_rate": 0.25,
        "counterfactual_rate": 0.20,
        "repair_trajectory_rate": 0.25,
        "synthetic_rate": 0.25,
        "external_teacher_rate": 0.15,
        "expert_review_rate": 0.20,
        "krippendorff_alpha": 0.85,
        "near_duplicate_rate": 0.002,
        "exact_duplicate_count": 0,
        "sealed_eval_contamination_count": 0,
        "unresolved_training_rights_count": 0,
        "unsupported_claim_count": 0,
        "provenance_coverage": 1.0,
        "license_locator_coverage": 1.0,
        "ablation_coverage": 1.0,
        "negative_control_coverage": 1.0,
        "reproducibility_receipt_coverage": 1.0,
        "rater_conflict_disclosure_coverage": 1.0,
        "reference_agency_count": 10,
        "campaign_case_count": 300,
        "minimum_cases_per_agency": 30,
        "minimum_channels_per_agency": 5,
        "senior_rater_count": 3,
        "total_rater_count": 5,
        "minimum_comparisons_per_agency": 150,
        "four_a_overall_mean": 4.8,
        "four_a_min_dimension": 4.6,
        "direct_publishable_rate": 0.97,
        "strong_baseline_count": 10,
        "world_size": 2,
        "two_gpu_speedup": 1.5,
        "parallel_efficiency": 0.70,
        "agency_preference_counts": {
            f"agency-{index}": {"preferred": 100, "comparisons": 150}
            for index in range(10)
        },
        "overall_preferred_count": 1000,
        "overall_comparison_count": 1500,
    }


class Top1FourATrainingGateTests(unittest.TestCase):
    def test_top1_gate_requires_raw_pairwise_agency_evidence(self) -> None:
        report = Top1FourATrainingContract().evaluate(
            passing_evidence(),
            tuple(source(index) for index in range(12)),
        )
        self.assertTrue(report.passed, report.failures)
        self.assertEqual(len(report.agency_wilson_lower_95), 10)
        self.assertGreater(report.overall_wilson_lower_95 or 0, 0.60)

    def test_model_self_score_cannot_replace_ten_agency_counts(self) -> None:
        evidence = passing_evidence()
        evidence.pop("agency_preference_counts")
        evidence["model_claimed_top1_score"] = 1.0
        report = Top1FourATrainingContract().evaluate(
            evidence,
            tuple(source(index) for index in range(12)),
        )
        self.assertFalse(report.passed)
        self.assertTrue(
            any("exactly ten agencies" in item for item in report.failures)
        )

    def test_unresolved_rights_and_eval_contamination_fail_closed(self) -> None:
        evidence = passing_evidence()
        evidence["unresolved_training_rights_count"] = 1
        evidence["sealed_eval_contamination_count"] = 1
        report = Top1FourATrainingContract().evaluate(
            evidence,
            tuple(source(index) for index in range(12)),
        )
        self.assertFalse(report.passed)

    def test_source_code_license_does_not_grant_training_rights(self) -> None:
        unsafe = UpstreamDataSource(
            source_id="unsafe",
            repository_url="https://github.com/example/unsafe",
            revision="a" * 40,
            declared_data_license="Apache-2.0 code only",
            permitted_use="training_candidate",
            asset_level_rights_verified=False,
            commercial_training_allowed=False,
            mechanism_to_reuse="data loader",
            truth_boundary="source assets unresolved",
        )
        self.assertTrue(unsafe.audit())

    def test_serialized_gate_is_content_addressed_and_training_blocked(self) -> None:
        payload = json.loads(
            (
                ROOT / "config" / "cortex_x_v10_top1_4a_training_gate.json"
            ).read_text(encoding="utf-8")
        )
        expected = payload.pop("contract_sha256")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected)
        self.assertEqual(len(payload["upstream_sources"]), 12)
        self.assertFalse(
            any(
                item["training_eligible_now"]
                for item in payload["upstream_sources"]
            )
        )
        self.assertEqual(payload["training_admission"]["default"], "blocked")


if __name__ == "__main__":
    unittest.main()

