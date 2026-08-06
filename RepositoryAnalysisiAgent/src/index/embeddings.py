"""BGE-m3 embedding model wrapper (CPU).

Lazy-loads sentence-transformers so the module imports cleanly
on machines without the GPU stack installed.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import EmbeddingConfig

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Wraps BGE-m3 for generating text embeddings on CPU."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import BGEM3FlagModel
            logger.info("Loading BGE-m3 on %s: %s", self.config.device, self.config.model)
            self._model = BGEM3FlagModel(
                self.config.model,
                use_fp16=self.config.device != "cpu",
            )
        except ImportError:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("Falling back to sentence-transformers: %s", self.config.model)
                self._model = SentenceTransformer(
                    self.config.model, device=self.config.device
                )
            except ImportError:
                raise ImportError(
                    "Neither FlagEmbedding nor sentence-transformers is installed. "
                    "Run: pip install FlagEmbedding sentence-transformers"
                )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning float vectors."""
        model = self._load()
        if hasattr(model, "encode"):
            result = model.encode(
                texts,
                batch_size=self.config.batch_size,
                max_length=8192,
            )
            # BGEM3FlagModel.encode returns a dict with 'dense_vecs'
            if isinstance(result, dict) and "dense_vecs" in result:
                return result["dense_vecs"].tolist()
            if hasattr(result, "tolist"):
                return result.tolist()
            return list(result)
        return []

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        vectors = self.embed([text])
        return vectors[0] if vectors else []

    @property
    def dimension(self) -> int:
        """Return embedding dimension (BGE-m3 = 1024)."""
        return 1024
