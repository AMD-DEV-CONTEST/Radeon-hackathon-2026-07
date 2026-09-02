"""Embedding generation for RAG chunks.

Uses the LLM‑compatible ``/v1/embeddings`` endpoint by default.
For local testing without a running LLM server, a deterministic
``HashEmbedder`` is provided.
"""

from __future__ import annotations

import hashlib
import asyncio
from typing import Protocol

import numpy as np


class EmbedderInterface(Protocol):
    """Minimal embedding interface for swapping implementations."""

    def embed(self, texts: list[str]) -> np.ndarray: ...

    @property
    def dim(self) -> int: ...


class LLMEmbedder:
    """Generate embeddings via OpenAI‑compatible ``/v1/embeddings``."""

    def __init__(
        self, base_url: str, model: str, timeout: int = 30, *, project_id: str = "default", settings=None
    ):
        self._base = str(base_url).rstrip("/")
        self._model = model
        self._timeout = timeout
        self._cached_dim: int | None = None
        self._project_id = project_id
        self._settings = settings

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([], dtype=np.float32)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("LLMEmbedder.embed must run from the synchronous project-index worker")

        from app.services.task_queue import get_task_queue

        data = asyncio.run(
            get_task_queue(self._settings).enqueue_embedding(
                project_id=self._project_id,
                cancel_event=asyncio.Event(),
                callable=self._embed_request,
                texts=texts,
            )
        )
        vectors = [item["embedding"] for item in data["data"]]
        emb = np.array(vectors, dtype=np.float32)
        self._cached_dim = emb.shape[1]
        return emb

    async def _embed_request(self, *, texts: list[str]) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout + 5) as client:
            response = await client.post(
                f"{self._base}/embeddings",
                json={"input": texts, "model": self._model},
            )
            response.raise_for_status()
            return response.json()

    @property
    def dim(self) -> int:
        if self._cached_dim is not None:
            return self._cached_dim
        # Warm‑up call to discover dimension
        test = self.embed(["dim probe"])
        return test.shape[1]


class HashEmbedder:
    """Deterministic embedder for testing — no server needed.

    Produces fixed‑dimensional vectors from text via SHA‑256 hash,
    so the same text always maps to the same vector.
    """

    def __init__(self, dim: int = 384):
        self._dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([], dtype=np.float32)
        vectors = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, txt in enumerate(texts):
            # Generate a deterministic vector from text hash
            h = hashlib.sha256(txt.encode("utf-8")).digest()
            # Clip seed to 32-bit range for RandomState compatibility
            seed = int.from_bytes(h[:4], "big")
            rng = np.random.RandomState(seed)
            v = rng.randn(self._dim).astype(np.float32)
            # L2‑normalize for cosine similarity
            norm = np.linalg.norm(v) or 1.0
            vectors[i] = v / norm
        return vectors

    @property
    def dim(self) -> int:
        return self._dim


def create_embedder(
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 30,
    *,
    mock_dim: int | None = None,
    project_id: str = "default",
    settings=None,
) -> EmbedderInterface:
    """Factory: return LLMEmbedder or HashEmbedder."""
    if mock_dim is not None:
        return HashEmbedder(dim=mock_dim)

    from app.config import Settings  # noqa: PLC0415

    settings = settings or Settings()
    return LLMEmbedder(
        base_url=base_url or settings.embedding_base_url,
        model=model or settings.llm_model,
        timeout=timeout,
        project_id=project_id,
        settings=settings,
    )
