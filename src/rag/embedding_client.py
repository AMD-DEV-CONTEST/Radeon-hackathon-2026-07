"""Call the embedding service directly over HTTP, bypassing Agently response-format uncertainty.

Root cause:
  The Agently embedding agent's return format is unstable — it may be a full OpenAI response dict
  {'data': [{'embedding': [...], 'index': 0}, ...], 'model': '...', 'usage': {...}},
  or a data-field list, or a bare vector list. This causes np.array(all_embeddings, dtype=np.float32)
  to raise TypeError: float() argument must be a string or a real number, not 'dict'.

Solution:
  DirectEmbeddingAgent mimics the Agently agent's chained .input(texts).async_start() interface,
  and internally calls the /v1/embeddings endpoint directly via httpx, uniformly parsing to list[list[float]].

Compatibility:
  - text-embeddings-router (HuggingFace TEI)
  - sentence_transformers FastAPI fallback server
  - any OpenAI /v1/embeddings compatible endpoint
"""
from __future__ import annotations

import logging
from typing import Sequence

import httpx

logger = logging.getLogger(__name__)


class _EmbeddingRequest:
    """Mimic Agently chained call: agent.input(texts).async_start().

    async_start() returns list[list[float]] — each element is the embedding vector of one text.
    No normalization is performed; the caller handles it (build_index.py batch normalizes, retriever.py per-item normalizes).
    """

    def __init__(self, agent: "DirectEmbeddingAgent", texts: list[str]):
        self._agent = agent
        self._texts = texts

    async def async_start(self) -> list[list[float]]:
        """Call the embedding API and return the raw vector list (unnormalized)."""
        client = await self._agent._ensure_client()
        model = self._agent.model
        batch_size = self._agent.batch_size
        all_vectors: list[list[float]] = []

        for i in range(0, len(self._texts), batch_size):
            batch = self._texts[i : i + batch_size]
            resp = await client.post(
                "/embeddings",
                json={"input": batch, "model": model},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Embedding API returned HTTP {resp.status_code}: {resp.text[:500]}"
                )

            data = resp.json()

            # OpenAI standard format: {"data": [{"embedding": [...], "index": 0}, ...], ...}
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
            elif isinstance(data, list):
                items = data
            else:
                raise RuntimeError(f"Embedding response format unexpected: {type(data).__name__}")

            for item in items:
                if isinstance(item, dict) and "embedding" in item:
                    vec = item["embedding"]
                elif isinstance(item, (list, tuple)):
                    vec = item
                else:
                    raise RuntimeError(
                        f"Embedding vector format unexpected: {type(item).__name__} = {str(item)[:100]}"
                    )
                all_vectors.append([float(v) for v in vec])

            logger.debug(
                "Embedding batch %d/%d complete (%d items)",
                (i // batch_size) + 1,
                (len(self._texts) + batch_size - 1) // batch_size,
                len(batch),
            )

        if not all_vectors:
            raise RuntimeError("Embedding service returned an empty result")

        return all_vectors


class DirectEmbeddingAgent:
    """Drop-in replacement for the Agently embedding agent.

    Uses httpx to call the embedding service directly, removing Agently response-format uncertainty.

    Interface compatibility:
      result = await agent.input(texts).async_start()
      # result: list[list[float]], each element is the vector of one text

    Usage (identical to the Agently agent):
      agent = DirectEmbeddingAgent(base_url, model, api_key)
      vectors = await agent.input(["hello", "world"]).async_start()
      # vectors = [[0.1, 0.2, ...], [0.3, 0.4, ...]]
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        batch_size: int = 32,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or "Empty-key-for-local-embed"
        self.batch_size = batch_size
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily create the httpx client (initialized on first call, ensuring it runs inside the event loop)."""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    def input(self, texts: str | Sequence[str]) -> _EmbeddingRequest:
        """Chained-call entry point, returns an _EmbeddingRequest object.

        Fully identical to the Agently agent.input() interface.
        """
        texts_list = list(texts) if isinstance(texts, (list, tuple)) else [texts]
        return _EmbeddingRequest(self, texts_list)

    async def close(self):
        """Close the httpx client and release the connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
