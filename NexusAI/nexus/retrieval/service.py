from dataclasses import dataclass
import numpy as np
from nexus.retrieval.vectorizer import LocalSemanticVectorizer

@dataclass
class SearchHit:
    index: int
    score: float

class SemanticRetriever:
    def __init__(self, dimension: int = 768):
        self.vectorizer = LocalSemanticVectorizer(dimension)

    def search(self, query: str, documents: list[str], top_k: int = 5) -> list[SearchHit]:
        if not query.strip() or not documents:
            return []

        encoded = self.vectorizer.encode([query, *documents]).vectors
        query_vector = encoded[0]
        document_vectors = encoded[1:]
        scores = document_vectors @ query_vector

        ranked = np.argsort(scores)[::-1][:max(1, top_k)]
        return [
            SearchHit(index=int(i), score=float(scores[i]))
            for i in ranked
            if scores[i] > 0
        ]
