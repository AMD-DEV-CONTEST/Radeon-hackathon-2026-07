from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .quality_contract import wilson_lower_bound


@dataclass(frozen=True)
class UpstreamDataSource:
    source_id: str
    repository_url: str
    revision: str
    declared_data_license: str
    permitted_use: str
    asset_level_rights_verified: bool
    commercial_training_allowed: bool
    mechanism_to_reuse: str
    truth_boundary: str

    def audit(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.repository_url.startswith("https://github.com/"):
            failures.append(f"{self.source_id}: repository URL is not authoritative")
        if len(self.revision) != 40 or any(
            char not in "0123456789abcdef" for char in self.revision
        ):
            failures.append(f"{self.source_id}: revision is not an immutable commit")
        if self.permitted_use not in {
            "training_candidate",
            "method_only",
            "evaluation_only",
        }:
            failures.append(f"{self.source_id}: invalid permitted_use")
        if self.permitted_use == "training_candidate" and (
            not self.asset_level_rights_verified
            or not self.commercial_training_allowed
        ):
            failures.append(
                f"{self.source_id}: training candidate lacks asset-level rights"
            )
        if not self.mechanism_to_reuse.strip() or not self.truth_boundary.strip():
            failures.append(f"{self.source_id}: reuse seam/truth boundary missing")
        if any(
            token in (
                self.repository_url
                + self.declared_data_license
                + self.mechanism_to_reuse
            ).lower()
            for token in ("<repo>", "<license>", "todo")
        ):
            failures.append(f"{self.source_id}: placeholder metadata")
        return tuple(failures)


@dataclass(frozen=True)
class Top1FourATrainingContract:
    minimum_upstream_sources: int = 12
    minimum_training_samples: int = 50_000
    minimum_task_families: int = 12
    minimum_industries: int = 10
    minimum_channels: int = 8
    minimum_owned_gtm_trajectory_rate: float = 0.35
    minimum_multimodal_rate: float = 0.60
    minimum_video_rate: float = 0.15
    minimum_four_k_video_rate: float = 0.80
    minimum_audio_rate: float = 0.10
    minimum_document_screen_rate: float = 0.15
    minimum_hard_negative_rate: float = 0.20
    minimum_counterfactual_rate: float = 0.15
    minimum_repair_trajectory_rate: float = 0.20
    maximum_synthetic_rate: float = 0.30
    maximum_external_teacher_rate: float = 0.20
    minimum_expert_review_rate: float = 0.15
    minimum_krippendorff_alpha: float = 0.80
    maximum_near_duplicate_rate: float = 0.005
    reference_agency_count: int = 10
    minimum_campaign_cases: int = 300
    minimum_cases_per_agency: int = 30
    minimum_channels_per_agency: int = 5
    minimum_senior_raters: int = 3
    minimum_total_raters: int = 5
    minimum_comparisons_per_agency: int = 150
    minimum_each_agency_wilson_lower_95: float = 0.50
    minimum_overall_wilson_lower_95: float = 0.60
    minimum_four_a_overall_mean: float = 4.80
    minimum_four_a_dimension: float = 4.60
    minimum_direct_publishable_rate: float = 0.97
    minimum_strong_baselines: int = 10
    minimum_world_size: int = 2
    minimum_two_gpu_speedup: float = 1.50
    minimum_parallel_efficiency: float = 0.70
    schema: str = "ProofLaunchTop1FourATrainingContractV1"

    def to_dict(self) -> dict:
        return asdict(self)

    def evaluate(
        self,
        evidence: Mapping[str, object],
        sources: Sequence[UpstreamDataSource],
    ) -> "Top1FourATrainingAudit":
        failures: list[str] = []
        for source in sources:
            failures.extend(source.audit())
        if len(sources) < self.minimum_upstream_sources:
            failures.append("fewer than twelve pinned upstream sources")

        minimums = {
            "training_samples": self.minimum_training_samples,
            "task_family_count": self.minimum_task_families,
            "industry_count": self.minimum_industries,
            "channel_count": self.minimum_channels,
            "owned_gtm_trajectory_rate": (
                self.minimum_owned_gtm_trajectory_rate
            ),
            "multimodal_rate": self.minimum_multimodal_rate,
            "video_rate": self.minimum_video_rate,
            "four_k_video_rate": self.minimum_four_k_video_rate,
            "audio_rate": self.minimum_audio_rate,
            "document_screen_rate": self.minimum_document_screen_rate,
            "hard_negative_rate": self.minimum_hard_negative_rate,
            "counterfactual_rate": self.minimum_counterfactual_rate,
            "repair_trajectory_rate": self.minimum_repair_trajectory_rate,
            "expert_review_rate": self.minimum_expert_review_rate,
            "krippendorff_alpha": self.minimum_krippendorff_alpha,
            "reference_agency_count": self.reference_agency_count,
            "campaign_case_count": self.minimum_campaign_cases,
            "minimum_cases_per_agency": self.minimum_cases_per_agency,
            "minimum_channels_per_agency": self.minimum_channels_per_agency,
            "senior_rater_count": self.minimum_senior_raters,
            "total_rater_count": self.minimum_total_raters,
            "minimum_comparisons_per_agency": (
                self.minimum_comparisons_per_agency
            ),
            "four_a_overall_mean": self.minimum_four_a_overall_mean,
            "four_a_min_dimension": self.minimum_four_a_dimension,
            "direct_publishable_rate": self.minimum_direct_publishable_rate,
            "strong_baseline_count": self.minimum_strong_baselines,
            "world_size": self.minimum_world_size,
            "two_gpu_speedup": self.minimum_two_gpu_speedup,
            "parallel_efficiency": self.minimum_parallel_efficiency,
        }
        maximums = {
            "synthetic_rate": self.maximum_synthetic_rate,
            "external_teacher_rate": self.maximum_external_teacher_rate,
            "near_duplicate_rate": self.maximum_near_duplicate_rate,
            "exact_duplicate_count": 0,
            "sealed_eval_contamination_count": 0,
            "unresolved_training_rights_count": 0,
            "unsupported_claim_count": 0,
        }
        for key, threshold in minimums.items():
            value = evidence.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                failures.append(f"{key}: missing/non-finite evidence")
            elif value < threshold:
                failures.append(f"{key}: {value} below {threshold}")
        for key, threshold in maximums.items():
            value = evidence.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                failures.append(f"{key}: missing/non-finite evidence")
            elif value > threshold:
                failures.append(f"{key}: {value} above {threshold}")

        for key in (
            "provenance_coverage",
            "license_locator_coverage",
            "ablation_coverage",
            "negative_control_coverage",
            "reproducibility_receipt_coverage",
            "rater_conflict_disclosure_coverage",
        ):
            if evidence.get(key) != 1.0:
                failures.append(f"{key}: must equal 1.0")

        agency_counts = evidence.get("agency_preference_counts")
        agency_lowers: dict[str, float] = {}
        if not isinstance(agency_counts, Mapping) or len(agency_counts) != 10:
            failures.append("agency_preference_counts: exactly ten agencies required")
        else:
            for agency_id, counts in agency_counts.items():
                if (
                    not isinstance(counts, Mapping)
                    or not isinstance(counts.get("preferred"), int)
                    or not isinstance(counts.get("comparisons"), int)
                ):
                    failures.append(f"{agency_id}: invalid raw preference counts")
                    continue
                preferred = counts["preferred"]
                comparisons = counts["comparisons"]
                if comparisons < self.minimum_comparisons_per_agency:
                    failures.append(f"{agency_id}: too few blind comparisons")
                    continue
                try:
                    lower = wilson_lower_bound(preferred, comparisons)
                except Exception:
                    failures.append(f"{agency_id}: impossible preference counts")
                    continue
                agency_lowers[str(agency_id)] = lower
                if lower < self.minimum_each_agency_wilson_lower_95:
                    failures.append(f"{agency_id}: fails pairwise non-inferiority")

        overall_preferred = evidence.get("overall_preferred_count")
        overall_comparisons = evidence.get("overall_comparison_count")
        overall_lower: float | None = None
        if isinstance(overall_preferred, int) and isinstance(
            overall_comparisons, int
        ):
            try:
                overall_lower = wilson_lower_bound(
                    overall_preferred,
                    overall_comparisons,
                )
            except Exception:
                failures.append("overall preference counts are impossible")
            else:
                if overall_lower < self.minimum_overall_wilson_lower_95:
                    failures.append("overall Top-1 preference lower bound failed")
        else:
            failures.append("raw overall preference counts are required")

        return Top1FourATrainingAudit(
            passed=not failures,
            failures=tuple(dict.fromkeys(failures)),
            agency_wilson_lower_95=agency_lowers,
            overall_wilson_lower_95=overall_lower,
        )


@dataclass(frozen=True)
class Top1FourATrainingAudit:
    passed: bool
    failures: tuple[str, ...]
    agency_wilson_lower_95: Mapping[str, float]
    overall_wilson_lower_95: float | None
    schema: str = "ProofLaunchTop1FourATrainingAuditV1"

