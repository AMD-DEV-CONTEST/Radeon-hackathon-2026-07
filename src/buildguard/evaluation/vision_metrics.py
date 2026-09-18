"""Detection and recall-guarded routing metrics."""

from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from buildguard.schemas.common import StrictSchema


class VisionPrediction(StrictSchema):
    label: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    matched: bool


class VisionEvaluationCase(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    ground_truth_labels: list[str] = Field(default_factory=list)
    high_risk_labels: list[str] = Field(default_factory=list)
    predictions: list[VisionPrediction] = Field(default_factory=list)
    model_calls: int = Field(ge=0)
    full_model_calls: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    vram_mb: float | None = Field(default=None, ge=0)
    processed_frames: int = Field(default=1, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)


class VisionMetrics(StrictSchema):
    map: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    high_risk_recall: float = Field(ge=0, le=1)
    model_calls: int = Field(ge=0)
    reduction_rate: float = Field(ge=0, le=1)
    average_latency_ms: float = Field(ge=0)
    peak_vram_mb: float | None = Field(default=None, ge=0)
    fps: float = Field(ge=0)
    evaluated_cases: int = Field(ge=0)


def _average_precision(
    predictions: list[tuple[float, bool]],
    ground_truth_count: int,
) -> float:
    if ground_truth_count == 0:
        return 0
    matched = 0
    precision_sum = 0.0
    for rank, (_, is_match) in enumerate(
        sorted(predictions, key=lambda item: (-item[0], not item[1])),
        start=1,
    ):
        if is_match:
            matched += 1
            precision_sum += matched / rank
    return min(1.0, precision_sum / ground_truth_count)


def evaluate_vision(cases: list[VisionEvaluationCase]) -> VisionMetrics:
    ground_truth: dict[str, int] = defaultdict(int)
    predictions: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    total_truth = 0
    found_truth = 0
    total_high_risk = 0
    found_high_risk = 0
    for case in cases:
        true_labels = set(case.ground_truth_labels)
        found_labels = {item.label for item in case.predictions if item.matched}
        total_truth += len(true_labels)
        found_truth += len(true_labels & found_labels)
        high_risk = true_labels & set(case.high_risk_labels)
        total_high_risk += len(high_risk)
        found_high_risk += len(high_risk & found_labels)
        for label in true_labels:
            ground_truth[label] += 1
        for prediction in case.predictions:
            predictions[prediction.label].append(
                (prediction.confidence, prediction.matched)
            )
    aps = [
        _average_precision(predictions[label], count)
        for label, count in sorted(ground_truth.items())
    ]
    model_calls = sum(case.model_calls for case in cases)
    full_calls = sum(case.full_model_calls for case in cases)
    elapsed = sum(case.elapsed_seconds for case in cases)
    measured_vram = [case.vram_mb for case in cases if case.vram_mb is not None]
    return VisionMetrics(
        map=sum(aps) / len(aps) if aps else 0,
        recall=found_truth / total_truth if total_truth else 0,
        high_risk_recall=(
            found_high_risk / total_high_risk if total_high_risk else 0
        ),
        model_calls=model_calls,
        reduction_rate=max(0.0, 1 - model_calls / full_calls) if full_calls else 0,
        average_latency_ms=(
            sum(case.latency_ms for case in cases) / len(cases) if cases else 0
        ),
        peak_vram_mb=max(measured_vram) if measured_vram else None,
        fps=(
            sum(case.processed_frames for case in cases) / elapsed if elapsed else 0
        ),
        evaluated_cases=len(cases),
    )
