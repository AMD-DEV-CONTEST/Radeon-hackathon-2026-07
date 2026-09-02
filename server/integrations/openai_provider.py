"""OpenAI LLM provider stub implementing the workflow LLM protocol."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.logger import get_logger
from workflows.llm import LLMProvider

logger = get_logger(__name__)


class OpenAIProvider:
    """Disabled OpenAI provider prepared for future wiring.

    No network calls are made. Enable via settings and implement ``complete``
    when API keys are available.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or settings.openai_model
        self._api_key = api_key or getattr(settings, "openai_api_key", None)
        self._enabled = bool(settings.llm_enabled and self._api_key)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        _ = (messages, model, kwargs)
        raise NotImplementedError(
            "OpenAI provider stub only. Implement API calls when llm_enabled "
            "and openai_api_key are configured."
        )


def get_openai_provider() -> LLMProvider:
    provider = OpenAIProvider()
    if not provider.is_enabled:
        logger.debug("OpenAI provider disabled (stub active)")
    return provider
