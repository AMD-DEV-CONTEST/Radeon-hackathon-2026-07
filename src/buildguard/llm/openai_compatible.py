"""OpenAI-compatible adapter restricted to approved local endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from buildguard.benchmark import validate_local_endpoint
from buildguard.config import LLMConfig, PermissionConfig
from buildguard.llm.base import (
    ChatMessage,
    GenerationProfileName,
    LocalLLMBackend,
    StructuredT,
)
from buildguard.llm.structured_output import parse_with_one_retry
from buildguard.llm.token_metrics import ChatResponse, TokenMetrics


class OpenAICompatibleLocalBackend(LocalLLMBackend):
    """Synchronous local llama.cpp/vLLM HTTP backend."""

    def __init__(
        self,
        config: LLMConfig,
        permissions: PermissionConfig,
        client: httpx.Client | None = None,
    ) -> None:
        validate_local_endpoint(config, permissions)
        self.config = config
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=config.timeout_seconds)
        self.metrics_history: list[TokenMetrics] = []

    @property
    def _chat_url(self) -> str:
        return f"{str(self.config.endpoint).rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        if self.config.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"}

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        stream: bool,
        thinking: bool,
        profile: GenerationProfileName | None,
    ) -> dict[str, Any]:
        selected = (
            getattr(self.config.generation_profiles, profile)
            if profile is not None
            else None
        )
        return {
            "model": self.config.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": selected.temperature if selected else self.config.temperature,
            "top_p": selected.top_p if selected else 1.0,
            "max_tokens": selected.max_tokens if selected else self.config.max_tokens,
            "stream": stream,
            "cache_prompt": self.config.cache_prompt,
            "chat_template_kwargs": {
                "enable_thinking": selected.thinking if selected else thinking
            },
        }

    def _retrying(self) -> Retrying:
        return Retrying(
            stop=stop_after_attempt(self.config.retry_attempts),
            wait=wait_fixed(self.config.retry_wait_seconds),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> ChatResponse:
        if self.config.stream_complete_responses:
            content = "".join(
                self.stream_chat(messages, thinking=thinking, profile=profile)
            )
            return ChatResponse(content=content, metrics=self.metrics_history[-1])
        started = time.perf_counter()

        def request() -> httpx.Response:
            response = self.client.post(
                self._chat_url,
                json=self._payload(
                    messages, stream=False, thinking=thinking, profile=profile
                ),
                headers=self._headers(),
            )
            response.raise_for_status()
            return response

        response = self._retrying()(request)
        payload = response.json()
        content = str(payload["choices"][0]["message"]["content"])
        usage = payload.get("usage", {})
        prompt_tokens = int(
            usage.get("prompt_tokens", sum(len(message.content.split()) for message in messages))
        )
        completion_tokens = int(usage.get("completion_tokens", max(1, len(content.split()))))
        total = time.perf_counter() - started
        metrics = TokenMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=int(usage.get("total_tokens", prompt_tokens + completion_tokens)),
            ttft_seconds=None,
            total_seconds=total,
            tokens_per_second=completion_tokens / total if total else 0,
            thinking_mode=(
                getattr(self.config.generation_profiles, profile).thinking
                if profile is not None
                else thinking
            ),
        )
        self.metrics_history.append(metrics)
        return ChatResponse(content=content, metrics=metrics)

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> Iterator[str]:
        started = time.perf_counter()
        first_token: float | None = None
        completion_tokens = 0
        prompt_tokens = sum(len(message.content.split()) for message in messages)
        with self.client.stream(
            "POST",
            self._chat_url,
            json=self._payload(
                messages, stream=True, thinking=thinking, profile=profile
            ),
            headers=self._headers(),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                try:
                    content = json.loads(raw)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if content:
                    if first_token is None:
                        first_token = time.perf_counter() - started
                    completion_tokens += max(1, len(str(content).split()))
                    yield str(content)
        total = time.perf_counter() - started
        self.metrics_history.append(
            TokenMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                ttft_seconds=first_token,
                total_seconds=total,
                tokens_per_second=completion_tokens / total if total else 0,
                thinking_mode=(
                    getattr(self.config.generation_profiles, profile).thinking
                    if profile is not None
                    else thinking
                ),
            )
        )

    def structured_chat(
        self,
        messages: Sequence[ChatMessage],
        schema: type[StructuredT],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> StructuredT:
        first = self.chat(messages, thinking=thinking, profile=profile)

        def retry(correction: str) -> str:
            corrected = [*messages, ChatMessage(role="system", content=correction)]
            return self.chat(
                corrected, thinking=thinking, profile=profile
            ).content

        return parse_with_one_retry(first.content, schema, retry)

    def health_check(self) -> bool:
        try:
            response = self.client.get(
                f"{str(self.config.endpoint).rstrip('/')}/models",
                headers=self._headers(),
            )
            return response.is_success
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
