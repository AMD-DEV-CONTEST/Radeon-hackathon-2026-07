from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from agent_factory.models.adapters.base import (
    reasoning_budget_tokens,
    reasoning_effort,
    reasoning_enabled,
    reasoning_summary,
)
from agent_factory.models.capabilities import ProviderProfile


class AnthropicChatAdapter:
    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    def create_chat_model(self, settings: Any) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model_name": settings.model,
            "api_key": settings.api_key,
            "base_url": settings.base_url,
            "streaming": True,
            "stream_usage": True,
        }
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        if settings.timeout_seconds is not None:
            kwargs["timeout"] = settings.timeout_seconds
        if getattr(settings, "max_output_tokens", None) is not None:
            kwargs["max_tokens_to_sample"] = settings.max_output_tokens

        thinking = _thinking_payload(settings)
        if thinking:
            kwargs["thinking"] = thinking
        effort = reasoning_effort(settings)
        if effort:
            kwargs["effort"] = effort

        return ChatAnthropic(**kwargs)


def _thinking_payload(settings: Any) -> dict[str, Any]:
    enabled = reasoning_enabled(settings)
    if enabled is None:
        return {}
    if enabled is False:
        return {"type": "disabled"}
    budget = reasoning_budget_tokens(settings)
    if budget is not None:
        payload: dict[str, Any] = {"type": "enabled", "budget_tokens": budget}
    else:
        payload = {"type": "adaptive"}
    summary = reasoning_summary(settings)
    if summary in {"summary", "summarized"}:
        payload["display"] = "summarized"
    return payload
