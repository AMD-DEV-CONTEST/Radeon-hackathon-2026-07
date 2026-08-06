"""Small local vector memory with an optional FAISS upgrade."""
from __future__ import annotations
import hashlib
import math
import re
from collections import Counter

class LocalMemory:
    def __init__(self) -> None:
        self.documents: list[tuple[str, str, Counter[str]]] = []

    @staticmethod
    def _vector(text: str) -> Counter[str]:
        return Counter(re.findall(r"[a-z]{2,}", text.lower()))

    def add(self, project_id: str, text: str) -> None:
        self.documents = [doc for doc in self.documents if doc[0] != project_id]
        self.documents.append((project_id, text, self._vector(text)))

    def search(self, query: str, limit: int = 8) -> list[tuple[str, float, str]]:
        q = self._vector(query)
        q_size = math.sqrt(sum(value * value for value in q.values())) or 1
        result = []
        for project_id, text, vector in self.documents:
            denominator = q_size * (math.sqrt(sum(value * value for value in vector.values())) or 1)
            score = sum(q[key] * vector[key] for key in q) / denominator
            result.append((project_id, score, text[:180]))
        return sorted(result, key=lambda item: item[1], reverse=True)[:limit]
