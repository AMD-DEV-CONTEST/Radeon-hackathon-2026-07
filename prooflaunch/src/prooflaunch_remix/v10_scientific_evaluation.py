from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .quality_contract import wilson_lower_bound
from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


class BenchmarkPartition(str, Enum):
    ENTITY_PRODUCT = "entity_product"
    AGENT_PRODUCT = "agent_product"
    LONG_DOCUMENT = "long_document"
    MULTI_IMAGE = "multi_image"
    VIDEO = "video"
    AUDIO = "audio"
    TOOL_TRAJECTORY = "tool_trajectory"
    MEMORY = "memory"
    FOUR_A_CAMPAIGN = "four_a_campaign"


@dataclass(frozen=True)
class FrozenEvalCase:
    case_id: str
    partition: BenchmarkPartition
    modalities: tuple[str, ...]
    source_locator: str
    source_sha256: str
    expected_schema_sha256: str
    rights: str = "project_owned"
    split: str = "sealed_test"
    training_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.source_locator.strip():
            raise V10ContractError("evaluation case identity and locator are required")
        if not self.modalities or any(item not in {"text", "image", "video", "audio", "tool", "memory"} for item in self.modalities):
            raise V10ContractError("evaluation case modalities are invalid")
        _require_sha256(self.source_sha256, "source_sha256")
        _require_sha256(self.expected_schema_sha256, "expected_schema_sha256")
        if self.rights != "project_owned" or self.split != "sealed_test" or self.training_allowed:
            raise V10ContractError("frozen evaluation cases must be project-owned, sealed and training-excluded")


@dataclass(frozen=True)
class FrozenGtmBench:
    benchmark_id: str
    cases: tuple[FrozenEvalCase, ...]
    canaries: Mapping[BenchmarkPartition, str]
    protocol_sha256: str

    def __post_init__(self) -> None:
        if not self.benchmark_id.strip():
            raise V10ContractError("benchmark_id is required")
        _require_sha256(self.protocol_sha256, "protocol_sha256")
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise V10ContractError("evaluation case IDs must be unique")
        if set(self.canaries) != set(BenchmarkPartition):
            raise V10ContractError("every benchmark partition requires a leakage canary")
        for partition in BenchmarkPartition:
            partition_cases = [item for item in self.cases if item.partition == partition]
            if len(partition_cases) < 2:
                raise V10ContractError("every benchmark partition requires at least two cases")
        if len(set(self.canaries.values())) != len(self.canaries) or any(not value.strip() for value in self.canaries.values()):
            raise V10ContractError("benchmark canaries must be unique and nonempty")

    @property
    def content_sha256(self) -> str:
        return stable_sha256(
            {
                "benchmark_id": self.benchmark_id,
                "protocol_sha256": self.protocol_sha256,
                "cases": [asdict(item) for item in sorted(self.cases, key=lambda case: case.case_id)],
                "canaries": {key.value: value for key, value in sorted(self.canaries.items(), key=lambda item: item[0].value)},
            }
        )


class BaselineLane(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    GTM_AGENT = "gtm_agent"


@dataclass(frozen=True)
class FrozenBaseline:
    lane: BaselineLane
    name: str
    revision: str
    settings_sha256: str
    source_url: str
    license_name: str
    selection_rationale: str
    same_input_required: bool = True
    same_hardware_required: bool = True
    frozen_before_candidate_results: bool = True

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.name, self.revision, self.source_url, self.license_name, self.selection_rationale)):
            raise V10ContractError("baseline metadata is incomplete")
        _require_sha256(self.settings_sha256, "settings_sha256")
        if not self.source_url.startswith("https://"):
            raise V10ContractError("baseline source URL must be public HTTPS")
        if not (self.same_input_required and self.same_hardware_required and self.frozen_before_candidate_results):
            raise V10ContractError("baseline selection must precede results and require matched execution")


@dataclass(frozen=True)
class BaselineSet:
    baselines: tuple[FrozenBaseline, ...]

    def __post_init__(self) -> None:
        if {item.lane for item in self.baselines} != set(BaselineLane) or len(self.baselines) != len(BaselineLane):
            raise V10ContractError("one frozen baseline is required for each image, video and GTM-agent lane")

    @property
    def content_sha256(self) -> str:
        return stable_sha256([asdict(item) for item in sorted(self.baselines, key=lambda item: item.lane.value)])


@dataclass(frozen=True)
class BinaryConfusion:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in asdict(self).values()):
            raise V10ContractError("confusion counts must be non-negative integers")

    def precision_receipt(self, metric: str) -> "MetricReceipt":
        return MetricReceipt(metric, self.true_positive, self.true_positive + self.false_positive, "tp/(tp+fp)")

    def recall_receipt(self, metric: str) -> "MetricReceipt":
        return MetricReceipt(metric, self.true_positive, self.true_positive + self.false_negative, "tp/(tp+fn)")


