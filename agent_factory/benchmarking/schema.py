from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


BenchmarkRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
BenchmarkSampleStatus = Literal["completed", "failed"]
BenchmarkRunKind = Literal["performance", "concurrency", "operator_analysis"]
BenchmarkImplementationId = Literal["official", "amd"]
BenchmarkExperimentGroupStatus = BenchmarkRunStatus
BenchmarkPromptCacheMode = Literal["legacy", "cold", "warm"]


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class BenchmarkImplementation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    revision: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label", "revision")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return str(value or "").strip()


class BenchmarkOperatorAnalysisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefill_tokens: int = Field(default=512, ge=32, le=32768)
    decode_tokens: int = Field(default=128, ge=1, le=4096)
    repetitions: int = Field(default=3, ge=1, le=20)
    top_kernels: int = Field(default=20, ge=5, le=100)


class BenchmarkConcurrencySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrent_requests: int = Field(default=1, ge=1, le=128)
    requests_per_worker: int = Field(default=2, ge=1, le=100)
    warmup_requests_per_worker: int = Field(default=1, ge=0, le=20)


class BenchmarkRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: BenchmarkRunKind = "performance"
    name: str
    profile_id: str
    prompt: str = ""
    max_output_tokens: int = Field(default=256, ge=1, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int = Field(default=42, ge=0)
    warmup_iterations: int = Field(default=1, ge=0, le=10)
    measured_iterations: int = Field(default=3, ge=1, le=50)
    telemetry_interval_ms: int = Field(default=250, ge=100, le=2000)
    prompt_cache_mode: BenchmarkPromptCacheMode = "legacy"
    implementation: BenchmarkImplementation = Field(default_factory=BenchmarkImplementation)
    concurrency: BenchmarkConcurrencySpec | None = None
    operator_analysis: BenchmarkOperatorAnalysisSpec | None = None

    @field_validator("name", "profile_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("prompt")
    @classmethod
    def _trim_prompt(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _validate_kind_configuration(self) -> "BenchmarkRunSpec":
        if self.kind == "performance":
            if not self.prompt:
                raise ValueError("performance benchmark prompt must not be empty")
            if self.operator_analysis is not None:
                raise ValueError("performance benchmark does not accept operator_analysis settings")
            if self.concurrency is not None:
                raise ValueError("performance benchmark does not accept concurrency settings")
        elif self.kind == "concurrency":
            if not self.prompt:
                raise ValueError("concurrency benchmark prompt must not be empty")
            if self.concurrency is None:
                raise ValueError("concurrency benchmark settings are required")
            if self.operator_analysis is not None:
                raise ValueError("concurrency benchmark does not accept operator_analysis settings")
        elif self.operator_analysis is None:
            raise ValueError("operator analysis settings are required")
        elif self.concurrency is not None:
            raise ValueError("operator analysis does not accept concurrency settings")
        return self


class BenchmarkExperimentGroupSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    profile_id: str
    prompt: str
    repetitions: int = Field(default=3, ge=1, le=20)
    max_output_tokens: int = Field(default=256, ge=1, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int = Field(default=42, ge=0)
    warmup_iterations: int = Field(default=1, ge=0, le=10)
    measured_iterations: int = Field(default=3, ge=1, le=50)
    telemetry_interval_ms: int = Field(default=250, ge=100, le=2000)
    prompt_cache_mode: BenchmarkPromptCacheMode = "legacy"
    concurrency: BenchmarkConcurrencySpec = Field(default_factory=BenchmarkConcurrencySpec)
    operator_analysis: BenchmarkOperatorAnalysisSpec = Field(
        default_factory=BenchmarkOperatorAnalysisSpec
    )

    @field_validator("name", "profile_id", "prompt")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text


class BenchmarkExperimentRunRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    repetition_index: int = Field(ge=0)
    implementation: BenchmarkImplementationId
    kind: BenchmarkRunKind


class BenchmarkTelemetryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elapsed_ms: float = Field(ge=0)
    used_memory_bytes: int | None = Field(default=None, ge=0)
    gpu_utilization_percent: float | None = None
    memory_activity_percent: float | None = None
    power_watts: float | None = None
    temperature_celsius: float | None = None


class BenchmarkSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_index: int = Field(ge=0)
    warmup: bool = False
    status: BenchmarkSampleStatus = "completed"
    started_at: str = Field(default_factory=utc_now_text)
    ttft_ms: float | None = Field(default=None, ge=0)
    request_to_headers_ms: float | None = Field(default=None, ge=0)
    first_event_ms: float | None = Field(default=None, ge=0)
    model_compute_ttft_ms: float | None = Field(default=None, ge=0)
    first_token_decode_ms: float | None = Field(default=None, ge=0)
    outside_model_compute_ms: float | None = Field(default=None, ge=0)
    end_to_end_ms: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cache_tokens: int | None = Field(default=None, ge=0)
    prompt_ms: float | None = Field(default=None, ge=0)
    decode_ms: float | None = Field(default=None, ge=0)
    prompt_tokens_per_second: float | None = Field(default=None, ge=0)
    decode_tokens_per_second: float | None = Field(default=None, ge=0)
    draft_tokens: int | None = Field(default=None, ge=0)
    accepted_draft_tokens: int | None = Field(default=None, ge=0)
    draft_acceptance_rate_percent: float | None = Field(default=None, ge=0, le=100)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    average_gpu_utilization_percent: float | None = None
    peak_gpu_utilization_percent: float | None = None
    average_power_watts: float | None = None
    peak_power_watts: float | None = None
    peak_temperature_celsius: float | None = None
    output_text: str = ""
    finish_reason: str = ""
    telemetry: list[BenchmarkTelemetryPoint] = Field(default_factory=list)
    error: str = ""


class BenchmarkMetricStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1)
    mean: float
    minimum: float
    maximum: float
    p50: float
    p95: float
    standard_deviation: float = Field(ge=0)


class BenchmarkPromptCacheSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_version: Literal["legacy", "prompt_prefix_reuse.v1"] = "legacy"
    prompt_tokens: int = Field(ge=0)
    cached_tokens: int = Field(ge=0)
    processed_tokens: int = Field(ge=0)
    hit_rate_percent: float = Field(ge=0, le=100)


class BenchmarkSpeculativeDecodingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_tokens: int = Field(ge=0)
    accepted_draft_tokens: int = Field(ge=0)
    acceptance_rate_percent: float = Field(ge=0, le=100)


class BenchmarkConcurrencyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrent_requests: int = Field(ge=1)
    request_count: int = Field(ge=1)
    successful_requests: int = Field(ge=0)
    error_rate_percent: float = Field(ge=0, le=100)
    elapsed_seconds: float = Field(gt=0)
    requests_per_second: float = Field(ge=0)
    input_tokens_per_second: float = Field(ge=0)
    output_tokens_per_second: float = Field(ge=0)
    request_latency_ms: BenchmarkMetricStats | None = None
    ttft_ms: BenchmarkMetricStats | None = None


class BenchmarkOperatorKernelStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str = ""
    family: str = ""
    descriptions: dict[str, str] = Field(default_factory=dict)
    variants: list[str] = Field(default_factory=list)
    variant_count: int = Field(default=0, ge=0)
    calls: int = Field(ge=0)
    total_duration_ns: float = Field(ge=0)
    average_duration_ns: float = Field(ge=0)
    duration_percent: float = Field(ge=0, le=100)


class BenchmarkOperatorGraphStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    backend: str
    count: int = Field(ge=1)


class BenchmarkCustomKernelStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kernel_id: str
    display_name: str = ""
    family: str = ""
    descriptions: dict[str, str] = Field(default_factory=dict)
    selected_count: int = Field(ge=0)
    dispatch_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    fallback_reasons: dict[str, int] = Field(default_factory=dict)


class BenchmarkOperatorDispatchVariantStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["mmvq", "mmq"]
    weight_type: str
    m: int = Field(ge=1)
    n: int = Field(ge=1)
    k: int = Field(ge=1)
    has_ids: bool = False
    has_fusion: bool = False
    experts: int = Field(default=0, ge=0)
    active_experts: int = Field(default=0, ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    calls: int = Field(ge=1)
    total_duration_ns: float = Field(ge=0)
    average_duration_ns: float = Field(ge=0)
    duration_percent: float = Field(ge=0, le=100)


class BenchmarkOperatorPhaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["prefill", "decode"]
    elapsed_seconds: float = Field(ge=0)
    benchmark_rows: list[dict[str, Any]] = Field(default_factory=list)
    top_kernels: list[BenchmarkOperatorKernelStat] = Field(default_factory=list)
    graph_operators: list[BenchmarkOperatorGraphStat] = Field(default_factory=list)
    custom_kernels: list[BenchmarkCustomKernelStat] = Field(default_factory=list)
    dispatch_variants: list[BenchmarkOperatorDispatchVariantStat] = Field(default_factory=list)
    artifact_directory: str = ""
    warnings: list[str] = Field(default_factory=list)


class BenchmarkOperatorAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiler: str
    gpu_graphs_disabled_for_attribution: bool = False
    runtime_was_paused: bool = False
    runtime_restored: bool = False
    phases: list[BenchmarkOperatorPhaseResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BenchmarkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measured_samples: int = Field(ge=0)
    successful_samples: int = Field(ge=0)
    ttft_ms: BenchmarkMetricStats | None = None
    request_to_headers_ms: BenchmarkMetricStats | None = None
    first_event_ms: BenchmarkMetricStats | None = None
    model_compute_ttft_ms: BenchmarkMetricStats | None = None
    first_token_decode_ms: BenchmarkMetricStats | None = None
    outside_model_compute_ms: BenchmarkMetricStats | None = None
    end_to_end_ms: BenchmarkMetricStats | None = None
    prompt_ms: BenchmarkMetricStats | None = None
    decode_ms: BenchmarkMetricStats | None = None
    prompt_tokens_per_second: BenchmarkMetricStats | None = None
    decode_tokens_per_second: BenchmarkMetricStats | None = None
    peak_vram_bytes: BenchmarkMetricStats | None = None
    average_gpu_utilization_percent: BenchmarkMetricStats | None = None
    peak_gpu_utilization_percent: BenchmarkMetricStats | None = None
    average_power_watts: BenchmarkMetricStats | None = None
    peak_power_watts: BenchmarkMetricStats | None = None
    prompt_cache: BenchmarkPromptCacheSummary | None = None
    speculative_decoding: BenchmarkSpeculativeDecodingSummary | None = None


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: BenchmarkRunStatus = "queued"
    spec: BenchmarkRunSpec
    progress_completed: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    environment: dict[str, Any] = Field(default_factory=dict)
    samples: list[BenchmarkSample] = Field(default_factory=list)
    summary: BenchmarkSummary | None = None
    concurrency: BenchmarkConcurrencyResult | None = None
    operator_analysis: BenchmarkOperatorAnalysisResult | None = None
    error: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = Field(default_factory=utc_now_text)


class BenchmarkExperimentGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    status: BenchmarkExperimentGroupStatus = "queued"
    spec: BenchmarkExperimentGroupSpec
    runs: list[BenchmarkExperimentRunRef] = Field(default_factory=list)
    progress_completed: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    initial_implementation: BenchmarkImplementationId | None = None
    active_implementation: BenchmarkImplementationId | None = None
    error: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = Field(default_factory=utc_now_text)
