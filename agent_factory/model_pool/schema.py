from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.models.protocol import ModelReasoningSettings, StructuredOutputMethod
from agent_factory.paths import cross_platform_absolute_path


UTC = timezone.utc
DEFAULT_LLAMA_CPP_PARALLEL_SLOTS = 3


ModelPoolProfileKind = Literal["chat", "embedding", "image_generation"]
ModelBindingRole = Literal["main", "task", "compression"]
ModelPoolDefaultRole = Literal["main", "task", "compression", "embedding", "image_generation"]
ModelBindingSource = Literal["model_pool", "runtime"]
ModelPoolModality = Literal["text", "image", "audio"]
ModelToolCapability = Literal["image_input", "image_output", "image_edit", "audio_input"]
ModelSelectionSource = Literal["auto", "manual"]
ModelSelectionOptimizeFor = Literal["balanced", "quality", "latency", "context"]
LocalInferenceEngine = Literal[
    "llama_cpp_rocm",
    "transformers_rocm",
    "stable_diffusion_cpp_rocm",
    "external",
]
ModelArtifactSource = Literal["local_storage", "external_endpoint"]
ModelContextExtensionMethod = Literal["yarn"]
DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS = 256 * 1024
DEFAULT_MODEL_COMPRESSION_TRIGGER_TOKENS = 200_000

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class ModelContextExtensionCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ModelContextExtensionMethod
    max_context_tokens: int = Field(ge=1)


class LocalModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    display_name: str
    kind: ModelPoolProfileKind
    source: ModelArtifactSource = "local_storage"
    local_path: str | None = None
    external_model_id: str | None = None
    model_format: str = "transformers"
    revision: str = ""
    checksum: str = ""
    license: str = ""
    native_context_tokens: int | None = Field(default=None, ge=1)
    context_extension: ModelContextExtensionCapability | None = None
    enabled: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id(cls, value: str) -> str:
        return validate_pool_id(value, field_name="artifact_id")

    @field_validator("display_name", "model_format")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("local_path")
    @classmethod
    def _local_path(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ValueError("local_path must be an absolute path")
        return str(path)

    @field_validator("external_model_id")
    @classmethod
    def _external_model_id(cls, value: str | None) -> str | None:
        return str(value or "").strip() or None

    @model_validator(mode="after")
    def _source_location(self) -> "LocalModelArtifact":
        if self.source == "local_storage" and not self.local_path:
            raise ValueError("local storage artifacts require local_path")
        if self.source == "external_endpoint" and not self.external_model_id:
            raise ValueError("external endpoint artifacts require external_model_id")
        if self.kind != "chat" and (self.native_context_tokens is not None or self.context_extension is not None):
            raise ValueError("context capabilities are only valid for chat model artifacts")
        if self.context_extension is not None:
            if self.native_context_tokens is None:
                raise ValueError("context extension requires native_context_tokens")
            if self.context_extension.max_context_tokens <= self.native_context_tokens:
                raise ValueError("extended context limit must exceed native context length")
        return self

    @field_validator("revision", "checksum", "license")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()

    def resolved_path(self) -> Path:
        if not self.local_path:
            raise ValueError("external endpoint artifacts do not have a local model path")
        return Path(self.local_path).expanduser().resolve()


class ModelPoolCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    output_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    tool_calling: bool = True
    streaming_tool_calls: bool = False
    strict_tool_schema: bool = False
    structured_output_methods: list[StructuredOutputMethod] = Field(
        default_factory=lambda: ["function_calling", "json_mode"]
    )
    reasoning_supported: bool = False
    reasoning_efforts: list[str] = Field(default_factory=list)
    reasoning_content: bool = False
    cache_usage: bool = False
    text_to_image: bool = False
    image_to_image: bool = False
    image_edit: bool = False
    batch_generation: bool = False
    async_job: bool = False

    @field_validator("input_modalities", "output_modalities", "structured_output_methods", "reasoning_efforts")
    @classmethod
    def _stable_strings(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip().lower()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result


class ModelPoolLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    context_compression_threshold_tokens: int | None = Field(default=None, ge=1000)

    @model_validator(mode="after")
    def _compression_fits_context_window(self) -> "ModelPoolLimits":
        if (
            self.max_input_tokens is not None
            and self.context_compression_threshold_tokens is not None
            and self.context_compression_threshold_tokens > self.max_input_tokens
        ):
            raise ValueError(
                "context_compression_threshold_tokens must not exceed max_input_tokens"
            )
        return self


class ModelPoolRuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0)


class LlamaCppMtpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["mtp"] = "mtp"
    max_draft_tokens: int = Field(default=3, ge=1, le=32)
    min_draft_tokens: int = Field(default=0, ge=0, le=32)
    min_acceptance_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    backend_sampling: bool = True

    @model_validator(mode="after")
    def _draft_range(self) -> "LlamaCppMtpConfig":
        if self.min_draft_tokens > self.max_draft_tokens:
            raise ValueError("min_draft_tokens must not exceed max_draft_tokens")
        return self


class LlamaCppSpeculativeDecodingDisabledConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["disabled"] = "disabled"


LlamaCppSpeculativeDecodingConfig = Annotated[
    LlamaCppSpeculativeDecodingDisabledConfig | LlamaCppMtpConfig,
    Field(discriminator="method"),
]


class LlamaCppInferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu_layers: int = Field(default=99, ge=0)
    parallel_slots: int = Field(default=DEFAULT_LLAMA_CPP_PARALLEL_SLOTS, ge=1)
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    flash_attention: bool = True
    mmproj_path: str | None = None
    speculative_decoding: LlamaCppSpeculativeDecodingConfig = Field(
        default_factory=LlamaCppSpeculativeDecodingDisabledConfig
    )

    @field_validator("cache_type_k", "cache_type_v")
    @classmethod
    def _cache_type(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        supported = {"f16", "bf16", "q8_0", "q4_0"}
        if text not in supported:
            raise ValueError(f"cache type must be one of: {', '.join(sorted(supported))}")
        return text

    @field_validator("mmproj_path")
    @classmethod
    def _mmproj_path(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        path = cross_platform_absolute_path(text)
        if path is None:
            raise ValueError("mmproj_path must be an absolute path")
        return str(path)


class TransformersInferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust_remote_code: bool = False


class StableDiffusionCppInferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vae_path: str
    clip_l_path: str
    t5xxl_path: str
    diffusion_flash_attention: bool = True
    eager_load: bool = True
    clip_on_cpu: bool = True
    vae_tiling: bool = True
    offload_to_cpu: bool = False
    max_vram_gib: float | None = Field(default=None, gt=0)
    stream_layers: int | None = Field(default=None, ge=1)
    default_width: int = Field(default=1024, ge=64, le=4096, multiple_of=64)
    default_height: int = Field(default=1024, ge=64, le=4096, multiple_of=64)
    default_steps: int = Field(default=20, ge=1, le=200)
    default_cfg_scale: float = Field(default=1.0, ge=0, le=30)
    default_sampler: str = "euler"
    residency_policy: Literal["coexist_if_fit", "exclusive"] = "coexist_if_fit"

    @field_validator("vae_path", "clip_l_path", "t5xxl_path")
    @classmethod
    def _required_absolute_path(cls, value: str) -> str:
        path = cross_platform_absolute_path(str(value or "").strip())
        if path is None:
            raise ValueError("stable-diffusion.cpp component paths must be absolute")
        return str(path)

    @field_validator("default_sampler")
    @classmethod
    def _sampler(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if not text:
            raise ValueError("default_sampler is required")
        return text


class ExternalInferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external: Literal[True] = True
    remote_inference: LlamaCppInferenceConfig | TransformersInferenceConfig | StableDiffusionCppInferenceConfig | None = None


LocalInferenceConfig = (
    LlamaCppInferenceConfig
    | TransformersInferenceConfig
    | StableDiffusionCppInferenceConfig
    | ExternalInferenceConfig
)


class ModelPoolProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    display_name: str
    description: str = ""
    kind: ModelPoolProfileKind = "chat"
    artifact_id: str
    engine: LocalInferenceEngine
    served_model_name: str
    enabled: bool = True
    capabilities: ModelPoolCapabilities = Field(default_factory=ModelPoolCapabilities)
    settings: ModelPoolRuntimeSettings = Field(default_factory=ModelPoolRuntimeSettings)
    limits: ModelPoolLimits = Field(default_factory=ModelPoolLimits)
    inference: LocalInferenceConfig
    embedding_dimensions: int | None = Field(default=None, ge=1)
    normalize_embeddings: bool = True
    notes: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("profile_id", "artifact_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return validate_pool_id(value, field_name="id")

    @field_validator("display_name", "served_model_name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @model_validator(mode="after")
    def _engine_matches_kind(self) -> "ModelPoolProfile":
        if self.kind == "chat":
            if self.engine == "llama_cpp_rocm" and not isinstance(self.inference, LlamaCppInferenceConfig):
                raise ValueError("chat profiles require llama.cpp inference settings")
            if self.engine == "external" and not isinstance(self.inference, ExternalInferenceConfig):
                raise ValueError("external chat profiles require external inference settings")
            if self.engine not in {"llama_cpp_rocm", "external"}:
                raise ValueError("unsupported chat inference engine")
            if (
                self.engine == "llama_cpp_rocm"
                and "image" in self.capabilities.input_modalities
                and isinstance(self.inference, LlamaCppInferenceConfig)
                and not self.inference.mmproj_path
            ):
                raise ValueError("image input requires a llama.cpp mmproj_path")
        if self.kind == "embedding":
            if self.engine == "transformers_rocm" and not isinstance(self.inference, TransformersInferenceConfig):
                raise ValueError("embedding profiles require Transformers inference settings")
            if self.engine == "external" and not isinstance(self.inference, ExternalInferenceConfig):
                raise ValueError("external embedding profiles require external inference settings")
            if self.engine not in {"transformers_rocm", "external"}:
                raise ValueError("unsupported embedding inference engine")
            if self.embedding_dimensions is None:
                raise ValueError("embedding profiles require embedding_dimensions")
        if self.kind == "image_generation":
            if self.engine == "stable_diffusion_cpp_rocm" and not isinstance(
                self.inference, StableDiffusionCppInferenceConfig
            ):
                raise ValueError("image generation profiles require stable-diffusion.cpp settings")
            if self.engine == "external" and not isinstance(self.inference, ExternalInferenceConfig):
                raise ValueError("external image generation profiles require external inference settings")
            if self.engine not in {"stable_diffusion_cpp_rocm", "external"}:
                raise ValueError("unsupported image generation inference engine")
            if "image" not in self.capabilities.output_modalities or not self.capabilities.text_to_image:
                raise ValueError("image generation profiles require image output and text_to_image capability")
        return self

    @property
    def model_name(self) -> str:
        return self.served_model_name

    def to_public(self, artifact: LocalModelArtifact | None = None) -> "ModelPoolProfilePublic":
        return ModelPoolProfilePublic(
            **self.model_dump(mode="json"),
            artifact=artifact,
        )


class ModelPoolProfilePublic(ModelPoolProfile):
    artifact: LocalModelArtifact | None = None


class ModelSelectionRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelBindingRole
    purpose: str = ""
    kind: ModelPoolProfileKind | None = None
    input_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    output_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    tool_calling: bool | None = None
    structured_output_methods: list[StructuredOutputMethod] = Field(default_factory=list)
    reasoning_required: bool | None = None
    min_context_window_tokens: int | None = Field(default=None, ge=1)
    excluded_profile_ids: list[str] = Field(default_factory=list)
    optimize_for: ModelSelectionOptimizeFor = "balanced"
    max_candidates: int = Field(default=5, ge=1, le=20)

    @field_validator("input_modalities", "output_modalities", "excluded_profile_ids")
    @classmethod
    def _stable_strings(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip().lower()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result

    @model_validator(mode="after")
    def _default_kind(self) -> "ModelSelectionRequirement":
        if self.kind is not None:
            return self
        return self.model_copy(update={"kind": "chat"})


class ModelSelectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    display_name: str
    description: str = ""
    engine: LocalInferenceEngine
    model_name: str
    score: float
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class ModelSelectionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelBindingRole
    profile_id: str
    display_name: str
    description: str = ""
    engine: LocalInferenceEngine
    model_name: str
    score: float
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    candidates: list[ModelSelectionCandidate] = Field(default_factory=list)


class ModelToolSelectionRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    capability: ModelToolCapability
    purpose: str = ""
    min_context_window_tokens: int | None = Field(default=None, ge=1)
    excluded_profile_ids: list[str] = Field(default_factory=list)
    optimize_for: ModelSelectionOptimizeFor = "balanced"
    max_candidates: int = Field(default=5, ge=1, le=20)

    @field_validator("tool_id")
    @classmethod
    def _tool_id(cls, value: str) -> str:
        tool_id = str(value or "").strip()
        if not _TOOL_ID_RE.fullmatch(tool_id):
            raise ValueError("tool_id must be snake_case")
        return tool_id

    def as_model_requirement(self) -> ModelSelectionRequirement:
        if self.capability in {"image_output", "image_edit"}:
            return ModelSelectionRequirement(
                role="task",
                purpose=self.purpose,
                kind="image_generation",
                input_modalities=["text"],
                output_modalities=["image"],
                excluded_profile_ids=self.excluded_profile_ids,
                optimize_for=self.optimize_for,
                max_candidates=self.max_candidates,
            )
        modality = "image" if self.capability == "image_input" else "audio"
        return ModelSelectionRequirement(
            role="task",
            purpose=self.purpose,
            kind="chat",
            input_modalities=[modality],
            output_modalities=["text"],
            min_context_window_tokens=self.min_context_window_tokens,
            excluded_profile_ids=self.excluded_profile_ids,
            optimize_for=self.optimize_for,
            max_candidates=self.max_candidates,
        )


class ModelToolSelectionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    capability: ModelToolCapability
    profile_id: str
    display_name: str
    description: str = ""
    engine: LocalInferenceEngine
    model_name: str
    score: float
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    candidates: list[ModelSelectionCandidate] = Field(default_factory=list)


class ModelSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ModelSelectionRequirement] = Field(default_factory=list)
    tool_requirements: list[ModelToolSelectionRequirement] = Field(default_factory=list)


class ModelSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "blocked"] = "completed"
    recommendations: list[ModelSelectionRecommendation] = Field(default_factory=list)
    tool_recommendations: list[ModelToolSelectionRecommendation] = Field(default_factory=list)
    unmatched: list[dict[str, Any]] = Field(default_factory=list)
    profile_count: int = 0
    enabled_profile_count: int = 0


class ModelBindingRuntimeOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelProfileBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = None
    source: ModelBindingSource = "model_pool"
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    overrides: ModelBindingRuntimeOverrides = Field(default_factory=ModelBindingRuntimeOverrides)

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str | None) -> str | None:
        return validate_pool_id(value, field_name="profile_id") if value is not None else None

    @model_validator(mode="after")
    def _source_requirements(self) -> "ModelProfileBinding":
        if self.source == "runtime" and self.profile_id:
            raise ValueError("runtime bindings must not define profile_id")
        return self


class ModelToolBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = None
    source: ModelBindingSource = "model_pool"
    capability: ModelToolCapability
    required: bool = True
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    overrides: ModelBindingRuntimeOverrides = Field(default_factory=ModelBindingRuntimeOverrides)
    description: str = ""

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str | None) -> str | None:
        return validate_pool_id(value, field_name="profile_id") if value is not None else None

    @model_validator(mode="after")
    def _source_requirements(self) -> "ModelToolBinding":
        if self.source == "runtime" and self.profile_id:
            raise ValueError("runtime bindings must not define profile_id")
        return self


def validate_pool_id(value: str, *, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(text):
        raise ValueError(
            f"{field_name} must start with a lowercase letter and contain lowercase letters, digits, _, ., or -"
        )
    return text
