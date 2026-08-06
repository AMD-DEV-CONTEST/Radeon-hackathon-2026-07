from __future__ import annotations

from typing import Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel

from agent_factory.models.capabilities import ProviderProfile
from agent_factory.models.openai_compat import ThinkingCompatibleChatOpenAI


class ProviderAdapterError(RuntimeError):
    pass


class ChatModelAdapter(Protocol):
    profile: ProviderProfile

    def create_chat_model(self, settings: Any) -> BaseChatModel:
        ...


class OpenAIChatCompletionsAdapter:
    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    def create_chat_model(self, settings: Any) -> BaseChatModel:
        self._validate_reasoning(settings)
        kwargs: dict[str, Any] = {
            "model": settings.model,
            "api_key": settings.api_key,
            "base_url": settings.base_url,
            "streaming": True,
        }
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        if settings.timeout_seconds is not None:
            kwargs["timeout"] = settings.timeout_seconds
        if getattr(settings, "max_output_tokens", None) is not None:
            kwargs["max_tokens"] = settings.max_output_tokens

        extra_body = self.extra_body(settings)
        if extra_body:
            kwargs["extra_body"] = extra_body
        if self._should_preserve_reasoning_content(settings):
            kwargs["preserve_reasoning_content"] = True
        return ThinkingCompatibleChatOpenAI(**kwargs)

    def extra_body(self, settings: Any) -> dict[str, Any]:
        return {}

    def _validate_reasoning(self, settings: Any) -> None:
        reasoning = getattr(settings, "reasoning", None)
        if getattr(reasoning, "enabled", None) is not True:
            return
        if not self.profile.capabilities.supports_reasoning():
            raise ProviderAdapterError(
                f"{self.profile.provider_id} does not advertise reasoning support; "
                "choose a reasoning-capable provider profile or disable reasoning."
            )

    def _should_preserve_reasoning_content(self, settings: Any) -> bool:
        reasoning = getattr(settings, "reasoning", None)
        if getattr(reasoning, "enabled", None) is not True:
            return False
        if getattr(reasoning, "send_history", None) is False:
            return False
        return self.profile.capabilities.send_reasoning_history != "unsupported"


def reasoning_enabled(settings: Any) -> bool | None:
    return getattr(getattr(settings, "reasoning", None), "enabled", None)


def reasoning_effort(settings: Any) -> str | None:
    return _clean_str(getattr(getattr(settings, "reasoning", None), "effort", None))


def reasoning_summary(settings: Any) -> str | None:
    return _clean_str(getattr(getattr(settings, "reasoning", None), "summary", None))


def reasoning_budget_tokens(settings: Any) -> int | None:
    value = getattr(getattr(settings, "reasoning", None), "budget_tokens", None)
    return value if isinstance(value, int) and value > 0 else None


def _clean_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
