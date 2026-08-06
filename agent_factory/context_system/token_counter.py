from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from agent_factory.models.usage import normalize_usage_metadata
from agent_factory.model_pool.schema import (
    DEFAULT_MODEL_COMPRESSION_TRIGGER_TOKENS,
    DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS,
)
from agent_factory.context_system.token_estimation import estimate_messages_tokens


@dataclass(frozen=True, slots=True)
class TokenCountResult:
    token_count: int | None
    method: str
    error: str | None = None
    model_role: str | None = None


@dataclass(frozen=True, slots=True)
class ModelContextLimits:
    context_window_tokens: int
    compression_trigger_tokens: int


def context_limits_with_overrides(
    limits: ModelContextLimits,
    *,
    context_window_tokens: int | None,
    compression_trigger_tokens: int | None,
) -> ModelContextLimits:
    window = context_window_tokens or limits.context_window_tokens
    trigger = (
        compression_trigger_tokens
        if compression_trigger_tokens is not None
        else min(limits.compression_trigger_tokens, window)
    )
    if trigger > window:
        raise ValueError("context compression trigger exceeds the effective context window")
    return ModelContextLimits(
        context_window_tokens=window,
        compression_trigger_tokens=trigger,
    )


def model_context_limits(
    *,
    services: Any | None = None,
    state: Any | None = None,
    model_role: str | None = None,
) -> ModelContextLimits:
    role = model_role or _model_role_from_services(services)
    service = getattr(services, "model_operation_service", None) if services is not None else None
    resolver = getattr(service, "context_limits_for_role", None)
    if callable(resolver):
        try:
            limits = resolver(role, state=state)
        except (LookupError, RuntimeError, ValueError):
            limits = None
        if isinstance(limits, dict):
            return _normalized_model_context_limits(limits)
    try:
        from agent_factory.model_pool.resolver import resolve_available_chat_model

        resolved = resolve_available_chat_model(role)
    except Exception:
        resolved = None
    if resolved is None and role == "task":
        try:
            resolved = resolve_available_chat_model("main")
        except Exception:
            resolved = None
    settings = resolved.settings if resolved is not None else None
    return _normalized_model_context_limits(
        {
            "max_input_tokens": getattr(settings, "max_input_tokens", None),
            "compression_trigger_tokens": getattr(settings, "compression_trigger_tokens", None),
        }
    )


def count_messages_tokens(
    messages: list[Any],
    *,
    services: Any | None = None,
    model: Any | None = None,
    model_role: str | None = None,
    tools: list[Any] | None = None,
) -> TokenCountResult:
    del model
    model_role = model_role or _model_role_from_services(services)
    normalized = [message for message in messages if isinstance(message, BaseMessage)]
    if not normalized:
        normalized = [HumanMessage(content=str(message)) for message in messages if str(message)]
    return TokenCountResult(
        token_count=estimate_messages_tokens(normalized),
        method="text_estimation_messages_only" if tools else "text_estimation",
        model_role=model_role,
    )


def count_text_tokens(
    text: str,
    *,
    services: Any | None = None,
    model: Any | None = None,
    model_role: str | None = None,
) -> TokenCountResult:
    if not text:
        return TokenCountResult(
            token_count=0,
            method="model_tokenizer",
            model_role=model_role or _model_role_from_services(services),
        )
    return count_messages_tokens(
        [HumanMessage(content=text)],
        services=services,
        model=model,
        model_role=model_role,
    )


def context_window_payload(
    *,
    node_id: str,
    token_count: int | None,
    token_count_method: str,
    compression_threshold_tokens: int | None,
    context_window_tokens: int | None = None,
    error: str | None = None,
    model_role: str | None = None,
    source: str,
) -> dict[str, Any]:
    window = context_window_tokens
    payload: dict[str, Any] = {
        "node_id": node_id,
        "source": source,
        "token_count": token_count,
        "token_count_method": token_count_method,
        "context_window_tokens": window,
        "compression_threshold_tokens": compression_threshold_tokens,
        "model_role": model_role,
    }
    if token_count is not None and window:
        payload["window_usage_ratio"] = min(float(token_count) / float(window), 1.0)
    if token_count is not None and compression_threshold_tokens:
        payload["compression_usage_ratio"] = min(float(token_count) / float(compression_threshold_tokens), 1.0)
    if error:
        payload["error"] = error
    return payload


def _normalized_model_context_limits(values: dict[str, Any]) -> ModelContextLimits:
    window = _positive_int(values.get("max_input_tokens")) or DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS
    trigger = (
        _positive_int(values.get("compression_trigger_tokens"))
        or DEFAULT_MODEL_COMPRESSION_TRIGGER_TOKENS
    )
    if trigger > window:
        raise ValueError("active model compression trigger exceeds its context window")
    return ModelContextLimits(
        context_window_tokens=window,
        compression_trigger_tokens=trigger,
    )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def token_count_from_usage_metadata(usage: Any) -> int | None:
    return normalize_usage_metadata(usage).input_tokens


def output_token_count_from_usage_metadata(usage: Any) -> int | None:
    return normalize_usage_metadata(usage).output_tokens


def cached_input_token_count_from_usage_metadata(usage: Any) -> int | None:
    return normalize_usage_metadata(usage).cache_hit_tokens


def provider_token_budget_payload(
    *,
    usage_metadata: Any,
    node_id: str,
    model_role: str,
    provider_input_tokens: Any = None,
) -> dict[str, Any]:
    usage = normalize_usage_metadata(usage_metadata)
    input_tokens = _token_int(provider_input_tokens)
    if input_tokens is None:
        input_tokens = usage.input_tokens
    if input_tokens is None:
        return {}
    output_tokens = usage.output_tokens
    total_tokens = usage.total_tokens
    context_tokens_after_call = total_tokens or int(input_tokens) + int(output_tokens or 0)
    return {
        "last_provider_input_tokens": int(input_tokens),
        "last_provider_output_tokens": output_tokens,
        "last_provider_total_tokens": total_tokens,
        "last_provider_context_tokens_after_call": context_tokens_after_call,
        "last_provider_token_count_method": "provider_usage",
        "last_provider_node_id": node_id,
        "last_provider_model_role": model_role,
        "last_provider_usage_metadata": usage_metadata if isinstance(usage_metadata, dict) else {},
    }


def _model_role_from_services(services: Any | None) -> str:
    if services is None:
        return "main"
    for service_name in ("model_operation_service", "model_service"):
        service = getattr(services, service_name, None)
        role = getattr(service, "model_role", None)
        if role:
            return str(role)
    return "main"


def _token_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
