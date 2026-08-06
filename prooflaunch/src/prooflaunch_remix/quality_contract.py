from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping


class QualityContractError(RuntimeError):
    pass


class QualityTier(str, Enum):
    STANDARD = "standard"
    COMPETITION_2X = "competition_2x"
    CORTEX_X_V10 = "cortex_x_v10"


class MetricOperator(str, Enum):
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


@dataclass(frozen=True)
class QualityMetricSpec:
    key: str
    operator: MetricOperator
    threshold: float
    unit: str
    rationale: str

    def passes(self, value: float) -> bool:
        if self.operator == MetricOperator.AT_LEAST:
            return value >= self.threshold
        if self.operator == MetricOperator.AT_MOST:
            return value <= self.threshold
        if self.operator == MetricOperator.LESS_THAN:
            return value < self.threshold
        return value > self.threshold


@dataclass(frozen=True)
class QualityMetricResult:
    key: str
    passed: bool
    actual: float | None
    operator: str
    threshold: float
    unit: str
    reason: str


@dataclass(frozen=True)
class QualityAcceptanceReport:
    tier: QualityTier
    passed: bool
    metrics: tuple[QualityMetricResult, ...]
    derived_metrics: Mapping[str, float]
    schema: str = "ProofLaunchQualityAcceptanceReportV1"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "tier": self.tier.value,
            "passed": self.passed,
            "metrics": [asdict(item) for item in self.metrics],
            "derived_metrics": dict(self.derived_metrics),
        }


@dataclass(frozen=True)
class QualityAcceptanceContract:
    tier: QualityTier
    metrics: tuple[QualityMetricSpec, ...]
    schema: str = "ProofLaunchQualityAcceptanceContractV1"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "tier": self.tier.value,
            "metrics": [
                {
                    **asdict(item),
                    "operator": item.operator.value,
                }
                for item in self.metrics
            ],
        }

    def evaluate(self, evidence: Mapping[str, object]) -> QualityAcceptanceReport:
        normalized, derived = _normalize_evidence(evidence)
        required_schema = {
            QualityTier.COMPETITION_2X: "ProofLaunchCompetition2XCompiledEvidenceV2",
            QualityTier.CORTEX_X_V10: "ProofLaunchCortexXV10CompiledEvidenceV1",
        }.get(self.tier)
        if required_schema is not None and evidence.get("schema") != required_schema:
            normalized = {}
            derived = {}
        results: list[QualityMetricResult] = []
        for spec in self.metrics:
            actual = normalized.get(spec.key)
            if actual is None:
                results.append(
                    QualityMetricResult(
                        key=spec.key,
                        passed=False,
                        actual=None,
                        operator=spec.operator.value,
                        threshold=spec.threshold,
                        unit=spec.unit,
                        reason="required metric is missing or non-numeric",
                    )
                )
                continue
            passed = spec.passes(actual)
            results.append(
                QualityMetricResult(
                    key=spec.key,
                    passed=passed,
                    actual=actual,
                    operator=spec.operator.value,
                    threshold=spec.threshold,
                    unit=spec.unit,
                    reason="accepted" if passed else "threshold not met",
                )
            )
        return QualityAcceptanceReport(
            tier=self.tier,
            passed=all(item.passed for item in results),
            metrics=tuple(results),
            derived_metrics=derived,
        )


