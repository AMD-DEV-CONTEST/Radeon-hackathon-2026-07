import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> List[str]:
    """Simple lowercase word tokenizer for BM25 indexing."""
    return re.findall(r"\w+", text.lower())


class HybridVectorStore:
    """Hybrid retrieval layer combining semantic vector search and BM25 lexical search."""

    def __init__(
        self,
        vector_store: Any,
        parent_store: Optional[Any] = None,
        semantic_weight: float = 0.5,
        bm25_weight: float = 0.5,
    ):
        """Initializes HybridVectorStore.

        Args:
            vector_store: VectorStore instance.
            parent_store: Optional ParentDocumentStore instance.
            semantic_weight: Weight for semantic rank fusion.
            bm25_weight: Weight for BM25 rank fusion.
        """
        self.vector_store = vector_store
        self.parent_store = parent_store
        self.semantic_weight = semantic_weight
        self.bm25_weight = bm25_weight

        self._corpus_docs: List[Dict[str, Any]] = []
        self._bm25_model = None
        self._bm25_available = True

    def index_documents(self, docs: List[Dict[str, Any]]) -> None:
        """Indexes document chunks into the BM25 corpus.

        Args:
            docs: List of dicts containing 'text' and 'metadata'.
        """
        if not docs:
            return

        self._corpus_docs = list(docs)
        tokenized_corpus = [_tokenize(doc.get("text", "")) for doc in self._corpus_docs]

        try:
            from rank_bm25 import BM25Okapi
            self._bm25_model = BM25Okapi(tokenized_corpus)
            self._bm25_available = True
            logger.info(f"Indexed {len(docs)} documents into BM25 index.")
        except ImportError:
            logger.warning("rank-bm25 not installed. BM25 lexical search will be skipped.")
            self._bm25_available = False
            self._bm25_model = None
        except Exception as e:
            logger.error(f"Error initializing BM25 index: {e}")
            self._bm25_available = False
            self._bm25_model = None

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Performs hybrid retrieval using RRF (Reciprocal Rank Fusion).

        Args:
            query: Search query text.
            top_k: Number of final results to return.
            filters: Optional metadata filters.
            k: Optional alias for top_k.

        Returns:
            Combined and deduplicated list of top_k results.
        """
        effective_k = k if k is not None else top_k
        fetch_k = effective_k * 3

        # 1. Semantic Search
        semantic_results = self.vector_store.search(query, top_k=fetch_k, filters=filters)

        # 2. BM25 Search
        bm25_results: List[Dict[str, Any]] = []
        if self._bm25_available and self._bm25_model and self._corpus_docs:
            try:
                tokenized_query = _tokenize(query)
                scores = self._bm25_model.get_scores(tokenized_query)

                scored_corpus = []
                for idx, (doc, score) in enumerate(zip(self._corpus_docs, scores)):
                    meta = doc.get("metadata", {})
                    # Apply filters if provided
                    if filters:
                        match = True
                        for fk, fv in filters.items():
                            if meta.get(fk) != fv:
                                match = False
                                break
                        if not match:
                            continue

                    scored_corpus.append({
                        "id": f"bm25_{idx}",
                        "text": doc.get("text", ""),
                        "metadata": meta,
                        "bm25_score": float(score),
                    })

                scored_corpus.sort(key=lambda x: x.get("bm25_score", 0.0), reverse=True)
                bm25_results = scored_corpus[:fetch_k]
            except Exception as e:
                logger.warning(f"BM25 search failed: {e}")
                bm25_results = []

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        # Semantic ranking
        for rank, res in enumerate(semantic_results):
            key = res.get("text", "").strip()
            if not key:
                continue
            doc_map[key] = res
            rrf_scores[key] = rrf_scores.get(key, 0.0) + self.semantic_weight / (60 + rank + 1)

        # BM25 ranking
        for rank, res in enumerate(bm25_results):
            key = res.get("text", "").strip()
            if not key:
                continue
            if key not in doc_map:
                doc_map[key] = res
            rrf_scores[key] = rrf_scores.get(key, 0.0) + self.bm25_weight / (60 + rank + 1)

        # 4. Sort by RRF score
        sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)

        final_results = []
        for key in sorted_keys[:effective_k]:
            item = dict(doc_map[key])
            item["rrf_score"] = rrf_scores[key]
            final_results.append(item)

        # 5. Enrich with parent context if available
        if self.parent_store:
            final_results = self.parent_store.enrich_results_with_parent(final_results)

        return final_results
