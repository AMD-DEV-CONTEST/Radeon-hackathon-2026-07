"""Frame, event, reconnect, and continuous video stability metrics."""

from __future__ import annotations

from pydantic import Field, NonNegativeFloat, model_validator

from buildguard.schemas.common import StrictSchema


class RealtimeEvaluationCase(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    frame_ground_truth: list[bool] = Field(default_factory=list)
    frame_predictions: list[bool] = Field(default_factory=list)
    ground_truth_event_ids: list[str] = Field(default_factory=list)
    detected_event_ids: list[str] = Field(default_factory=list)
    emitted_event_ids: list[str] = Field(default_factory=list)
    confirmation_latencies_ms: list[NonNegativeFloat] = Field(default_factory=list)
    reconnect_times_seconds: list[NonNegativeFloat] = Field(default_factory=list)
    observed_seconds: float = Field(default=0, ge=0)
    crashed: bool = False

    @model_validator(mode="after")
    def frame_lengths_match(self) -> RealtimeEvaluationCase:
        if len(self.frame_ground_truth) != len(self.frame_predictions):
            raise ValueError("frame ground truth and predictions must have equal length")
        return self


class RealtimeMetrics(StrictSchema):
    frame_false_positive_rate: float = Field(ge=0, le=1)
    event_false_positive_rate: float = Field(ge=0, le=1)
    event_miss_rate: float = Field(ge=0, le=1)
    duplicate_event_rate: float = Field(ge=0, le=1)
    average_confirmation_latency_ms: float = Field(ge=0)
    average_reconnect_time_seconds: float = Field(ge=0)
    continuous_stability: float = Field(ge=0, le=1)
    observed_seconds: float = Field(ge=0)
    evaluated_cases: int = Field(ge=0)


def evaluate_realtime(cases: list[RealtimeEvaluationCase]) -> RealtimeMetrics:
    frame_pairs = [
        pair
        for case in cases
        for pair in zip(case.frame_ground_truth, case.frame_predictions, strict=True)
    ]
    negative_frames = sum(not truth for truth, _ in frame_pairs)
    false_positive_frames = sum(
        prediction and not truth for truth, prediction in frame_pairs
    )
    ground_truth_events = {
        event_id for case in cases for event_id in case.ground_truth_event_ids
    }
    detected_events = {
        event_id for case in cases for event_id in case.detected_event_ids
    }
    emitted = [event_id for case in cases for event_id in case.emitted_event_ids]
    unique_emitted = set(emitted)
    false_events = unique_emitted - ground_truth_events
    missed_events = ground_truth_events - detected_events
    duplicate_count = len(emitted) - len(unique_emitted)
    confirmation = [
        value for case in cases for value in case.confirmation_latencies_ms
    ]
    reconnect = [value for case in cases for value in case.reconnect_times_seconds]
    total_seconds = sum(case.observed_seconds for case in cases)
    stable_seconds = sum(
        case.observed_seconds for case in cases if not case.crashed
    )
    return RealtimeMetrics(
        frame_false_positive_rate=(
            false_positive_frames / negative_frames if negative_frames else 0
        ),
        event_false_positive_rate=(
            len(false_events) / len(unique_emitted) if unique_emitted else 0
        ),
        event_miss_rate=(
            len(missed_events) / len(ground_truth_events)
            if ground_truth_events
            else 0
        ),
        duplicate_event_rate=duplicate_count / len(emitted) if emitted else 0,
        average_confirmation_latency_ms=(
            sum(confirmation) / len(confirmation) if confirmation else 0
        ),
        average_reconnect_time_seconds=(
            sum(reconnect) / len(reconnect) if reconnect else 0
        ),
        continuous_stability=stable_seconds / total_seconds if total_seconds else 0,
        observed_seconds=total_seconds,
        evaluated_cases=len(cases),
    )
