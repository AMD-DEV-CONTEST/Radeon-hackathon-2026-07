from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

import httpx

from .utils import tokenize


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class HashEmbedding:
    """A deterministic local baseline used for tests and CPU-only development."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self.model_id = f"hash-embedding-v1-{dimension}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        return _normalize(vector)

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class OpenAICompatibleEmbedding:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self.timeout = timeout

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model_id, "input": list(texts)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda item: item["index"])
        return [_normalize(list(map(float, row["embedding"]))) for row in rows]

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right))

