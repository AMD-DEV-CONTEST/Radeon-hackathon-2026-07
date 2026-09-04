from __future__ import annotations

import hashlib
import json
import math
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from policyseal.agent.classification_graph import SemanticClassificationGraph
from policyseal.agent.llm_client import CompletionClient
from policyseal.agent.schemas import ClassificationOutcome, LocalCompletion, SemanticRegionInput
from policyseal.domain.enums import ContentCategory, FileKind
from policyseal.domain.models import DocumentRegion
from policyseal.evals.assets import RiskLevel, SemanticSnippet


class BenchmarkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelParameters(BenchmarkModel):
    dtype: str
    attention_backend: str
    max_model_len: int = Field(gt=0)
    max_num_seqs: int = Field(gt=0)
    max_num_batched_tokens: int = Field(gt=0)
    gpu_memory_utilization: float = Field(gt=0, le=1)
    thinking: bool


class RuntimeEvidence(BenchmarkModel):
    platform: str
    python: str
    rocm: str
    hip: str
    gpu_architecture: str
    gpu_name: str
    gpu_vram_bytes: int = Field(gt=0)
    torch: str
    vllm: str
    transformers: str
    model: str
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_files: dict[str, str]
    model_parameters: ModelParameters
    model_server_cold_start_ms: float = Field(ge=0)
    endpoint_scope: Literal["localhost"]


class WorkloadEvidence(BenchmarkModel):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: int = Field(gt=0)
    warm_repetitions: int = Field(ge=10)
    consistency_passes: int = Field(ge=2)


class StrategyConfiguration(BenchmarkModel):
    batch_size: int = Field(gt=0)
    consistency_passes: int = Field(ge=2)
    deterministic_short_circuit: bool


class WarmRun(BenchmarkModel):
    iteration: int = Field(gt=0)
    latency_ms: float = Field(gt=0)
    model_latency_ms: float = Field(ge=0)
    throughput_regions_per_second: float = Field(gt=0)
    model_region_count: int = Field(ge=0)
    model_request_count: int = Field(ge=0)
    gpu_utilization_percent_mean: float = Field(ge=0, le=100)
    gpu_utilization_percent_peak: float = Field(ge=0, le=100)
    vram_used_bytes_peak: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class StrategySummary(BenchmarkModel):
    p50_latency_ms: float = Field(gt=0)
    p95_latency_ms: float = Field(gt=0)
    throughput_regions_per_second: float = Field(gt=0)
    model_region_count_total: int = Field(ge=0)
    model_request_count_total: int = Field(ge=0)
    gpu_utilization_percent_mean: float = Field(ge=0, le=100)
    gpu_utilization_percent_peak: float = Field(ge=0, le=100)
    vram_used_bytes_peak: int = Field(ge=0)
    prompt_tokens_total: int = Field(ge=0)
    completion_tokens_total: int = Field(ge=0)
    deterministic_output: bool


class QualityEvidence(BenchmarkModel):
    macro_f1: float = Field(ge=0, le=1)
    accuracy: float = Field(ge=0, le=1)
    leakage_count: int = Field(ge=0)
    over_removal_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    high_risk_to_ordinary_false_negative_count: int = Field(ge=0)
    gate_passed: bool


class StrategyReport(BenchmarkModel):
    strategy_id: str
    configuration: StrategyConfiguration
    cold_workflow_latency_ms: float = Field(gt=0)
    warm_runs: tuple[WarmRun, ...] = Field(min_length=10)
    summary: StrategySummary
    quality: QualityEvidence


class ExperimentReport(BenchmarkModel):
    experiment_id: Literal["experiment-a-batching", "experiment-b-cascade"]
    title: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: int = Field(gt=0)
    baseline_strategy_id: str
    optimized_strategy_id: str
    target_metric: str
    target_improvement_percent: float = Field(gt=0)
    actual_improvement_percent: float
    target_status: Literal["met", "not_met"]
    result_reason: str
    strategies: tuple[StrategyReport, StrategyReport]

    @model_validator(mode="after")
    def validate_strategy_pair(self) -> ExperimentReport:
        strategy_ids = {item.strategy_id for item in self.strategies}
        if strategy_ids != {self.baseline_strategy_id, self.optimized_strategy_id}:
            raise ValueError("experiment strategy IDs do not match the declared pair")
        return self


class BenchmarkReport(BenchmarkModel):
    schema_version: Literal[1]
    recorded_at: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime: RuntimeEvidence
    workload: WorkloadEvidence
    experiments: tuple[ExperimentReport, ExperimentReport]

    @model_validator(mode="after")
    def validate_experiment_pair(self) -> BenchmarkReport:
        experiment_ids = {item.experiment_id for item in self.experiments}
        if experiment_ids != {"experiment-a-batching", "experiment-b-cascade"}:
            raise ValueError("the Radeon report must contain both approved experiments")
        if any(
            len(item.warm_runs) != self.workload.warm_repetitions
            for experiment in self.experiments
            for item in experiment.strategies
        ):
            raise ValueError("every strategy must use the declared warm repetition count")
        return self


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    snippet: SemanticSnippet
    deterministic: bool


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    batch_size: int
    deterministic_short_circuit: bool


