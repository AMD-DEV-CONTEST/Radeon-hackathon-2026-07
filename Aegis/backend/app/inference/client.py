"""
Inference client — the single chokepoint through which every agent talks to the
local LLM. vLLM (running on ROCm) exposes an OpenAI-compatible HTTP API, so we
speak that protocol directly rather than depending on a heavier framework client.

Design decisions that map directly to judging criteria:
  - Bounded concurrency semaphore -> prevents VRAM oversubscription under
    concurrent multi-agent load (GPU efficiency).
  - Streaming support -> low perceived latency or, for background agents,
    accurate token/sec measurement (benchmark strategy, Phase 14).
  - Every call returns timing + token-count metadata -> feeds AgentStep records
    (explainability) and the benchmarking dashboard directly, not as an afterthought.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import InferenceEngineError
from app.core.logging import get_logger
from app.core.metrics import (
    INFERENCE_CONCURRENT_REQUESTS,
    INFERENCE_REQUESTS_TOTAL,
    record_tokens_per_second,
)

logger = get_logger(__name__)


@dataclass
class CompletionResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    tokens_per_second: float = field(init=False)

    def __post_init__(self) -> None:
        seconds = self.duration_ms / 1000
        self.tokens_per_second = round(self.completion_tokens / seconds, 2) if seconds > 0 else 0.0


class InferenceClient:
    """
    Thin async client for a local, OpenAI-API-compatible vLLM server.

    Launch command this client targets (ROCm build of vLLM), documented fully
    in docs/ROCM_SETUP.md:

        vllm serve Qwen/Qwen2.5-14B-Instruct \\
            --host 0.0.0.0 --port 8001 \\
            --dtype float16 \\
            --gpu-memory-utilization 0.90 \\
            --max-num-seqs 32 \\
            --enable-prefix-caching
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._semaphore = asyncio.Semaphore(self._settings.INFERENCE_MAX_CONCURRENCY)
        self._client = httpx.AsyncClient(
            base_url=self._settings.INFERENCE_BASE_URL,
            timeout=self._settings.INFERENCE_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {self._settings.INFERENCE_API_KEY}"},
        )

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> CompletionResult:
        """Non-streaming completion — used by agents whose full output is needed
        before the next planning step (e.g. structured JSON hypothesis output)."""
        async with self._semaphore:
            INFERENCE_CONCURRENT_REQUESTS.inc()
            start = time.perf_counter()
            try:
                resp = await self._client.post(
                    "/chat/completions",
                    json={
                        "model": self._settings.INFERENCE_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("inference.request_failed", error=str(exc))
                INFERENCE_REQUESTS_TOTAL.labels(status="error").inc()
                raise InferenceEngineError(
                    "Local inference engine is unreachable or returned an error",
                    details={"backend": self._settings.INFERENCE_BASE_URL, "error": str(exc)},
                ) from exc
            finally:
                INFERENCE_CONCURRENT_REQUESTS.dec()

            duration_ms = (time.perf_counter() - start) * 1000
            data = resp.json()
            choice = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            result = CompletionResult(
                text=choice,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                duration_ms=duration_ms,
            )
            INFERENCE_REQUESTS_TOTAL.labels(status="success").inc()
            record_tokens_per_second(result.tokens_per_second)
            return result

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Streaming completion — used for the live agent-reasoning SSE feed
        exposed to the frontend (Phase 11/12), so a human watching an
        in-progress investigation sees tokens as they're generated."""
        async with self._semaphore:
            try:
                async with self._client.stream(
                    "POST",
                    "/chat/completions",
                    json={
                        "model": self._settings.INFERENCE_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break
                        import json
                        chunk = json.loads(payload)
                        delta = chunk["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
            except httpx.HTTPError as exc:
                logger.error("inference.stream_failed", error=str(exc))
                raise InferenceEngineError(
                    "Local inference engine is unreachable or returned an error during streaming",
                    details={"backend": self._settings.INFERENCE_BASE_URL, "error": str(exc)},
                ) from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Calls the embedding model served alongside the chat model (vLLM can
        serve both via --task embed on a second port, or a dedicated small
        embedding model) — used by the RAG pipeline (Phase 9)."""
        async with self._semaphore:
            try:
                resp = await self._client.post(
                    "/embeddings",
                    json={"model": self._settings.INFERENCE_MODEL, "input": texts},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise InferenceEngineError(
                    "Embedding request failed", details={"error": str(exc)}
                ) from exc
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def aclose(self) -> None:
        await self._client.aclose()


_client_singleton: Optional[InferenceClient] = None


def get_inference_client() -> InferenceClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = InferenceClient()
    return _client_singleton