def wilson_lower_bound(successes: int, trials: int, *, z: float = 1.95996398454) -> float:
    if trials <= 0:
        raise QualityContractError("Wilson interval requires at least one trial")
    if successes < 0 or successes > trials:
        raise QualityContractError("successes must be between zero and trials")
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = proportion + z * z / (2 * trials)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)
    )
    return (centre - margin) / denominator


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _integer(value: object) -> int | None:
    number = _numeric(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _normalize_evidence(
    evidence: Mapping[str, object],
) -> tuple[dict[str, float], dict[str, float]]:
    normalized = {
        key: number
        for key, value in evidence.items()
        if (number := _numeric(value)) is not None
    }
    for derived_key in (
        "publish_preference_rate",
        "publish_preference_lower_95",
        "human_rating_count",
    ):
        normalized.pop(derived_key, None)
    derived: dict[str, float] = {}
    successes = _integer(evidence.get("publish_preferred_count"))
    trials = _integer(evidence.get("publish_comparison_count"))
    if successes is not None and trials is not None and trials > 0:
        preference_rate = successes / trials
        lower_bound = wilson_lower_bound(successes, trials)
        normalized["publish_preference_rate"] = preference_rate
        normalized["publish_preference_lower_95"] = lower_bound
        normalized["human_rating_count"] = float(trials)
        derived.update(
            {
                "publish_preference_rate": preference_rate,
                "publish_preference_lower_95": lower_bound,
                "human_rating_count": float(trials),
            }
        )
    return normalized, derived


STANDARD_METRICS = (
    QualityMetricSpec(
        "product_count", MetricOperator.AT_LEAST, 1, "products", "minimum smoke set"
    ),
    QualityMetricSpec(
        "aspect_ratio_count",
        MetricOperator.AT_LEAST,
        1,
        "ratios",
        "minimum output-shape coverage",
    ),
    QualityMetricSpec(
        "unsupported_claim_count",
        MetricOperator.AT_MOST,
        0,
        "claims",
        "release must never contain an unsupported claim",
    ),
    QualityMetricSpec(
        "locator_coverage",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "every factual observation needs a source locator",
    ),
    QualityMetricSpec(
        "completion_rate",
        MetricOperator.AT_LEAST,
        0.90,
        "ratio",
        "workflow reliability floor",
    ),
    QualityMetricSpec(
        "crash_rate",
        MetricOperator.AT_MOST,
        0.05,
        "ratio",
        "workflow crash ceiling",
    ),
)


COMPETITION_2X_METRICS = (
    QualityMetricSpec(
        "product_count",
        MetricOperator.AT_LEAST,
        30,
        "products",
        "broad product-domain benchmark",
    ),
    QualityMetricSpec(
        "aspect_ratio_count",
        MetricOperator.AT_LEAST,
        3,
        "ratios",
        "1:1, 4:5, and 9:16 output coverage",
    ),
    QualityMetricSpec(
        "seeds_per_product",
        MetricOperator.AT_LEAST,
        5,
        "seeds",
        "generation stability across seeds",
    ),
    QualityMetricSpec(
        "video_case_count",
        MetricOperator.AT_LEAST,
        30,
        "cases",
        "at least one full audio-video export per benchmark product",
    ),
    QualityMetricSpec(
        "human_raters",
        MetricOperator.AT_LEAST,
        5,
        "raters",
        "independent preference coverage",
    ),
    QualityMetricSpec(
        "human_rating_count",
        MetricOperator.AT_LEAST,
        150,
        "comparisons",
        "at least one blind comparison per product and rater",
    ),
    QualityMetricSpec(
        "repair_budget_max",
        MetricOperator.AT_MOST,
        2,
        "repairs",
        "bounded agent behavior",
    ),
    QualityMetricSpec(
        "unsupported_claim_count",
        MetricOperator.AT_MOST,
        0,
        "claims",
        "zero unsupported claims",
    ),
    QualityMetricSpec(
        "locator_coverage",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "all evidence must be source-located",
    ),
    QualityMetricSpec(
        "image_identity_pass_rate",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "exact product identity on still images",
    ),
    QualityMetricSpec(
        "preencode_video_identity_pass_rate",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "exact composited identity before codec",
    ),
    QualityMetricSpec(
        "encoded_video_identity_pass_rate",
        MetricOperator.AT_LEAST,
        0.95,
        "ratio",
        "product identity after the delivery codec",
    ),
    QualityMetricSpec(
        "audio_video_alignment_pass_rate",
        MetricOperator.AT_LEAST,
        0.95,
        "ratio",
        "semantic event timing survives final export",
    ),
    QualityMetricSpec(
        "cross_media_pass_rate",
        MetricOperator.AT_LEAST,
        0.95,
        "ratio",
        "claims and product semantics agree across media",
    ),
    QualityMetricSpec(
        "completion_rate",
        MetricOperator.AT_LEAST,
        0.95,
        "ratio",
        "end-to-end mission reliability",
    ),
    QualityMetricSpec(
        "crash_rate",
        MetricOperator.AT_MOST,
        0.02,
        "ratio",
        "strict workflow crash ceiling",
    ),
    QualityMetricSpec(
        "seed_diversity_group_pass_rate",
        MetricOperator.AT_LEAST,
        0.95,
        "ratio",
        "five-seed outputs vary without losing exact product identity",
    ),
    QualityMetricSpec(
        "baseline_completion_rate_gap",
        MetricOperator.AT_LEAST,
        0.0,
        "ratio",
        "completion must be no worse than the declared baseline on the same cases",
    ),
    QualityMetricSpec(
        "publish_preference_rate",
        MetricOperator.AT_LEAST,
        0.60,
        "ratio",
        "blind preference over the declared baseline",
    ),
    QualityMetricSpec(
        "publish_preference_lower_95",
        MetricOperator.GREATER_THAN,
        0.50,
        "ratio",
        "preference result must clear chance at 95% confidence",
    ),
)


CORTEX_X_V10_METRICS = (
    QualityMetricSpec(
        "four_a_overall_mean",
        MetricOperator.AT_LEAST,
        4.8,
        "score/5",
        "five-reviewer blind 4A quality floor",
    ),
    QualityMetricSpec(
        "four_a_min_dimension",
        MetricOperator.AT_LEAST,
        4.6,
        "score/5",
        "no 4A dimension may hide behind the overall mean",
    ),
    QualityMetricSpec(
        "directly_publishable_rate",
        MetricOperator.AT_LEAST,
        0.97,
        "ratio",
        "release quality without major modification",
    ),
    QualityMetricSpec(
        "baseline_count",
        MetricOperator.AT_LEAST,
        5,
        "baselines",
        "same-hardware frozen comparison breadth",
    ),
    QualityMetricSpec(
        "human_raters",
        MetricOperator.AT_LEAST,
        5,
        "raters",
        "independent blind-review coverage",
    ),
    QualityMetricSpec(
        "human_rating_count",
        MetricOperator.AT_LEAST,
        150,
        "comparisons",
        "minimum evidence for preference inference",
    ),
    QualityMetricSpec(
        "publish_preference_rate",
        MetricOperator.AT_LEAST,
        0.80,
        "ratio",
        "blind preference over five frozen baselines",
    ),
    QualityMetricSpec(
        "publish_preference_lower_95",
        MetricOperator.GREATER_THAN,
        0.70,
        "ratio",
        "preference must clear the V10 Wilson lower bound",
    ),
    QualityMetricSpec(
        "gtm_gain_vs_base",
        MetricOperator.AT_LEAST,
        0.45,
        "ratio",
        "frozen GTM benchmark gain over the current base model",
    ),
    QualityMetricSpec(
        "gtm_gain_vs_v9",
        MetricOperator.AT_LEAST,
        0.20,
        "ratio",
        "incremental gain attributable to V10 breakthroughs",
    ),
    QualityMetricSpec(
        "general_multimodal_regression",
        MetricOperator.AT_MOST,
        0.005,
        "absolute ratio",
        "retain general multimodal ability",
    ),
    QualityMetricSpec(
        "agent_success_rate",
        MetricOperator.AT_LEAST,
        0.99,
        "ratio",
        "end-to-end GTM coworker reliability",
    ),
    QualityMetricSpec(
        "tool_error_rate",
        MetricOperator.LESS_THAN,
        0.002,
        "ratio",
        "strict tool invocation error ceiling",
    ),
    QualityMetricSpec(
        "structured_output_valid_rate",
        MetricOperator.AT_LEAST,
        0.998,
        "ratio",
        "typed agent boundary reliability",
    ),
    QualityMetricSpec(
        "critical_unsupported_claim_count",
        MetricOperator.AT_MOST,
        0,
        "claims",
        "critical unsupported claims are forbidden",
    ),
    QualityMetricSpec(
        "claim_locator_coverage",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "every claim binds to a source locator",
    ),
    QualityMetricSpec(
        "rights_locator_coverage",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "every source asset binds to a rights record",
    ),
    QualityMetricSpec(
        "approval_coverage",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "every released asset binds to an approver",
    ),
    QualityMetricSpec(
        "ocr_accuracy",
        MetricOperator.AT_LEAST,
        0.9995,
        "ratio",
        "4K mastered text fidelity",
    ),
    QualityMetricSpec(
        "brand_delta_e",
        MetricOperator.AT_MOST,
        1.0,
        "Delta E 2000",
        "brand color fidelity",
    ),
    QualityMetricSpec(
        "product_identity_rate",
        MetricOperator.AT_LEAST,
        0.995,
        "ratio",
        "product and logo identity retention",
    ),
    QualityMetricSpec(
        "temporal_gain_vs_base",
        MetricOperator.AT_LEAST,
        0.30,
        "ratio",
        "temporal quality improvement over the base generation path",
    ),
    QualityMetricSpec(
        "audio_video_alignment",
        MetricOperator.AT_LEAST,
        0.96,
        "ratio",
        "semantic audio/video event alignment",
    ),
    QualityMetricSpec(
        "simulated_business_claim_count",
        MetricOperator.AT_MOST,
        0,
        "claims",
        "predictions may not be presented as observed business outcomes",
    ),
    QualityMetricSpec(
        "radeon_core_evidence_coverage",
        MetricOperator.AT_LEAST,
        1.0,
        "ratio",
        "all core inference, generation, enhancement, and audit paths need Radeon traces",
    ),
    QualityMetricSpec(
        "breakthrough_evidence_count",
        MetricOperator.AT_LEAST,
        12,
        "bets",
        "all twelve breakthrough bets must produce evidence",
    ),
    QualityMetricSpec(
        "breakthrough_promoted_count",
        MetricOperator.AT_LEAST,
        3,
        "bets",
        "at least three bets must pass technical, product, and effect gates",
    ),
    QualityMetricSpec(
        "repair_budget_max",
        MetricOperator.AT_MOST,
        2,
        "repairs",
        "repair remains bounded and localized",
    ),
)


def contract_for(tier: QualityTier | str) -> QualityAcceptanceContract:
    try:
        selected = QualityTier(tier)
    except ValueError as error:
        raise QualityContractError(f"unknown quality tier: {tier}") from error
    metrics = {
        QualityTier.STANDARD: STANDARD_METRICS,
        QualityTier.COMPETITION_2X: COMPETITION_2X_METRICS,
        QualityTier.CORTEX_X_V10: CORTEX_X_V10_METRICS,
    }[selected]
    return QualityAcceptanceContract(tier=selected, metrics=metrics)