@dataclass(frozen=True)
class MetricReceipt:
    metric: str
    numerator: int
    denominator: int
    formula: str
    evidence_locator: str = "project://scientific-evaluation/formula-fixture"

    def __post_init__(self) -> None:
        if not self.metric.strip() or not self.formula.strip() or not self.evidence_locator.strip():
            raise V10ContractError("metric identity, formula and locator are required")
        if isinstance(self.numerator, bool) or isinstance(self.denominator, bool) or not isinstance(self.numerator, int) or not isinstance(self.denominator, int):
            raise V10ContractError("metric counts must be integers")
        if self.denominator <= 0 or not 0 <= self.numerator <= self.denominator:
            raise V10ContractError("metric numerator and denominator are impossible")

    @property
    def value(self) -> float:
        return self.numerator / self.denominator


SCIENTIFIC_METRIC_NAMES = (
    "claim_precision",
    "claim_recall",
    "schema_validity",
    "agent_success",
    "tool_error",
    "trajectory_accuracy",
    "failure_attribution_accuracy",
    "memory_precision",
    "stale_recall",
    "image_identity",
    "video_identity",
    "temporal_consistency",
    "audio_video_alignment",
)


@dataclass(frozen=True)
class ScientificMetricBundle:
    metrics: tuple[MetricReceipt, ...]

    def __post_init__(self) -> None:
        names = tuple(item.metric for item in self.metrics)
        if names != SCIENTIFIC_METRIC_NAMES:
            raise V10ContractError("scientific metrics must use the exact preregistered order")

    @property
    def content_sha256(self) -> str:
        return stable_sha256([asdict(item) for item in self.metrics])

    def values(self) -> dict[str, float]:
        return {item.metric: item.value for item in self.metrics}


def build_metric_bundle(
    *,
    claim_confusion: BinaryConfusion,
    counts: Mapping[str, tuple[int, int]],
) -> ScientificMetricBundle:
    expected = set(SCIENTIFIC_METRIC_NAMES) - {"claim_precision", "claim_recall"}
    if set(counts) != expected:
        raise V10ContractError("all non-Claim metric counts are required with no extras")
    receipts = [
        claim_confusion.precision_receipt("claim_precision"),
        claim_confusion.recall_receipt("claim_recall"),
    ]
    for name in SCIENTIFIC_METRIC_NAMES[2:]:
        numerator, denominator = counts[name]
        formula = "error_count/total_calls" if name == "tool_error" else "passed/eligible"
        receipts.append(MetricReceipt(name, numerator, denominator, formula))
    return ScientificMetricBundle(tuple(receipts))


@dataclass(frozen=True)
class BlindPreferenceReceipt:
    preferred_count: int
    comparison_count: int

    def __post_init__(self) -> None:
        if self.comparison_count <= 0 or not 0 <= self.preferred_count <= self.comparison_count:
            raise V10ContractError("blind preference counts are impossible")

    @property
    def rate(self) -> float:
        return self.preferred_count / self.comparison_count

    @property
    def wilson_lower_95(self) -> float:
        return wilson_lower_bound(self.preferred_count, self.comparison_count)


@dataclass(frozen=True)
class ReviewerCalibrationPlan:
    reviewer_ids: tuple[str, ...]
    ratings_per_reviewer: int
    gold_case_count: int
    candidate_identity_blinded: bool
    randomized_order: bool
    conflict_disclosure_required: bool

    def __post_init__(self) -> None:
        if len(self.reviewer_ids) != 5 or len(set(self.reviewer_ids)) != 5:
            raise V10ContractError("exactly five independent reviewers are required")
        if self.ratings_per_reviewer < 300 or self.gold_case_count < 20:
            raise V10ContractError("the plan must support at least 1,500 ratings and 20 gold cases")
        if not (self.candidate_identity_blinded and self.randomized_order and self.conflict_disclosure_required):
            raise V10ContractError("review calibration must be blinded, randomized and conflict-aware")

    @property
    def planned_rating_count(self) -> int:
        return len(self.reviewer_ids) * self.ratings_per_reviewer


def planned_scientific_report(bench: FrozenGtmBench, baselines: BaselineSet, reviewer_plan: ReviewerCalibrationPlan) -> dict[str, object]:
    return {
        "schema": "ProofLaunchScientificReportV1",
        "status": "planned_not_executed",
        "benchmark_sha256": bench.content_sha256,
        "baseline_set_sha256": baselines.content_sha256,
        "reviewer_plan": asdict(reviewer_plan),
        "observed_runs": {
            "v7_4": None,
            "base_model": None,
            "no_kd": None,
            "no_cpt": None,
            "no_sft": None,
            "no_rl": None,
            "no_memory": None,
            "no_world_model": None,
            "single_agent": None,
            "fixed_topology": None,
            "no_audit": None,
            "no_repair": None,
        },
        "human_evidence": {
            "rating_count": None,
            "krippendorff_alpha": None,
            "four_a_mean": None,
            "publishable_rate": None,
            "preference_rate": None,
            "wilson_lower_95": None,
            "critic_tpr": None,
            "critic_tnr": None,
        },
        "top3_claim_eligible": False,
        "frozen": False,
        "truth_boundary": "Frozen project-owned protocol and formula fixtures do not prove model quality, human preference, ablation gains or Top-3 standing.",
    }
