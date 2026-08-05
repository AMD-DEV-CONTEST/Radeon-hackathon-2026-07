from __future__ import annotations

from collections import Counter
from hashlib import sha256
import math
import re


TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{2,}")


class LocalEmbeddingEngine:
    """A lightweight, deterministic, fully offline embedding engine.

    It is intentionally pure Python so the project remains installable on
    Python 3.13 without any compiler toolchain.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        text = (text or "").lower().strip()
        if not text:
            return [0.0] * self.dimensions

        tokens = TOKEN_RE.findall(text)
        char_ngrams = [text[i : i + 3] for i in range(max(0, len(text) - 2))]
        counts = Counter(tokens + char_ngrams)
        vector = [0.0] * self.dimensions

        for token, weight in counts.items():
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign * float(weight)

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [round(value / norm, 8) for value in vector]
