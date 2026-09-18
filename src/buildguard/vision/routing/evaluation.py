"""Comparable routing metrics across all four strategies."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import Field

from buildguard.config import VisionModelConfig
from buildguard.schemas.common import StrictSchema
from buildguard.vision.routing.router import VisualRouter
from buildguard.vision.routing.schemas import (
    RoiFeatures,
    RoutingDecision,
    RoutingStrategy,
)


class RoutingPrediction(StrictSchema):
    label: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    true_positive: bool


class RoutingEvaluationCase(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    features: RoiFeatures
    ground_truth_classes: list[str] = Field(default_factory=list)
    high_risk_classes: list[str] = Field(default_factory=list)
    model_predictions: dict[str, list[RoutingPrediction]] = Field(default_factory=dict)
    measured_model_latency_ms: dict[str, float] = Field(default_factory=dict)
    measured_model_vram_mb: dict[str, float] = Field(default_factory=dict)
    temporal_key: str | None = None


class RoutingEvaluationMetrics(StrictSchema):
    strategy: RoutingStrategy
    recall: float = Field(ge=0, le=1)
    map: float = Field(ge=0, le=1)
    high_risk_recall: float = Field(ge=0, le=1)
    call_count: int = Field(ge=0)
    call_reduction: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)
    vram_mb: float = Field(ge=0)
    average_models_per_roi: float = Field(ge=0)
    guard_rate: float = Field(ge=0, le=1)
    resource_source: Literal["measured", "estimated"] = "estimated"


class RoutingEvaluationResult(StrictSchema):
    metrics: RoutingEvaluationMetrics
    decisions: list[RoutingDecision]


def _average_precision(
    predictions: list[tuple[float, bool]],
    ground_truth_count: int,
) -> float:
    if ground_truth_count <= 0:
        return 0.0
    ordered = sorted(predictions, key=lambda item: (-item[0], not item[1]))
    true_positives = 0
    precision_sum = 0.0
    for rank, (_, is_true_positive) in enumerate(ordered, start=1):
        if is_true_positive:
            true_positives += 1
            precision_sum += true_positives / rank
    return min(1.0, precision_sum / ground_truth_count)


class RoutingEvaluator:
    def __init__(
        self,
        router: VisualRouter,
        models: list[VisionModelConfig],
    ) -> None:
        self.router = router
        self.models = list(models)
        self.model_by_name = {model.model_name: model for model in models}

    def evaluate(
        self,
        cases: list[RoutingEvaluationCase],
        strategy: RoutingStrategy,
    ) -> RoutingEvaluationResult:
        self.router.smoother.reset()
        decisions: list[RoutingDecision] = []
        total_ground_truth = 0
        found_ground_truth = 0
        total_high_risk = 0
        found_high_risk = 0
        call_count = 0
        full_all_calls = 0
        total_latency = 0.0
        peak_vram = 0.0
        guarded = 0
        measured_resources = True
        class_predictions: dict[str, list[tuple[float, bool]]] = defaultdict(list)
        class_ground_truth: dict[str, int] = defaultdict(int)
        for case in cases:
            decision = self.router.route(
                case.features,
                self.models,
                strategy=strategy,
                temporal_key=case.temporal_key,
            )
            decisions.append(decision)
            selected = set(decision.selected_model_names)
            predictions = [
                prediction
                for model_name in selected
                for prediction in case.model_predictions.get(model_name, [])
            ]
            true_labels = {
                prediction.label
                for prediction in predictions
                if prediction.true_positive
            }
            ground_truth = set(case.ground_truth_classes)
            high_risk = ground_truth & set(case.high_risk_classes)
            total_ground_truth += len(ground_truth)
            found_ground_truth += len(ground_truth & true_labels)
            total_high_risk += len(high_risk)
            found_high_risk += len(high_risk & true_labels)
            for label in ground_truth:
                class_ground_truth[label] += 1
            for prediction in predictions:
                class_predictions[prediction.label].append(
                    (prediction.confidence, prediction.true_positive)
                )
            call_count += len(selected)
            full_all_calls += len(decision.candidate_model_names)
            if not all(
                name in case.measured_model_latency_ms
                and name in case.measured_model_vram_mb
                for name in selected
            ):
                measured_resources = False
            total_latency += sum(
                case.measured_model_latency_ms.get(
                    name,
                    self.model_by_name[name].estimated_latency_ms,
                )
                for name in selected
            )
            peak_vram = max(
                peak_vram,
                sum(
                    case.measured_model_vram_mb.get(
                        name,
                        self.model_by_name[name].estimated_memory_mb,
                    )
                    for name in selected
                ),
            )
            guarded += int(decision.guard_triggered)
        average_precisions = [
            _average_precision(
                class_predictions[label],
                count,
            )
            for label, count in sorted(class_ground_truth.items())
        ]
        case_count = len(cases)
        metrics = RoutingEvaluationMetrics(
            strategy=strategy,
            recall=(
                found_ground_truth / total_ground_truth
                if total_ground_truth
                else 0.0
            ),
            map=(
                sum(average_precisions) / len(average_precisions)
                if average_precisions
                else 0.0
            ),
            high_risk_recall=(
                found_high_risk / total_high_risk if total_high_risk else 0.0
            ),
            call_count=call_count,
            call_reduction=(
                max(0.0, 1.0 - call_count / full_all_calls)
                if full_all_calls
                else 0.0
            ),
            latency_ms=total_latency,
            vram_mb=peak_vram,
            average_models_per_roi=call_count / case_count if case_count else 0.0,
            guard_rate=guarded / case_count if case_count else 0.0,
            resource_source="measured" if measured_resources else "estimated",
        )
        return RoutingEvaluationResult(metrics=metrics, decisions=decisions)

    def compare(
        self,
        cases: list[RoutingEvaluationCase],
    ) -> dict[RoutingStrategy, RoutingEvaluationResult]:
        strategies: tuple[RoutingStrategy, ...] = (
            "full-all",
            "rule",
            "cost-aware",
            "cost-aware-guard",
        )
        return {
            strategy: self.evaluate(cases, strategy)
            for strategy in strategies
        }
