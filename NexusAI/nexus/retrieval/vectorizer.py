from dataclasses import dataclass
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize

@dataclass
class VectorResult:
    vectors: np.ndarray
    dimension: int

class LocalSemanticVectorizer:
    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.vectorizer = HashingVectorizer(
            n_features=dimension,
            alternate_sign=False,
            norm=None,
            lowercase=True,
            ngram_range=(1, 2),
        )

    def encode(self, texts: list[str]) -> VectorResult:
        if not texts:
            return VectorResult(np.empty((0, self.dimension)), self.dimension)
        matrix = self.vectorizer.transform(texts)
        matrix = normalize(matrix, norm="l2", axis=1)
        return VectorResult(matrix.toarray().astype("float32"), self.dimension)
