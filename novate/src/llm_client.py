"""
Thin client around a local, OpenAI-compatible inference server.

Why this design:
- llama.cpp's `llama-server` and vLLM's `--api-server` both expose the same
  `/v1/chat/completions` schema, so Nova can swap between them (or between
  models) with zero code changes — only config.py / .env changes.
- All inference happens on-machine, on the AMD Radeon GPU via ROCm. Nova
  itself never sends prompts or documents to any third-party API.
"""
from __future__ import annotations

import logging
from typing import Iterable

from openai import OpenAI

import config

logger = logging.getLogger(__name__)


class LocalLLMClient:
    """Wraps chat-completion calls to a local ROCm-backed inference server."""

    def __init__(
        self,
        base_url: str = config.LLM_SERVER_BASE_URL,
        model_name: str = config.LLM_MODEL_NAME,
        api_key: str = config.LLM_API_KEY,
        timeout: int = config.LLM_TIMEOUT_S,
    ) -> None:
        self.model_name = model_name
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    def chat(
        self,
        messages: Iterable[dict],
        temperature: float = config.LLM_TEMPERATURE,
        max_tokens: int = config.LLM_MAX_TOKENS,
    ) -> str:
        """Send a chat-formatted message list to the local model, return text."""
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # local server down, connection refused, etc.
            logger.error("Local LLM call failed: %s", exc)
            raise RuntimeError(
                "Could not reach the local inference server. Is `llama-server` "
                "(or vLLM) running? See README > Running the model server."
            ) from exc

        return response.choices[0].message.content or ""

    def health_check(self) -> bool:
        """Return True if the local inference server responds."""
        try:
            self.chat(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=4,
            )
            return True
        except RuntimeError:
            return False
