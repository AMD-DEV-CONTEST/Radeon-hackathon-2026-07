"""Typed YAML and environment configuration."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

from buildguard.exceptions import ConfigurationError


class AppConfig(BaseModel):
    """General application settings."""

    name: str = "BuildGuard-Radeon"
    environment: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    seed: int = 42
    data_dir: Path = Path("data")
    workspace_dir: Path = Path("workspace")
    database_path: Path = Path("workspace/database/buildguard.db")
    retention: RetentionConfig = Field(default_factory=lambda: RetentionConfig())
    agent: AgentConfig = Field(default_factory=lambda: AgentConfig())
    tools: ToolsConfig = Field(default_factory=lambda: ToolsConfig())


class RetentionConfig(BaseModel):
    """Age-based local artifact retention settings."""

    enabled: bool = False
    event_images_days: int = Field(default=30, ge=0)
    event_clips_days: int = Field(default=30, ge=0)
    normal_frames_days: int = Field(default=7, ge=0)
    performance_logs_days: int = Field(default=30, ge=0)
    audit_logs_days: int = Field(default=90, ge=0)
    interval_seconds: float = Field(default=3600, gt=0, le=604_800)


class AgentConfig(BaseModel):
    """Agent graph safety limits and tool allowlists."""

    max_plan_steps: int = Field(default=6, ge=1, le=20)
    max_replans: int = Field(default=1, ge=0, le=5)
    registered_tools: list[str] = Field(
        default_factory=lambda: ["echo", "inspect_image", "search_memory"]
    )
    confirmation_tools: list[str] = Field(default_factory=lambda: ["inspect_image"])


class ToolsConfig(BaseModel):
    """Built-in tool resource bounds."""

    inspection_image_max_items: int = Field(default=100, ge=1, le=100_000)
    default_timeout_seconds: float = Field(default=10, gt=0, le=300)


class GenerationProfile(BaseModel):
    """One named, auditable local generation policy."""

    thinking: bool = False
    temperature: float = Field(ge=0, le=2)
    top_p: float = Field(gt=0, le=1)
    max_tokens: int = Field(gt=0, le=8192)


class GenerationProfiles(BaseModel):
    """Profiles used by planning, dialogue, verification, and replanning."""

    structured_plan: GenerationProfile = Field(
        default_factory=lambda: GenerationProfile(
            thinking=False, temperature=0.2, top_p=0.8, max_tokens=768
        )
    )
    normal_dialogue: GenerationProfile = Field(
        default_factory=lambda: GenerationProfile(
            thinking=False, temperature=0.7, top_p=0.8, max_tokens=1024
        )
    )
    complex_replan: GenerationProfile = Field(
        default_factory=lambda: GenerationProfile(
            thinking=True, temperature=0.6, top_p=0.95, max_tokens=1200
        )
    )


class LLMConfig(BaseModel):
    """Local OpenAI-compatible server settings."""

    mode: Literal["mock", "local"] = "mock"
    endpoint: HttpUrl = HttpUrl("http://127.0.0.1:8080/v1")
    model: str = Field(default="local-model", min_length=1)
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "::1"])
    max_tokens: int = Field(default=64, gt=0, le=8192)
    temperature: float = Field(default=0.0, ge=0, le=2)
    retry_attempts: int = Field(default=2, ge=1, le=5)
    retry_wait_seconds: float = Field(default=0.1, ge=0, le=10)
    stream_complete_responses: bool = False
    cache_prompt: bool = True
    estimated_memory_mb: float = Field(default=0, ge=0)
    generation_profiles: GenerationProfiles = Field(default_factory=GenerationProfiles)

    @field_validator("allowed_hosts")
    @classmethod
    def hosts_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("allowed_hosts must contain at least one host")
        for host in value:
            if host.lower() == "localhost":
                continue
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
            if is_loopback:
                continue
            raise ValueError("allowed_hosts may contain only localhost or loopback addresses")
        return value


class AdvancedSecurityConfig(BaseModel):
    """CaMeL-inspired control/data isolation and capability limits."""

    enabled: bool = True
    require_capabilities: bool = True
    capability_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    capability_max_uses: int = Field(default=1, ge=1, le=10_000)


class PermissionConfig(BaseModel):
    """Network and audit policy."""

    allow_network: bool = False
    allow_lan_llm: bool = False
    allowed_lan_cidrs: list[str] = Field(default_factory=list)
    audit_enabled: bool = True
    confirmation_ttl_seconds: int = Field(default=300, ge=10, le=3600)
    tool_retry_attempts: int = Field(default=2, ge=1, le=5)
    tool_retry_wait_seconds: float = Field(default=0.05, ge=0, le=10)
    advanced: AdvancedSecurityConfig = Field(default_factory=AdvancedSecurityConfig)


class GpuSchedulerConfig(BaseModel):
    """Resource-aware local GPU scheduling policy."""

    max_concurrent_inference: int = Field(default=1, ge=1, le=64)
    max_gpu_utilization_percent: float = Field(default=95, ge=0, le=100)
    reserved_vram_mb: float = Field(default=512, ge=0, le=131_072)
    oom_batch_reduction_factor: float = Field(default=0.5, gt=0, lt=1)
    allow_cpu_fallback: bool = True
    task_priorities: dict[str, int] = Field(
        default_factory=lambda: {
            "emergency_vision": 1,
            "risk_confirmation": 2,
            "normal_monitoring": 3,
            "agent_response": 4,
            "report_generation": 5,
            "background_indexing": 6,
        }
    )

    @field_validator("task_priorities")
    @classmethod
    def validate_priorities(cls, value: dict[str, int]) -> dict[str, int]:
        required = {
            "emergency_vision",
            "risk_confirmation",
            "normal_monitoring",
            "agent_response",
            "report_generation",
            "background_indexing",
        }
        if set(value) != required:
            raise ValueError(f"task_priorities must contain exactly {sorted(required)}")
        if any(priority < 1 for priority in value.values()):
            raise ValueError("GPU task priorities must be positive")
        return value


class MonitoringConfig(BaseModel):
    """Hardware sampling settings."""

    enabled: bool = True
    sample_interval_seconds: float = Field(default=1.0, gt=0, le=3600)
    command_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    output_path: Path = Path("data/hardware.jsonl")
    dashboard_log_path: Path = Path("workspace/logs/performance/dashboard.jsonl")
    export_dir: Path = Path("workspace/logs/performance/exports")
    dashboard_history_size: int = Field(default=1000, ge=10, le=100_000)
    scheduler: GpuSchedulerConfig = Field(default_factory=GpuSchedulerConfig)


class AdvancedRagConfig(BaseModel):
    """Retrieval gating, correction, grounding, and quality policy."""

    enabled: bool = True
    use_llm_gate: bool = True
    use_llm_rewriter: bool = True
    required_retrieval_terms: list[str] = Field(
        default_factory=lambda: ["规范", "条款", "依据", "历史", "风险等级"]
    )
    professional_term_mappings: dict[str, str] = Field(
        default_factory=lambda: {
            "安全帽": "个体防护装备 安全帽",
            "临边": "临边作业 防护栏杆",
            "漏电": "剩余电流动作保护器 漏电保护",
        }
    )
    entity_terms: list[str] = Field(
        default_factory=lambda: [
            "安全帽",
            "临边",
            "洞口",
            "脚手架",
            "配电箱",
            "漏电保护",
            "高处作业",
        ]
    )
    quality_generate_threshold: float = Field(default=0.75, ge=0, le=1)
    quality_correct_threshold: float = Field(default=0.45, ge=0, le=1)
    initial_top_k: int = Field(default=5, ge=1, le=50)
    corrective_top_k: int = Field(default=15, ge=1, le=50)
    max_corrections: int = Field(default=1, ge=0, le=1)
    initial_bm25_weight: float = Field(default=1.0, ge=0)
    initial_dense_weight: float = Field(default=1.0, ge=0)
    corrective_bm25_weight: float = Field(default=1.25, ge=0)
    corrective_dense_weight: float = Field(default=0.75, ge=0)
    grounding_min_coverage: float = Field(default=0.25, ge=0, le=1)
    refusal_message: str = Field(
        default="现有本地检索证据不足，无法安全回答该问题。",
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_advanced_rag(self) -> AdvancedRagConfig:
        if self.quality_correct_threshold >= self.quality_generate_threshold:
            raise ValueError(
                "quality_correct_threshold must be below quality_generate_threshold"
            )
        if self.corrective_top_k < self.initial_top_k:
            raise ValueError("corrective_top_k must not be smaller than initial_top_k")
        if self.initial_bm25_weight + self.initial_dense_weight <= 0:
            raise ValueError("initial retrieval weights must include a positive value")
        if self.corrective_bm25_weight + self.corrective_dense_weight <= 0:
            raise ValueError("corrective retrieval weights must include a positive value")
        return self


class RagConfig(BaseModel):
    """Local hybrid retrieval configuration."""

    embedding_mode: Literal["mock", "transformers"] = "mock"
    embedding_local_files_only: bool = True
    embedding_model_path: Path | None = None
    embedding_manifest_path: Path | None = None
    embedding_device: str = "cpu"
    embedding_estimated_memory_mb: float = Field(default=0, ge=0)
    embedding_batch_size: int = Field(default=16, ge=1, le=512)
    embedding_dimension: int = Field(default=128, ge=8, le=8192)
    embedding_model_revision: str = "unreported"
    embedding_tokenizer_revision: str = "unreported"
    embedding_model_sha256: str = "unreported"
    embedding_query_instruction: str = "Represent this query for retrieval:"
    embedding_query_instruction_version: str = "v1"
    embedding_pooling: Literal["last_token"] = "last_token"
    embedding_normalize: bool = True
    reranker_mode: Literal["mock", "transformers"] = "mock"
    reranker_local_files_only: bool = True
    reranker_model_path: Path | None = None
    reranker_manifest_path: Path | None = None
    reranker_architecture: Literal["cross_encoder", "causal_yes_no"] = "cross_encoder"
    reranker_device: str = "cpu"
    reranker_estimated_memory_mb: float = Field(default=0, ge=0)
    reranker_batch_size: int = Field(default=8, ge=1, le=256)
    reranker_model_revision: str = "unreported"
    reranker_model_sha256: str = "unreported"
    reranker_enabled: bool = True
    index_dir: Path = Path("workspace/indexes/construction_standards")
    allowed_source_roots: list[Path] = Field(
        default_factory=lambda: [Path("workspace/knowledge")]
    )
    chunk_min_chars: int = Field(default=300, ge=50, le=2000)
    chunk_max_chars: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_chars: int = Field(default=60, ge=0, le=500)
    chunker_version: str = "structure-aware-v1"
    bm25_top_k: int = Field(default=20, ge=1, le=200)
    dense_top_k: int = Field(default=20, ge=1, le=200)
    fusion_top_k: int = Field(default=15, ge=1, le=100)
    final_top_k: int = Field(default=5, ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    min_top_score: float = Field(default=0.1, ge=0, le=1)
    min_keyword_coverage: float = Field(default=0.15, ge=0, le=1)
    advanced: AdvancedRagConfig = Field(default_factory=AdvancedRagConfig)

    @model_validator(mode="after")
    def validate_rag(self) -> RagConfig:
        if self.chunk_min_chars > self.chunk_max_chars:
            raise ValueError("chunk_min_chars must not exceed chunk_max_chars")
        if self.chunk_overlap_chars >= self.chunk_min_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_min_chars")
        if self.embedding_mode == "transformers" and self.embedding_model_path is None:
            raise ValueError("embedding_model_path is required for transformers mode")
        if (
            self.reranker_enabled
            and self.reranker_mode == "transformers"
            and self.reranker_model_path is None
        ):
            raise ValueError("reranker_model_path is required for transformers mode")
        return self


class VisionModelConfig(BaseModel):
    """One configured visual detector."""

    model_name: str = Field(min_length=1, max_length=256)
    backend: Literal["mock", "local", "http"]
    local_adapter: Literal["generic", "rtdetr_v2", "yolo11"] = "generic"
    model_path: Path | None = None
    model_config_path: Path | None = None
    model_manifest_path: Path | None = None
    model_revision: str | None = None
    model_sha256: str | None = None
    class_mapping: dict[int, str] = Field(default_factory=dict)
    yolo_class_mapping: dict[str, str] = Field(default_factory=dict)
    batch_size: int = Field(default=4, ge=1, le=256)
    endpoint: HttpUrl | None = None
    applicable_roi_types: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    defect_classes: list[str] = Field(min_length=1)
    input_size: tuple[int, int] = (640, 640)
    confidence_threshold: float = Field(default=0.35, ge=0, le=1)
    nms_iou: float = Field(default=0.5, gt=0, le=1)
    device: str = Field(default="cpu", min_length=1)
    estimated_latency_ms: float = Field(default=0, ge=0)
    estimated_memory_mb: float = Field(default=0, ge=0)
    reliability: float = Field(default=1.0, ge=0, le=1)
    fixed_call_cost: float = Field(default=0, ge=0)
    high_risk_relevance: float = Field(default=0.5, ge=0, le=1)
    enabled: bool = True

    @field_validator("applicable_roi_types", "defect_classes")
    @classmethod
    def unique_non_empty_labels(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("model labels must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("model labels must be unique")
        return normalized

    @field_validator("input_size")
    @classmethod
    def validate_input_size(cls, value: tuple[int, int]) -> tuple[int, int]:
        if any(item <= 0 for item in value):
            raise ValueError("input_size values must be positive")
        return value

    @model_validator(mode="after")
    def validate_backend_location(self) -> VisionModelConfig:
        if self.backend == "local" and self.model_path is None:
            raise ValueError("model_path is required for local vision backend")
        if self.local_adapter == "rtdetr_v2":
            required = {
                "model_path": self.model_path,
                "model_config_path": self.model_config_path,
                "model_manifest_path": self.model_manifest_path,
                "model_revision": self.model_revision,
                "model_sha256": self.model_sha256,
                "class_mapping": self.class_mapping,
            }
            missing = [name for name, value in required.items() if not value]
            if self.backend != "local":
                raise ValueError("rtdetr_v2 adapter requires the local backend")
            if missing:
                raise ValueError(
                    f"rtdetr_v2 adapter is missing required fields: {missing}"
                )
        if self.local_adapter == "yolo11":
            if self.backend != "local":
                raise ValueError("yolo11 adapter requires the local backend")
            missing = [
                name
                for name, value in {
                    "model_path": self.model_path,
                    "model_sha256": self.model_sha256,
                    "yolo_class_mapping": self.yolo_class_mapping,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    f"yolo11 adapter is missing required fields: {missing}"
                )
        if self.backend == "http" and self.endpoint is None:
            raise ValueError("endpoint is required for HTTP vision backend")
        return self


class VisionRoutingConfig(BaseModel):
    """Recall-guarded cost-aware visual routing policy."""

    enabled: bool = True
    prior_probability: float = Field(default=0.45, gt=0, lt=1)
    model_priors: dict[str, float] = Field(default_factory=dict)
    probability_alpha: float = 2.0
    probability_beta: float = 1.0
    probability_gamma: float = 1.0
    probability_delta: float = Field(default=1.0, ge=0)
    temporal_alpha: float = Field(default=0.6, gt=0, le=1)
    latency_reference_ms: float = Field(default=100, gt=0)
    memory_reference_mb: float = Field(default=1024, gt=0)
    latency_weight: float = Field(default=0.45, ge=0)
    memory_weight: float = Field(default=0.35, ge=0)
    benefit_weight: float = Field(default=1.0, ge=0)
    coverage_weight: float = Field(default=0.35, ge=0)
    cost_weight: float = Field(default=0.35, ge=0)
    call_count_weight: float = Field(default=0.15, ge=0)
    max_models_per_roi: int = Field(default=3, ge=1, le=12)
    roi_budget: float = Field(default=2.0, gt=0)
    min_models_high_risk: int = Field(default=2, ge=1, le=12)
    guard_budget_overrun_ratio: float = Field(default=0.25, ge=0, le=1)
    low_confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    small_roi_area_ratio: float = Field(default=0.02, gt=0, le=1)
    poor_quality_threshold: float = Field(default=0.35, ge=0, le=1)
    top_probability_gap: float = Field(default=0.08, ge=0, le=1)
    rule_high_risk_relevance_threshold: float = Field(default=0.6, ge=0, le=1)
    high_risk_roi_types: list[str] = Field(default_factory=list)

    @field_validator("model_priors")
    @classmethod
    def validate_model_priors(cls, value: dict[str, float]) -> dict[str, float]:
        if any(probability <= 0 or probability >= 1 for probability in value.values()):
            raise ValueError("model prior probabilities must be within (0, 1)")
        return value

    @model_validator(mode="after")
    def validate_routing_limits(self) -> VisionRoutingConfig:
        if self.min_models_high_risk > self.max_models_per_roi:
            raise ValueError("min_models_high_risk must not exceed max_models_per_roi")
        return self


class SemanticPromptSetConfig(BaseModel):
    """Positive/negative prompts used to score one existing specialist model."""

    positive: list[str] = Field(min_length=1, max_length=32)
    negative: list[str] = Field(min_length=1, max_length=32)
    temperature: float = Field(default=0.07, gt=0, le=10)
    bias: float = Field(default=0.0, ge=-2, le=2)

    @field_validator("positive", "negative")
    @classmethod
    def unique_non_empty_prompts(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("semantic routing prompts must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("semantic routing prompts must be unique")
        return normalized

    @model_validator(mode="after")
    def positive_and_negative_must_not_overlap(self) -> SemanticPromptSetConfig:
        overlap = set(self.positive) & set(self.negative)
        if overlap:
            raise ValueError(
                f"semantic positive and negative prompts overlap: {sorted(overlap)}"
            )
        return self


class MobileClip2SemanticRouterConfig(BaseModel):
    """Local MobileCLIP2-S0 semantic scorer used only before specialist routing."""

    enabled: bool = False
    required: bool = False
    resident: bool = True
    model_name: Literal["MobileCLIP2-S0"] = "MobileCLIP2-S0"
    model_path: Path | None = None
    model_revision: str | None = None
    model_sha256: str | None = None
    device: str = Field(default="cpu", min_length=1)
    precision: Literal["fp32", "fp16", "bf16"] = "fp32"
    semantic_weight: float = Field(default=0.7, ge=0, le=1)
    cache_max_items: int = Field(default=128, ge=0, le=10_000)
    estimated_memory_mb: float = Field(default=512, ge=0)
    experts: dict[str, SemanticPromptSetConfig] = Field(default_factory=dict)

    @field_validator("model_sha256")
    @classmethod
    def valid_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("MobileCLIP2 model_sha256 must be 64 lowercase hex characters")
        return normalized

    @model_validator(mode="after")
    def validate_enabled_semantic_router(self) -> MobileClip2SemanticRouterConfig:
        if self.required and not self.enabled:
            raise ValueError("required MobileCLIP2 semantic routing must be enabled")
        if self.enabled:
            missing = [
                name
                for name, value in {
                    "model_path": self.model_path,
                    "model_revision": self.model_revision,
                    "model_sha256": self.model_sha256,
                    "experts": self.experts,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    f"enabled MobileCLIP2 semantic routing is missing: {missing}"
                )
        return self


class OpenVocabularyConfig(BaseModel):
    """Optional local open-vocabulary object localization configuration."""

    enabled: bool = False
    model_name: str = Field(default="grounding-dino-local", min_length=1, max_length=256)
    model_dir: Path | None = None
    device: str = Field(default="cpu", min_length=1)
    prompt_allowlist: list[str] = Field(default_factory=list)
    class_aliases: dict[str, str] = Field(default_factory=dict)
    confidence_threshold: float = Field(default=0.35, ge=0, le=1)
    batch_size: int = Field(default=8, ge=1, le=256)
    unload_after_inference: bool = False

    @field_validator("prompt_allowlist")
    @classmethod
    def unique_prompts(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("open-vocabulary prompts must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("open-vocabulary prompts must be unique")
        return normalized

    @field_validator("class_aliases")
    @classmethod
    def valid_aliases(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {
            alias.strip(): target.strip()
            for alias, target in value.items()
        }
        if any(not alias or not target for alias, target in normalized.items()):
            raise ValueError("open-vocabulary class aliases must not be empty")
        return normalized


class SegmentationConfig(BaseModel):
    """Optional local SAM 2 box-prompt segmentation configuration."""

    enabled: bool = False
    model_name: str = Field(default="sam2-local", min_length=1, max_length=256)
    model_dir: Path | None = None
    device: str = Field(default="cpu", min_length=1)
    output_dir: Path = Path("workspace/events/masks")
    area_required_classes: list[str] = Field(default_factory=list)
    batch_size: int = Field(default=4, ge=1, le=128)
    min_confidence: float = Field(default=0, ge=0, le=1)
    min_stability: float = Field(default=0, ge=0, le=1)
    unload_after_inference: bool = False

    @field_validator("area_required_classes")
    @classmethod
    def unique_area_classes(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("segmentation area classes must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("segmentation area classes must be unique")
        return normalized


class RiskPolicyConfig(BaseModel):
    """Deterministic risk scoring inputs."""

    base_severity: dict[str, float] = Field(default_factory=dict)
    default_severity: float = Field(default=0.5, ge=0, le=1)
    location_top: float = Field(default=0.8, ge=0, le=1)
    location_middle: float = Field(default=0.55, ge=0, le=1)
    location_bottom: float = Field(default=0.35, ge=0, le=1)
    default_evidence_strength: float = Field(default=0.2, ge=0, le=1)
    duration_reference_seconds: float = Field(default=60.0, gt=0, le=86_400)
    frequency_reference_count: int = Field(default=5, ge=1, le=1_000_000)

    @field_validator("base_severity")
    @classmethod
    def validate_severity_values(cls, value: dict[str, float]) -> dict[str, float]:
        if any(score < 0 or score > 1 for score in value.values()):
            raise ValueError("base severity scores must be within 0..1")
        return value


class ImageUploadConfig(BaseModel):
    """Bounded local image upload policy."""

    max_files: int = Field(default=20, ge=1, le=1000)
    max_file_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_total_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    chunk_bytes: int = Field(default=1024 * 1024, ge=4096, le=8 * 1024 * 1024)
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [".jpg", ".jpeg", ".png"]
    )
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: ["image/jpeg", "image/png"]
    )

    @model_validator(mode="after")
    def validate_limits(self) -> ImageUploadConfig:
        if self.max_total_bytes < self.max_file_bytes:
            raise ValueError("max_total_bytes must be at least max_file_bytes")
        if any(not item.startswith(".") for item in self.allowed_extensions):
            raise ValueError("upload extensions must begin with a dot")
        return self


class VideoUploadConfig(BaseModel):
    """Bounded local video upload policy for Agent video inspection."""

    max_files: int = Field(default=1, ge=1, le=20)
    max_file_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    max_total_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    chunk_bytes: int = Field(default=1024 * 1024, ge=4096, le=8 * 1024 * 1024)
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [".mp4", ".avi", ".mov", ".mkv"]
    )
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "video/mp4",
            "video/x-msvideo",
            "video/quicktime",
            "video/x-matroska",
            "application/octet-stream",
        ]
    )

    @model_validator(mode="after")
    def validate_limits(self) -> VideoUploadConfig:
        if self.max_total_bytes < self.max_file_bytes:
            raise ValueError("video max_total_bytes must be at least max_file_bytes")
        if any(not item.startswith(".") for item in self.allowed_extensions):
            raise ValueError("video upload extensions must begin with a dot")
        return self


class VisionConfig(BaseModel):
    """Visual inspection runtime configuration."""

    allowed_image_roots: list[Path] = Field(
        default_factory=lambda: [Path("workspace/uploads")]
    )
    visualization_dir: Path = Path("workspace/events/images")
    batch_max_items: int = Field(default=50, ge=1, le=10_000)
    requires_review_threshold: float = Field(default=0.65, ge=0, le=1)
    http_timeout_seconds: float = Field(default=30, gt=0, le=300)
    http_retry_attempts: int = Field(default=2, ge=1, le=5)
    http_retry_wait_seconds: float = Field(default=0.1, ge=0, le=10)
    upload: ImageUploadConfig = Field(default_factory=ImageUploadConfig)
    video_upload: VideoUploadConfig = Field(default_factory=VideoUploadConfig)
    models: list[VisionModelConfig] = Field(default_factory=list)
    routing: VisionRoutingConfig = Field(default_factory=VisionRoutingConfig)
    semantic_router: MobileClip2SemanticRouterConfig = Field(
        default_factory=MobileClip2SemanticRouterConfig
    )
    open_vocab: OpenVocabularyConfig = Field(default_factory=OpenVocabularyConfig)
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    risk: RiskPolicyConfig = Field(default_factory=RiskPolicyConfig)

    @model_validator(mode="after")
    def unique_models(self) -> VisionConfig:
        names = [model.model_name for model in self.models]
        if len(names) != len(set(names)):
            raise ValueError("vision model_name values must be unique")
        unknown_semantic_experts = set(self.semantic_router.experts) - set(names)
        if unknown_semantic_experts:
            raise ValueError(
                "MobileCLIP2 semantic experts must reference configured vision models: "
                f"{sorted(unknown_semantic_experts)}"
            )
        return self


class TemporalRuleConfig(BaseModel):
    """M-of-N and smoothing policy for one realtime event type."""

    m: int = Field(ge=1, le=100)
    n: int = Field(ge=1, le=100)
    alpha: float = Field(default=0.6, gt=0, le=1)

    @model_validator(mode="after")
    def validate_window(self) -> TemporalRuleConfig:
        if self.m > self.n:
            raise ValueError("temporal confirmation m must not exceed n")
        return self


class CameraConfig(BaseModel):
    """One configured local video, USB, or RTSP source."""

    camera_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    source_type: Literal["local", "usb", "rtsp"]
    file_path: Path | None = None
    usb_index: int | None = Field(default=None, ge=0, le=128)
    rtsp_url: SecretStr | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> CameraConfig:
        configured = {
            "local": self.file_path is not None,
            "usb": self.usb_index is not None,
            "rtsp": self.rtsp_url is not None,
        }
        if not configured[self.source_type]:
            raise ValueError(f"{self.source_type} camera source is missing its location")
        if self.rtsp_url is not None and not self.rtsp_url.get_secret_value().strip():
            raise ValueError("RTSP camera URL must not be empty")
        return self


class CameraPolicyConfig(BaseModel):
    """Independent adaptive sampling policy for one camera."""

    static_fps: float = Field(default=1, gt=0, le=120)
    low_motion_fps: float = Field(default=3, gt=0, le=120)
    active_fps: float = Field(default=5, gt=0, le=120)
    suspected_fps: float = Field(default=8, gt=0, le=10)
    static_motion_threshold: float = Field(default=2, ge=0, le=255)
    active_motion_threshold: float = Field(default=12, gt=0, le=255)
    hysteresis_frames: int = Field(default=3, ge=1, le=100)

    @model_validator(mode="after")
    def validate_policy(self) -> CameraPolicyConfig:
        if not (
            self.static_fps
            <= self.low_motion_fps
            <= self.active_fps
            <= self.suspected_fps
        ):
            raise ValueError(
                "camera FPS must satisfy static <= low_motion <= active <= suspected"
            )
        if self.static_motion_threshold >= self.active_motion_threshold:
            raise ValueError(
                "static_motion_threshold must be below active_motion_threshold"
            )
        return self


class PPEEventConfig(BaseModel):
    """Association and temporal policy for missing PPE events."""

    person_head_iou: float = Field(default=0.5, gt=0, le=1)
    head_helmet_iou: float = Field(default=0.5, gt=0, le=1)
    person_vest_iou: float = Field(default=0.5, gt=0, le=1)
    m: int = Field(default=3, ge=1, le=100)
    n: int = Field(default=5, ge=1, le=100)
    cooldown_seconds: float = Field(default=10, ge=0, le=3600)
    track_max_age: int = Field(default=10, ge=0, le=1000)
    person_confidence: float = Field(default=0.5, ge=0, le=1)
    head_confidence: float = Field(default=0.5, ge=0, le=1)
    helmet_confidence: float = Field(default=0.5, ge=0, le=1)
    safety_vest_confidence: float = Field(default=0.5, ge=0, le=1)
    monitor_missing_helmet: bool = True
    monitor_missing_safety_vest: bool = False
    smoothing_alpha: float = Field(default=0.6, gt=0, le=1)

    @model_validator(mode="after")
    def validate_window(self) -> PPEEventConfig:
        if self.m > self.n:
            raise ValueError("PPE event m must not exceed n")
        if not (self.monitor_missing_helmet or self.monitor_missing_safety_vest):
            raise ValueError("At least one missing-PPE monitor must be enabled")
        return self


class RealtimeOptimizationConfig(BaseModel):
    """Video-only streaming, temporal-evidence, and recovery controls."""

    enabled: bool = False
    pace_local_video: bool = True
    local_playback_speed: float = Field(default=1.0, gt=0, le=100)
    normal_frame_deadline_seconds: float = Field(default=1.0, gt=0, le=30)
    risk_frame_deadline_seconds: float = Field(default=0.5, gt=0, le=30)
    suspected_hold_seconds: float = Field(default=2.0, ge=0, le=60)
    recovery_hold_seconds: float = Field(default=2.0, ge=0, le=60)
    uncertainty_threshold: float = Field(default=0.45, ge=0, le=1)
    observation_centric_tracking: bool = True
    direction_cost_weight: float = Field(default=0.25, ge=0, le=1)
    time_evidence_enabled: bool = True
    evidence_window_seconds: float = Field(default=5.0, gt=0, le=120)
    evidence_half_life_seconds: float = Field(default=1.5, gt=0, le=120)
    evidence_min_positive_seconds: float = Field(default=0.5, ge=0, le=30)
    evidence_confirm_threshold: float = Field(default=0.55, ge=0, le=1)
    calibration_path: Path | None = None
    calibration_required: bool = False
    @model_validator(mode="after")
    def validate_optimization(self) -> RealtimeOptimizationConfig:
        if self.risk_frame_deadline_seconds > self.normal_frame_deadline_seconds:
            raise ValueError("risk frame deadline must not exceed normal frame deadline")
        if self.evidence_min_positive_seconds > self.evidence_window_seconds:
            raise ValueError("minimum positive evidence must fit inside the evidence window")
        if self.calibration_required and self.calibration_path is None:
            raise ValueError("calibration_path is required when calibration is required")
        return self


class RealtimeConfig(BaseModel):
    """Bounded single-camera realtime monitoring policy."""

    allowed_video_roots: list[Path] = Field(
        default_factory=lambda: [Path("workspace/cameras")]
    )
    event_image_dir: Path = Path("workspace/events/images")
    event_clip_dir: Path = Path("workspace/events/clips")
    buffer_seconds: float = Field(default=20, gt=0, le=120)
    buffer_max_frames: int = Field(default=600, ge=1, le=20_000)
    buffer_memory_mb: float = Field(default=256, gt=0, le=8192)
    inference_queue_size: int = Field(default=32, ge=1, le=4096)
    event_queue_size: int = Field(default=64, ge=1, le=4096)
    max_concurrent_cameras: int = Field(default=4, ge=1, le=256)
    static_fps: float = Field(default=1, gt=0, le=120)
    low_motion_fps: float = Field(default=3, gt=0, le=120)
    normal_fps: float = Field(default=2, gt=0, le=120)
    active_fps: float = Field(default=5, gt=0, le=120)
    suspected_fps: float = Field(default=8, gt=0, le=120)
    tracker_algorithm: Literal["iou", "bytetrack"] = "bytetrack"
    tracker_iou_threshold: float = Field(default=0.3, gt=0, le=1)
    tracker_high_confidence: float = Field(default=0.5, ge=0, le=1)
    tracker_low_confidence: float = Field(default=0.1, ge=0, le=1)
    tracker_max_age: int = Field(default=10, ge=0, le=10_000)
    tracker_min_hits: int = Field(default=2, ge=1, le=100)
    reconnect_failure_threshold: int = Field(default=3, ge=1, le=100)
    reconnect_initial_seconds: float = Field(default=0.25, ge=0, le=30)
    reconnect_multiplier: float = Field(default=2, ge=1, le=10)
    reconnect_max_seconds: float = Field(default=30, gt=0, le=30)
    event_cooldown_seconds: float = Field(default=10, ge=0, le=3600)
    event_resolve_seconds: float = Field(default=15, gt=0, le=3600)
    event_region_iou_threshold: float = Field(default=0.4, gt=0, le=1)
    evidence_before_seconds: float = Field(default=5, ge=0, le=60)
    evidence_after_seconds: float = Field(default=5, ge=0, le=60)
    save_event_clips: bool = False
    clip_codec: str = Field(default="VP80", min_length=4, max_length=4)
    clip_fps: float = Field(default=10, gt=0, le=120)
    event_class_map: dict[str, str] = Field(default_factory=dict)
    event_severity: dict[
        str, Literal["info", "low", "normal", "medium", "high", "critical"]
    ] = Field(default_factory=dict)
    temporal_rules: dict[str, TemporalRuleConfig] = Field(default_factory=dict)
    ppe: PPEEventConfig = Field(default_factory=PPEEventConfig)
    optimization: RealtimeOptimizationConfig = Field(
        default_factory=RealtimeOptimizationConfig
    )
    cameras: list[CameraConfig] = Field(default_factory=list)
    camera_policies: dict[str, CameraPolicyConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_realtime(self) -> RealtimeConfig:
        identifiers = [camera.camera_id for camera in self.cameras]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("realtime camera_id values must be unique")
        if self.active_fps < self.normal_fps:
            raise ValueError("active_fps must be greater than or equal to normal_fps")
        if self.suspected_fps < self.active_fps:
            raise ValueError("suspected_fps must be greater than or equal to active_fps")
        if self.tracker_low_confidence > self.tracker_high_confidence:
            raise ValueError(
                "tracker_low_confidence must not exceed tracker_high_confidence"
            )
        if self.static_fps > self.low_motion_fps or self.low_motion_fps > self.active_fps:
            raise ValueError("adaptive FPS must satisfy static <= low_motion <= active")
        return self


class ReportingConfig(BaseModel):
    """Local report rendering and export policy."""

    output_dir: Path = Path("workspace/reports")
    template_name: str = Field(default="inspection", min_length=1, max_length=128)
    enable_pdf: bool = False
    max_summary_chars: int = Field(default=4000, ge=200, le=20_000)


class ServiceConfig(BaseModel):
    """Local API and Streamlit bind settings."""

    api_host: str = Field(default="127.0.0.1", min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65535)
    ui_host: str = Field(default="127.0.0.1", min_length=1)
    ui_port: int = Field(default=8501, ge=1, le=65535)
    api_base_url: HttpUrl = HttpUrl("http://127.0.0.1:8000")

    @field_validator("api_host", "ui_host")
    @classmethod
    def bind_host_must_be_local(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "localhost":
            return value
        try:
            is_loopback = ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            is_loopback = False
        if is_loopback:
            return value
        raise ValueError("service bind hosts must be localhost or loopback addresses")


class RuntimeModeConfig(BaseModel):
    """Persistent mutually exclusive runtime mode configuration."""

    state_path: Path = Path("workspace/runtime/runtime-mode.json")
    lock_path: Path = Path("workspace/runtime/runtime-mode.lock")
    audit_path: Path = Path("workspace/logs/audit/runtime-mode.jsonl")
    lock_timeout_seconds: float = Field(default=10, gt=0, le=300)
    task_priorities: dict[str, int] = Field(
        default_factory=lambda: {"online": 1, "indexing": 2, "training": 3}
    )

    @field_validator("task_priorities")
    @classmethod
    def complete_priorities(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != {"online", "indexing", "training"}:
            raise ValueError("Runtime priorities require online, indexing, and training")
        if any(priority < 1 for priority in value.values()):
            raise ValueError("Runtime priorities must be positive")
        return value


class EvaluationConfig(BaseModel):
    """Offline experiment and competition-export policy."""

    output_dir: Path = Path("workspace/reports/evaluation")
    agent_iterations: int = Field(default=20, ge=1, le=10_000)
    tool_iterations: int = Field(default=50, ge=1, le=100_000)
    video_stability_seconds: int = Field(default=7200, ge=1, le=604_800)
    multi_camera_stress_count: int = Field(default=4, ge=1, le=256)
    fail_on_missing_resources: bool = False
    active_quantization: str = Field(default="unreported", min_length=1, max_length=64)
    prefix_cache_enabled: bool | None = None
    context_compression_enabled: bool | None = None
    model_residency: Literal["unreported", "resident", "on_demand"] = "unreported"
    rgc_enabled: bool | None = None
    agent_dataset_path: Path | None = None
    rag_dataset_path: Path | None = None
    vision_dataset_path: Path | None = None
    realtime_dataset_path: Path | None = None
    security_dataset_path: Path | None = None
    stability_manifest_path: Path | None = None


class CompetitionConfig(BaseModel):
    """Resource inventory and readiness thresholds for competition delivery."""

    offline_only: bool = False
    require_rocm: bool = False
    agent_min_cases: int = Field(default=100, ge=1, le=100_000)
    rag_min_cases: int = Field(default=150, ge=1, le=100_000)
    ppe_dataset_dir: Path = Path("workspace/datasets/ppe")
    ppe_min_train_images: int = Field(default=1, ge=1, le=10_000_000)
    ppe_min_val_images: int = Field(default=1, ge=1, le=10_000_000)
    ppe_min_test_images: int = Field(default=1, ge=1, le=10_000_000)
    vision_min_distinct_models: int = Field(default=1, ge=1, le=100)
    vision_required_classes: list[str] = Field(
        default_factory=lambda: ["person", "head", "helmet", "safety_vest"]
    )
    knowledge_dir: Path = Path("workspace/knowledge")
    rag_manifest_path: Path = Path(
        "workspace/indexes/construction_standards/corpus_manifest.json"
    )


class Settings(BaseModel):
    """Complete stage-zero configuration."""

    model_config = ConfigDict(extra="forbid")
    app: AppConfig
    llm: LLMConfig
    permissions: PermissionConfig
    monitoring: MonitoringConfig
    rag: RagConfig = Field(default_factory=RagConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    realtime: RealtimeConfig = Field(default_factory=RealtimeConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    services: ServiceConfig = Field(default_factory=ServiceConfig)
    runtime: RuntimeModeConfig = Field(default_factory=RuntimeModeConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    competition: CompetitionConfig = Field(default_factory=CompetitionConfig)

    @model_validator(mode="after")
    def validate_competition_semantics(self) -> Settings:
        if self.app.environment != "competition":
            return self
        violations: list[str] = []
        if self.llm.mode == "mock":
            violations.append("LLM mock mode")
        if self.rag.embedding_mode == "mock":
            violations.append("embedding mock mode")
        if self.rag.reranker_mode == "mock":
            violations.append("reranker mock mode")
        if any(model.enabled and model.backend == "mock" for model in self.vision.models):
            violations.append("vision mock backend")
        if not self.competition.offline_only:
            violations.append("offline_only=false")
        if not self.competition.require_rocm:
            violations.append("require_rocm=false")
        if self.monitoring.scheduler.allow_cpu_fallback:
            violations.append("allow_cpu_fallback=true")
        if not self.rag.embedding_local_files_only:
            violations.append("embedding_local_files_only=false")
        if not self.rag.reranker_local_files_only:
            violations.append("reranker_local_files_only=false")
        if violations:
            raise ValueError(
                "Competition configuration violates production policy: "
                + ", ".join(violations)
            )
        return self

    def safe_dump(self) -> dict[str, Any]:
        """Return data safe for logging and CLI output."""
        data = self.model_dump(mode="json")
        if self.llm.api_key is not None:
            data["llm"]["api_key"] = "********"
        return data


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read YAML configuration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Configuration root must be a mapping: {path}")
    return raw


def _parse_env_value(value: str) -> Any:
    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return value


def _apply_environment(data: dict[str, Any]) -> None:
    prefix = "BUILDGUARD_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix) :].lower().split("__")
        if len(parts) < 2 or parts[0] not in {
            "app",
            "llm",
            "permissions",
            "monitoring",
            "rag",
            "vision",
            "realtime",
            "reporting",
            "services",
            "runtime",
            "evaluation",
            "competition",
        }:
            continue
        target = data.setdefault(parts[0], {})
        for part in parts[1:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = _parse_env_value(value)


def load_settings(config_path: Path) -> Settings:
    """Load the app manifest and referenced component YAML files."""
    app_file = config_path.resolve()
    manifest = _read_yaml(app_file)
    base = app_file.parent
    data: dict[str, Any] = {"app": manifest.get("app", {})}
    references = {
        "llm": "llm_config_path",
        "permissions": "permission_config_path",
        "monitoring": "monitoring_config_path",
    }
    for section, key in references.items():
        reference = Path(str(manifest.get(key, f"{section}.yaml")))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data[section] = child.get(section, child)
    rag_reference = manifest.get("rag_config_path")
    if rag_reference is not None:
        reference = Path(str(rag_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["rag"] = child.get("rag", child)
    else:
        data["rag"] = {}
    vision_reference = manifest.get("vision_config_path")
    if vision_reference is not None:
        reference = Path(str(vision_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["vision"] = child.get("vision", child)
    else:
        data["vision"] = {}
    realtime_reference = manifest.get("realtime_config_path")
    if realtime_reference is not None:
        reference = Path(str(realtime_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["realtime"] = child.get("realtime", child)
    else:
        data["realtime"] = {}
    reporting_reference = manifest.get("reporting_config_path")
    if reporting_reference is not None:
        reference = Path(str(reporting_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["reporting"] = child.get("reporting", child)
    else:
        data["reporting"] = {}
    services_reference = manifest.get("services_config_path")
    if services_reference is not None:
        reference = Path(str(services_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["services"] = child.get("services", child)
    else:
        data["services"] = {}
    runtime_reference = manifest.get("runtime_config_path")
    if runtime_reference is not None:
        reference = Path(str(runtime_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["runtime"] = child.get("runtime", child)
    else:
        data["runtime"] = {}
    evaluation_reference = manifest.get("evaluation_config_path")
    if evaluation_reference is not None:
        reference = Path(str(evaluation_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["evaluation"] = child.get("evaluation", child)
    else:
        data["evaluation"] = {}
    competition_reference = manifest.get("competition_config_path")
    if competition_reference is not None:
        reference = Path(str(competition_reference))
        child = _read_yaml(reference if reference.is_absolute() else base / reference)
        data["competition"] = child.get("competition", child)
    else:
        data["competition"] = {}
    _apply_environment(data)
    try:
        return Settings.model_validate(data)
    except Exception as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
