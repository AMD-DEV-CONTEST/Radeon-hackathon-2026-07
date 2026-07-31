"""
Local embedding model wrapper.

Uses sentence-transformers, which will place tensors on the AMD Radeon GPU
automatically when a ROCm-enabled PyTorch build is installed (ROCm exposes
its devices under the same `cuda` device string that PyTorch already uses,
so no code changes are needed vs. an NVIDIA setup — see README).
"""
from __future__ import annotations

import logging
from typing import List

from sentence_transformers import SentenceTransformer

import config

logger = logging.getLogger(__name__)


class LocalEmbedder:
    """Generates embeddings locally, with automatic GPU fallback to CPU."""

    def __init__(
        self,
        model_name: str = config.EMBEDDING_MODEL_NAME,
        device: str = config.EMBEDDING_DEVICE,
    ) -> None:
        try:
            self._model = SentenceTransformer(model_name, device=device)
            logger.info("Loaded embedding model '%s' on device '%s'", model_name, device)
        except Exception as exc:
            logger.warning(
                "Falling back to CPU for embeddings (device '%s' unavailable: %s)",
                device,
                exc,
            )
            self._model = SentenceTransformer(model_name, device="cpu")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self._model.encode([text], normalize_embeddings=True)[0].tolist()
