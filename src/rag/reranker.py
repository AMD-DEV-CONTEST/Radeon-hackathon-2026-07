"""Cross-Encoder reranking: precisely re-rank the top-K retrieval results to select the most relevant top-N.

Reference the LLMReranker + JinaReranker in lesson 8 reranking.py.
Difference between Cross-Encoder and Bi-Encoder (vector retrieval):
- Bi-Encoder: query and doc are encoded independently and retrieved via vector distance (fast but coarse)
- Cross-Encoder: query and doc are concatenated and jointly encoded, giving higher precision (slow but accurate)

This module supports two reranking approaches:
1. Cross-Encoder model (sentence-transformers, local inference)
2. LLM-based reranking (called through the Agently Agent, better compatibility)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """A reranker based on the Cross-Encoder model.

    Uses sentence-transformers' CrossEncoder to score query-doc pairs.
    Compared to the Bi-Encoder used in vector retrieval, Cross-Encoder can capture finer-grained semantic interactions.

    Recommended models:
    - BAAI/bge-reranker-base (Chinese + English, lightweight)
    - BAAI/bge-reranker-large (Chinese + English, higher precision)
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model_name = model_name
        self._model = None
        self._available = False

        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            self._model = CrossEncoder(model_name)
            self._available = True
            logger.info("Cross-Encoder reranker loaded: %s", model_name)
        except ImportError:
            logger.warning(
                "sentence-transformers not installed, Cross-Encoder reranking unavailable. "
                "pip install sentence-transformers"
            )
        except Exception as e:
            logger.warning("Cross-Encoder model loading failed: %s", e)

    @property
    def available(self) -> bool:
        return self._available

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_n: int = 5,
    ) -> list[dict]:
        """Perform Cross-Encoder reranking on the candidate list.

        Args:
            query: the user query
            candidates: the retrieval candidate list (each candidate needs a chunk_text or content field)
            top_n: the top-N count returned after reranking

        Returns:
            the reranked top-N candidate list (descending by relevance)
        """
        if not self._available or not candidates:
            logger.warning("Cross-Encoder unavailable or candidates empty, skipping reranking")
            return candidates[:top_n]

        # build the query-doc pairs
        pairs = []
        for c in candidates:
            text = c.get("chunk_text") or c.get("content") or ""
            pairs.append((query, text))

        # Cross-Encoder scoring
        scores = self._model.predict(pairs)

        # attach the scores to the candidates
        for c, score in zip(candidates, scores):
            c["rerank_score"] = float(score)

        # sort in descending order of rerank score
        reranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0), reverse=True)

        logger.info(
            "Cross-Encoder reranking: %d candidates → top-%d (highest score: %.4f)",
            len(candidates), top_n,
            reranked[0].get("rerank_score", 0) if reranked else 0,
        )

        return reranked[:top_n]


class LLMReranker:
    """An LLM-based reranker (fallback approach).

    When the Cross-Encoder model is unavailable, use the LLM to score candidate relevance.
    Reference the LLMReranker.rerank_documents method in lesson 8 reranking.py.
    """

    def __init__(self, chat_agent: Any = None):
        self.chat_agent = chat_agent

    async def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_n: int = 5,
    ) -> list[dict]:
        """Use the LLM to score and rerank the candidates by relevance.

        Args:
            query: the user query
            candidates: the retrieval candidate list
            top_n: return top-N

        Returns:
            the reranked top-N candidate list
        """
        if not self.chat_agent or not candidates:
            return candidates[:top_n]

        # build the LLM input
        doc_texts = []
        for i, c in enumerate(candidates):
            text = c.get("chunk_text") or c.get("content") or ""
            # truncate to avoid an overly long input
            doc_texts.append(f"[Doc {i + 1}] {text[:300]}")

        try:
            result = await (
                self.chat_agent
                .input({
                    "query": query,
                    "documents": doc_texts,
                })
                .instruct(
                    "You are a document relevance assessment expert. Score each document's relevance to the query (0-10). "
                    "Return only a JSON-formatted list of scores, e.g.: {\"scores\": [8.5, 3.2, 9.1]}"
                )
                .output({
                    "scores": ([float], "the relevance score of each document (0-10), ordered as the input", "not_null"),
                }, format="json")
                .async_start()
            )

            scores = result.get("scores", [])
            # pad the scores (the LLM may return an incomplete list)
            while len(scores) < len(candidates):
                scores.append(0.0)

            for c, score in zip(candidates, scores):
                c["rerank_score"] = float(score)

            reranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0), reverse=True)

            logger.info(
                "LLM reranking: %d candidates → top-%d (highest score: %.1f)",
                len(candidates), top_n,
                reranked[0].get("rerank_score", 0) if reranked else 0,
            )

            return reranked[:top_n]

        except Exception as e:
            logger.warning("LLM reranking failed, returning the original order: %s", e)
            return candidates[:top_n]


def create_reranker(
    prefer_cross_encoder: bool = True,
    chat_agent: Any = None,
    model_name: str = "BAAI/bge-reranker-base",
) -> CrossEncoderReranker | LLMReranker:
    """Factory function: prefer Cross-Encoder, fall back to LLM reranking when unavailable.

    Args:
        prefer_cross_encoder: whether to prefer Cross-Encoder
        chat_agent: the LLM Agent (used for the LLM reranking fallback)
        model_name: the Cross-Encoder model name

    Returns:
        a reranker instance
    """
    if prefer_cross_encoder:
        reranker = CrossEncoderReranker(model_name=model_name)
        if reranker.available:
            return reranker
        logger.info("Cross-Encoder unavailable, falling back to LLM reranking")

    return LLMReranker(chat_agent=chat_agent)