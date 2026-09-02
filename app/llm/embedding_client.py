"""Stage J — Separate Embedding Model Client.

Uses a dedicated, smaller embedding model (e.g. bge-small-en-v1.5) served via
its own llama.cpp / OpenAI-compatible endpoint so that the 35B chat model and
the embedding model do not compete for the same VRAM.

This module mirrors the structure of ``app/llm/client.py`` but targets the
embedding endpoint exclusively.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("projectpack.embedding")


class EmbeddingClient:
    """Async client for a dedicated embedding model endpoint.

    Communicates via OpenAI-compatible ``/v1/embeddings`` and returns
    numpy-style float lists.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._base_url = str(settings.embedding_base_url).rstrip("/")
        self._model = settings.embedding_model
        self._timeout = settings.embedding_timeout_seconds
        self._transport = transport

        # Metrics
        self._request_count: int = 0
        self._error_count: int = 0
        self._total_tokens: int = 0
        self._total_latency_ms: float = 0.0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for *texts*.

        Args:
            texts: One or more input strings (batch embedding).

        Returns:
            A list of float-lists, same length as *texts*.
        """
        if not texts:
            return []

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    json={
                        "model": self._model,
                        "input": texts,
                    },
                )
                response.raise_for_status()
                data = response.json()

                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._request_count += 1
                self._total_latency_ms += elapsed_ms

                embeddings: list[list[float]] = [
                    item["embedding"] for item in data["data"]
                ]
                if data.get("usage"):
                    self._total_tokens += data["usage"].get("total_tokens", 0)

                logger.debug(
                    "Embedding request completed: %d texts, %.0f ms",
                    len(texts),
                    elapsed_ms,
                )
                return embeddings
        except httpx.HTTPStatusError as exc:
            self._error_count += 1
            logger.error("Embedding HTTP error %d: %s", exc.response.status_code, exc)
            raise RuntimeError(
                f"Embedding service returned {exc.response.status_code}"
            ) from exc
        except httpx.TimeoutException as exc:
            self._error_count += 1
            logger.error("Embedding request timed out after %.1fs", self._timeout)
            raise RuntimeError("Embedding service timed out") from exc
        except Exception as exc:
            self._error_count += 1
            logger.error("Embedding request failed: %s", exc)
            raise

    async def health(self) -> dict[str, Any]:
        """Check if the embedding endpoint is reachable."""
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=5.0
            ) as client:
                response = await client.get(f"{self._base_url[:-3]}/health")
                is_healthy = response.status_code == 200
        except Exception:
            is_healthy = False

        return {
            "healthy": is_healthy,
            "base_url": self._base_url,
            "model": self._model,
            "request_count": self._request_count,
            "error_count": self._error_count,
            "avg_latency_ms": round(
                self._total_latency_ms / max(self._request_count, 1), 1
            ),
            "total_tokens": self._total_tokens,
        }

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "request_count": self._request_count,
            "error_count": self._error_count,
            "error_rate": round(
                self._error_count / max(self._request_count, 1) * 100, 1
            ),
            "avg_latency_ms": round(
                self._total_latency_ms / max(self._request_count, 1), 1
            ),
            "total_tokens": self._total_tokens,
        }


# Module-level singleton
_embedding_client: EmbeddingClient | None = None


def get_embedding_client(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EmbeddingClient:
    """Return the module-level EmbeddingClient singleton."""
    global _embedding_client
    if _embedding_client is None:
        if settings is None:
            settings = Settings()
        _embedding_client = EmbeddingClient(settings, transport=transport)
    return _embedding_client
