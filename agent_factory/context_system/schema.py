from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ContextCandidateKind = Literal["memory"]
ContextEventStatus = Literal["started", "completed", "failed", "skipped"]


class CompressionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    trigger_token_threshold: int | None = Field(
        default=None,
        ge=1000,
        description="Optional Agent override. Null follows the active model profile.",
    )
    keep_recent_messages: int = Field(default=12, ge=2, le=128)


class CrossSessionMemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    write_enabled: bool = True
    injection_enabled: bool = True
    write_interval_turns: int = Field(default=3, ge=1, le=1000)
    max_candidates: int = Field(default=24, ge=1, le=128)
    min_score: float = Field(default=0.55, ge=0.0, le=1.0)
    max_items: int = Field(default=8, ge=1, le=64)
    max_tokens: int = Field(default=1200, ge=100, le=32000)
    per_kind_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "constraint": 3,
            "preference": 3,
            "decision": 2,
            "fact": 2,
            "artifact": 1,
        }
    )

    @field_validator("per_kind_limits")
    @classmethod
    def _per_kind_limits_are_valid(cls, value: dict[str, int]) -> dict[str, int]:
        result: dict[str, int] = {}
        for raw_kind, raw_limit in value.items():
            kind = str(raw_kind).strip()
            if not kind:
                raise ValueError("per_kind_limits keys must not be empty")
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or raw_limit < 0:
                raise ValueError("per_kind_limits values must be non-negative integers")
            result[kind] = raw_limit
        return result


class AssemblyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items_total: int = Field(default=8, ge=1, le=64)
    max_tokens_total: int = Field(default=1200, ge=100, le=32000)
    per_source_limits: dict[str, int] = Field(default_factory=dict)


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["context_policy.v1"] = "context_policy.v1"
    compression: CompressionPolicy = Field(default_factory=CompressionPolicy)
    cross_session_memory: CrossSessionMemoryPolicy = Field(default_factory=CrossSessionMemoryPolicy)

    def assembly_policy(self) -> AssemblyPolicy:
        memory = self.cross_session_memory
        return AssemblyPolicy(
            max_items_total=memory.max_items,
            max_tokens_total=memory.max_tokens,
            per_source_limits={"cross_session_memory": memory.max_items},
        )


class ContextContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["context_system.v1"] = "context_system.v1"
    enabled: bool = True
    context_window_tokens: int | None = Field(default=None, ge=1000)
    default_policy: ContextPolicy = Field(default_factory=ContextPolicy)

    @model_validator(mode="after")
    def _explicit_limits_are_consistent(self) -> "ContextContractConfig":
        if self.context_window_tokens is None:
            return self
        threshold = self.default_policy.compression.trigger_token_threshold
        if threshold is not None and threshold > self.context_window_tokens:
            raise ValueError("compression threshold exceeds context_window_tokens")
        return self


class ContextQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    impl: str
    text: str = ""
    user_input: str | None = None


class ContextCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_id: str
    kind: ContextCandidateKind
    content: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    token_estimate: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMContextFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["llm_context_frame.v0"] = "llm_context_frame.v0"
    node_id: str
    query: str
    items: list[ContextCandidate] = Field(default_factory=list)
    token_estimate: int = 0
    text: str = ""


class ContextCompressionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ContextEventStatus
    node_id: str | None = None
    original_message_count: int = 0
    compressed_message_count: int = 0
    token_estimate_before: int = 0
    token_estimate_after: int = 0
    token_count_method: str | None = None
    token_count_error: str | None = None
    summary_token_estimate: int = 0
    error: str | None = None
    duration_ms: int = 0


class ContextRetrievalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ContextEventStatus
    node_id: str | None = None
    source_counts: dict[str, int] = Field(default_factory=dict)
    candidate_count: int = 0
    selected_count: int = 0
    token_estimate: int = 0
    error: str | None = None
    duration_ms: int = 0


class ContextInjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ContextEventStatus
    node_id: str | None = None
    item_count: int = 0
    token_estimate: int = 0
    error: str | None = None
    duration_ms: int = 0
