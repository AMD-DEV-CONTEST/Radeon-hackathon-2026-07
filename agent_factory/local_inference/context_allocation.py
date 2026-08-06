from __future__ import annotations

from dataclasses import dataclass

from agent_factory.model_pool.schema import LlamaCppInferenceConfig, LocalModelArtifact, ModelPoolLimits


@dataclass(frozen=True, slots=True)
class LlamaContextAllocation:
    per_slot_tokens: int
    parallel_slots: int
    server_context_tokens: int


@dataclass(frozen=True, slots=True)
class LlamaRopeScaling:
    method: str
    original_context_tokens: int
    target_context_tokens: int
    factor: float


@dataclass(frozen=True, slots=True)
class LlamaContextPlan:
    allocation: LlamaContextAllocation
    rope_scaling: LlamaRopeScaling | None


def resolve_llama_context_allocation(
    limits: ModelPoolLimits,
    inference: LlamaCppInferenceConfig,
) -> LlamaContextAllocation | None:
    per_slot_tokens = limits.max_input_tokens
    if per_slot_tokens is None:
        return None
    parallel_slots = inference.parallel_slots
    return LlamaContextAllocation(
        per_slot_tokens=per_slot_tokens,
        parallel_slots=parallel_slots,
        server_context_tokens=per_slot_tokens * parallel_slots,
    )


def resolve_llama_context_plan(
    artifact: LocalModelArtifact,
    limits: ModelPoolLimits,
    inference: LlamaCppInferenceConfig,
) -> LlamaContextPlan | None:
    allocation = resolve_llama_context_allocation(limits, inference)
    if allocation is None:
        return None
    native_context_tokens = artifact.native_context_tokens
    if native_context_tokens is None or allocation.per_slot_tokens <= native_context_tokens:
        return LlamaContextPlan(allocation=allocation, rope_scaling=None)
    extension = artifact.context_extension
    if extension is None:
        raise ValueError(
            f"requested context {allocation.per_slot_tokens} exceeds the model native context "
            f"{native_context_tokens}, but the model does not declare a context extension capability"
        )
    if allocation.per_slot_tokens > extension.max_context_tokens:
        raise ValueError(
            f"requested context {allocation.per_slot_tokens} exceeds the model {extension.method} limit "
            f"{extension.max_context_tokens}"
        )
    return LlamaContextPlan(
        allocation=allocation,
        rope_scaling=LlamaRopeScaling(
            method=extension.method,
            original_context_tokens=native_context_tokens,
            target_context_tokens=allocation.per_slot_tokens,
            factor=allocation.per_slot_tokens / native_context_tokens,
        ),
    )
