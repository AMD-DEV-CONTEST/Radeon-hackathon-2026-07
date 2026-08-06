"""bge-reranker-v2-m3 cross-encoder wrapper (GPU).

Runs on GPU for low-latency online reranking during Agent search.
Lazy-loads the model so the module imports cleanly without GPU deps.

VRAM: ~1.5GB (0.6GB model + 0.9GB HIP context + allocator overhead).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import RerankerConfig

logger = logging.getLogger(__name__)


class RerankerModel:
    """Wraps bge-reranker-v2-m3 cross-encoder for GPU-based reranking."""

    def __init__(self, config: RerankerConfig) -> None:
        self.config = config
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import FlagReranker
            logger.info(
                "Loading reranker on %s: %s (~1.5GB VRAM expected)",
                self.config.device, self.config.model,
            )
            self._model = FlagReranker(
                self.config.model,
                use_fp16=True,  # FP16 inference for speed
            )
        except ImportError:
            logger.warning(
                "FlagEmbedding not installed; reranker will be skipped. "
                "Run: pip install FlagEmbedding"
            )
            self._model = "unavailable"
        return self._model

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.

        Returns list of ``(original_index, score)`` sorted by score descending,
        truncated to ``top_k`` (defaults to config.final_count).
        """
        if top_k is None:
            top_k = self.config.final_count

        model = self._load()
        if model == "unavailable":
            # Without reranker, return original order truncated
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]

        t0 = time.time()

        # Build query-document pairs
        pairs = [[query, doc] for doc in documents]
        scores = model.compute_score(pairs, normalize=True)

        # compute_score returns a single float for one pair, list for multiple
        if isinstance(scores, (int, float)):
            scores = [float(scores)]
        else:
            scores = [float(s) for s in scores]

        # Sort by score descending
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        elapsed = time.time() - t0
        logger.debug("Reranked %d candidates in %.3fs", len(documents), elapsed)

        return ranked[:top_k]

    def rerank_chunks(
        self,
        query: str,
        chunks: list[Any],  # list of CodeChunk or similar with .content
        top_k: int | None = None,
    ) -> list[Any]:
        """Rerank CodeChunk objects, returning the top_k most relevant."""
        if not chunks:
            return []

        documents = [getattr(c, "content", str(c))[:512] for c in chunks]
        ranked_indices = self.rerank(query, documents, top_k)
        return [chunks[idx] for idx, _ in ranked_indices]
