"""Local embedding providers.

Production defaults to the local BGE-M3 path configured in ``.env``.  The
deterministic hashing provider exists for offline unit tests and bootstrap
validation; it never makes a network request.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Protocol, Sequence


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_.%-]+")


class EmbeddingProvider(Protocol):
    dimension: int
    name: str

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def tokenize(text: str) -> list[str]:
    compact = "".join(text.lower().split())
    single = TOKEN_PATTERN.findall(compact)
    bigrams = [
        compact[index : index + 2]
        for index in range(max(0, len(compact) - 1))
        if any("\u4e00" <= char <= "\u9fff" for char in compact[index : index + 2])
    ]
    return single + bigrams


class HashEmbeddingProvider:
    """Feature-hashing fallback used only when a model runtime is unavailable."""

    name = "local-hash-fallback"

    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            number = int.from_bytes(digest, "big")
            index = number % self.dimension
            vector[index] += -1.0 if number & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class BgeM3EmbeddingProvider:
    """SentenceTransformers wrapper with an explicit device switch."""

    name = "BAAI/bge-m3"

    def __init__(
        self,
        model_path: Path | str,
        *,
        device: str = "cpu",
        batch_size: int = 8,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install the 'local-models' extra in the Radeon Python 3.10 "
                "environment before selecting BGE-M3."
            ) from exc
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Local BGE-M3 path does not exist: {path}. Remote model IDs are "
                "not accepted by the production provider."
            )
        self._model = SentenceTransformer(str(path), device=device)
        self.dimension = int(self._model.get_sentence_embedding_dimension())
        self.batch_size = batch_size
        self.device = device

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]
