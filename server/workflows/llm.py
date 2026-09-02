"""LLM provider placeholders for future OpenAI integration.

No prompts, no API keys, and no network calls are implemented here.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Structural interface for future language-model providers."""

    @property
    def name(self) -> str: ...

    @property
    def is_enabled(self) -> bool: ...

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> str: ...


class NoOpLLMProvider:
    """Disabled provider used until OpenAI integration is wired in."""

    def __init__(self, *, name: str = "noop") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_enabled(self) -> bool:
        return False

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError(
            "LLM provider is not configured. Future OpenAI integration goes here."
        )


def get_default_llm_provider() -> LLMProvider:
    """Return the default LLM provider.

    Prefers the OpenAI stub when ``settings.llm_enabled`` is true; otherwise
    returns the no-op provider. No network calls are made by either stub.
    """
    from core.config import settings

    if settings.llm_enabled:
        from integrations.openai_provider import get_openai_provider

        return get_openai_provider()
    return NoOpLLMProvider()