@dataclass(slots=True)
class RecordingClient(CompletionClient):
    client: CompletionClient
    completions: list[LocalCompletion] = field(default_factory=list)

    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion:
        completion = self.client.complete(regions)
        self.completions.append(completion)
        return completion


@dataclass(frozen=True, slots=True)
class _GpuSample:
    utilization_percent: float
    vram_used_bytes: int


class RadeonSampler:
    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[_GpuSample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> RadeonSampler:
        self._thread = threading.Thread(target=self._collect, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sample()

    def _collect(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval_seconds)

    def _sample(self) -> None:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showuse", "--showmeminfo", "vram", "--json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            payload = json.loads(result.stdout)
            card = payload[sorted(payload)[0]]
            self.samples.append(
                _GpuSample(
                    utilization_percent=float(card["GPU use (%)"]),
                    vram_used_bytes=int(card["VRAM Total Used Memory (B)"]),
                )
            )
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError):
            return


@dataclass(frozen=True, slots=True)
class _ObservedRun:
    report: WarmRun
    outcomes: tuple[ClassificationOutcome, ...]


LOW_RISK_CATEGORIES = {
    ContentCategory.GENERAL_BUSINESS,
    ContentCategory.ORGANIZATIONAL_ROLE,
    ContentCategory.RELATIVE_PERFORMANCE_TERM,
    ContentCategory.STANDARD_LEGAL_TERM,
}


def percentile(values: list[float], requested: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(requested * len(ordered)) - 1)
    return ordered[index]


def macro_f1(
    expected: tuple[ContentCategory, ...],
    predicted: tuple[ContentCategory | None, ...],
) -> float:
    scores: list[float] = []
    for label in sorted(set(expected), key=lambda item: item.value):
        true_positive = sum(
            expected_item is label and predicted_item is label
            for expected_item, predicted_item in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            expected_item is not label and predicted_item is label
            for expected_item, predicted_item in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            expected_item is label and predicted_item is not label
            for expected_item, predicted_item in zip(expected, predicted, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0 if denominator == 0 else 2 * true_positive / denominator)
    return sum(scores) / len(scores)


def benchmark_input_sha256(cases: tuple[BenchmarkCase, ...]) -> str:
    payload = [
        {
            "id": case.snippet.id,
            "text_sha256": hashlib.sha256(case.snippet.text.encode("utf-8")).hexdigest(),
            "expected": case.snippet.expected_category.value,
            "risk": case.snippet.risk.value,
            "scenario": case.snippet.scenario,
            "deterministic": case.deterministic,
        }
        for case in cases
    ]
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _file_kind(scenario: str) -> FileKind:
    return {"xlsx": FileKind.XLSX, "docx": FileKind.DOCX, "pdf": FileKind.PDF}[scenario]


def _regions(
    cases: tuple[BenchmarkCase, ...],
    *,
    deterministic_short_circuit: bool,
) -> tuple[DocumentRegion, ...]:
    return tuple(
        DocumentRegion(
            id=case.snippet.id,
            file_kind=_file_kind(case.snippet.scenario),
            location=f"benchmark:{case.snippet.scenario}:{case.snippet.id}",
            order=index,
            text=case.snippet.text,
            category=(
                case.snippet.expected_category
                if deterministic_short_circuit and case.deterministic
                else ContentCategory.UNCLASSIFIED
            ),
        )
        for index, case in enumerate(cases)
    )


def _output_sha256(outcomes: tuple[ClassificationOutcome, ...]) -> str:
    payload = [
        {
            "id": outcome.region_id,
            "category": outcome.category.value if outcome.category is not None else None,
            "evidence_ids": outcome.evidence_ids,
            "requires_human_review": outcome.requires_human_review,
            "reason_code": outcome.reason_code,
        }
        for outcome in outcomes
    ]
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _execute(
    graph: SemanticClassificationGraph,
    recording: RecordingClient,
    regions: tuple[DocumentRegion, ...],
    iteration: int,
) -> _ObservedRun:
    request_start = len(recording.completions)
    started = time.perf_counter()
    with RadeonSampler() as sampler:
        result = graph.run(regions)
    latency_ms = (time.perf_counter() - started) * 1_000
    samples = sampler.samples
    utilization = [item.utilization_percent for item in samples]
    peak_vram = max((item.vram_used_bytes for item in samples), default=0)
    report = WarmRun(
        iteration=iteration,
        latency_ms=round(latency_ms, 6),
        model_latency_ms=round(result.latency_ms, 6),
        throughput_regions_per_second=round(len(regions) / (latency_ms / 1_000), 6),
        model_region_count=sum(item.model_assisted for item in result.outcomes),
        model_request_count=len(recording.completions) - request_start,
        gpu_utilization_percent_mean=round(sum(utilization) / len(utilization), 6)
        if utilization
        else 0,
        gpu_utilization_percent_peak=max(utilization, default=0),
        vram_used_bytes_peak=peak_vram,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        output_sha256=_output_sha256(result.outcomes),
    )
    return _ObservedRun(report, result.outcomes)


def _quality(
    cases: tuple[BenchmarkCase, ...],
    outcomes: tuple[ClassificationOutcome, ...],
) -> QualityEvidence:
    expected = tuple(case.snippet.expected_category for case in cases)
    predicted = tuple(outcome.category for outcome in outcomes)
    exact = sum(
        expected_item is predicted_item
        for expected_item, predicted_item in zip(expected, predicted, strict=True)
    )
    high_risk_to_ordinary = sum(
        case.snippet.risk is RiskLevel.HIGH
        and outcome.category in LOW_RISK_CATEGORIES
        and not outcome.requires_human_review
        for case, outcome in zip(cases, outcomes, strict=True)
    )
    over_removal = sum(
        case.snippet.risk is RiskLevel.LOW
        and (
            outcome.requires_human_review or outcome.category is not case.snippet.expected_category
        )
        for case, outcome in zip(cases, outcomes, strict=True)
    )
    score = macro_f1(expected, predicted)
    return QualityEvidence(
        macro_f1=round(score, 6),
        accuracy=round(exact / len(expected), 6),
        leakage_count=high_risk_to_ordinary,
        over_removal_count=over_removal,
        review_count=sum(outcome.requires_human_review for outcome in outcomes),
        high_risk_to_ordinary_false_negative_count=high_risk_to_ordinary,
        gate_passed=score >= 0.9 and high_risk_to_ordinary == 0,
    )


def run_strategy(
    definition: StrategyDefinition,
    cases: tuple[BenchmarkCase, ...],
    client: CompletionClient,
    *,
    warm_repetitions: int,
    consistency_passes: int,
) -> StrategyReport:
    if warm_repetitions < 10:
        raise ValueError("Radeon benchmark strategies require at least ten warm repetitions")
    regions = _regions(
        cases,
        deterministic_short_circuit=definition.deterministic_short_circuit,
    )
    recording = RecordingClient(client)
    graph = SemanticClassificationGraph(
        recording,
        batch_size=definition.batch_size,
        consistency_passes=consistency_passes,
    )
    cold = _execute(graph, recording, regions, 1)
    observed = tuple(
        _execute(graph, recording, regions, iteration)
        for iteration in range(1, warm_repetitions + 1)
    )
    runs = tuple(item.report for item in observed)
    latency_values = [item.latency_ms for item in runs]
    utilization_values = [item.gpu_utilization_percent_mean for item in runs]
    output_hashes = {item.output_sha256 for item in runs}
    summary = StrategySummary(
        p50_latency_ms=round(percentile(latency_values, 0.5), 6),
        p95_latency_ms=round(percentile(latency_values, 0.95), 6),
        throughput_regions_per_second=round(
            len(cases) * len(runs) / (sum(latency_values) / 1_000), 6
        ),
        model_region_count_total=sum(item.model_region_count for item in runs),
        model_request_count_total=sum(item.model_request_count for item in runs),
        gpu_utilization_percent_mean=round(sum(utilization_values) / len(utilization_values), 6),
        gpu_utilization_percent_peak=max(
            (item.gpu_utilization_percent_peak for item in runs), default=0
        ),
        vram_used_bytes_peak=max((item.vram_used_bytes_peak for item in runs), default=0),
        prompt_tokens_total=sum(item.prompt_tokens for item in runs),
        completion_tokens_total=sum(item.completion_tokens for item in runs),
        deterministic_output=len(output_hashes) == 1,
    )
    quality = _quality(cases, observed[0].outcomes)
    return StrategyReport(
        strategy_id=definition.strategy_id,
        configuration=StrategyConfiguration(
            batch_size=definition.batch_size,
            consistency_passes=consistency_passes,
            deterministic_short_circuit=definition.deterministic_short_circuit,
        ),
        cold_workflow_latency_ms=cold.report.latency_ms,
        warm_runs=runs,
        summary=summary,
        quality=quality,
    )


def improvement_percent(baseline: float, optimized: float) -> float:
    if baseline <= 0:
        raise ValueError("baseline must be positive")
    return round((baseline - optimized) / baseline * 100, 6)


__all__ = [
    "BenchmarkCase",
    "BenchmarkReport",
    "ExperimentReport",
    "ModelParameters",
    "RuntimeEvidence",
    "StrategyDefinition",
    "WorkloadEvidence",
    "benchmark_input_sha256",
    "improvement_percent",
    "run_strategy",
]
