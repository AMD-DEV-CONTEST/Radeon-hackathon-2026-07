import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class Reranker:
    """Cross-encoder reranker for refining vector search results."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """Initializes the Reranker.

        Args:
            model_name: CrossEncoder model identifier.
        """
        self.model_name = model_name
        self._model = None
        self._load_attempted = False

    def _load_model(self) -> Any:
        """Lazy-loads the CrossEncoder model when needed."""
        if not self._load_attempted:
            self._load_attempted = True
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name)
                logger.info(f"Loaded CrossEncoder reranker model: {self.model_name}")
            except Exception as e:
                logger.warning(f"Reranker model '{self.model_name}' unavailable: {e}. Fallback active.")
                self._model = None
        return self._model

    def rerank(self, query: str, results: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """Reranks search results by query relevance.

        Args:
            query: The search query text.
            results: List of candidate result dicts (each having 'text').
            top_k: Number of top results to return after reranking.

        Returns:
            List of reranked candidate dicts with 'rerank_score' attached.
        """
        if not results:
            return []

        model = self._load_model()
        if model is None:
            logger.warning("Reranker model unavailable. Returning top_k original results.")
            return results[:top_k]

        try:
            pairs = [[query, doc.get("text", "")] for doc in results]
            scores = model.predict(pairs)

            reranked_results = []
            for doc, score in zip(results, scores):
                doc_copy = dict(doc)
                doc_copy["rerank_score"] = float(score)
                reranked_results.append(doc_copy)

            reranked_results.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
            return reranked_results[:top_k]

        except Exception as e:
            logger.warning(f"Reranking failed: {e}. Returning top_k original results.")
            return results[:top_k]
