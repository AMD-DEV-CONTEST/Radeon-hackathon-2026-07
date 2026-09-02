"""Hybrid retrieval: FAISS + BM25 with RRF merging.

Retriever wraps a ProjectIndex and exposes ``search()`` which returns
the top 4–6 ``Evidence`` objects from a dual‑index hybrid search.
"""

from __future__ import annotations

from app.rag.indexer import ProjectIndex
from app.rag.manifest import ContentChunk
from app.schemas.models import Evidence

RRF_K = 60


class Retriever:
    """Hybrid FAISS + BM25 retriever with RRF merging."""

    def __init__(self, index: ProjectIndex):
        self._index = index

    @property
    def index(self) -> ProjectIndex:
        return self._index

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.35,
        bm25_only: bool = False,
    ) -> list[Evidence]:
        """Return top‑k evidence items using hybrid recall + RRF.

        Args:
            query: Natural language question or search string.
            top_k: Number of evidence items to return (typically 4–6).
            min_score: Minimum normalized score threshold (0–1).
                       When > 0, evidence below this score is filtered out.
                       Default 0.0 passes all results.
            bm25_only: When True, use BM25 keyword search only (no FAISS).
                       Useful for testing with non‑semantic mock embeddings.

        Returns:
            Evidence list, or empty list when no results pass threshold.
        """
        if not query.strip() or not self._index.is_built():
            return []

        if bm25_only:
            bm25_hits = self._index.bm25_search(query, k=top_k)
            evidence_list: list[Evidence] = []
            # Normalize BM25 scores to [0, 1] range for Evidence model
            max_bm25 = max((s for _, s in bm25_hits), default=1.0)
            for chunk_idx, score in bm25_hits:
                chunk = self._index.get_chunk(chunk_idx)
                if chunk is None:
                    continue
                normalized = score / max_bm25 if max_bm25 > 0 else score
                evidence_list.append(
                    _to_evidence(chunk, chunk_idx, round(normalized, 4))
                )
            return evidence_list

        # Wide recall from both methods
        faiss_hits = self._index.faiss_search(query, k=top_k * 3)
        bm25_hits = self._index.bm25_search(query, k=top_k * 3)

        # Dense search always returns neighbours.  With no lexical evidence,
        # require a meaningful raw cosine score before treating them as proof.
        best_dense_score = max((score for _, score in faiss_hits), default=0.0)
        if not bm25_hits and best_dense_score < min_score:
            return []

        # RRF merge
        merged = self._rrf_merge(faiss_hits, bm25_hits, k=top_k)

        # Score‑threshold filtering
        # Build Evidence list
        evidence_list: list[Evidence] = []
        for chunk_idx, score in merged:
            chunk = self._index.get_chunk(chunk_idx)
            if chunk is None:
                continue
            evidence_list.append(_to_evidence(chunk, chunk_idx, score))

        return evidence_list

    def _rrf_merge(
        self,
        faiss_hits: list[tuple[int, float]],
        bm25_hits: list[tuple[int, float]],
        k: int,
    ) -> list[tuple[int, float]]:
        """Reciprocal Rank Fusion — merge two ranked lists."""
        score_map: dict[int, float] = {}

        for rank, (idx, _) in enumerate(faiss_hits):
            score_map[idx] = score_map.get(idx, 0) + 1.0 / (RRF_K + rank + 1)

        for rank, (idx, _) in enumerate(bm25_hits):
            score_map[idx] = score_map.get(idx, 0) + 1.0 / (RRF_K + rank + 1)

        sorted_items = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
        result = sorted_items[:k]

        # Normalise to [0, 1]
        if result:
            max_score = max(s for _, s in result)
            return [(idx, s / max_score) for idx, s in result]
        return []


def _to_evidence(chunk: ContentChunk, idx: int, score: float) -> Evidence:
    """Convert a ContentChunk + score into an Evidence model."""
    locator = _build_locator(chunk)
    excerpt = chunk.content[:200]
    if len(chunk.content) > 200:
        excerpt += "..."

    return Evidence(
        evidence_id=f"{chunk.relative_path}#c{idx}",
        relative_path=chunk.relative_path,
        locator=locator,
        excerpt=excerpt,
        score=round(score, 4),
    )


def _build_locator(chunk: ContentChunk) -> str:
    """Human‑readable location string for a chunk."""
    parts: list[str] = []

    if chunk.heading_path:
        parts.append(chunk.heading_path)

    if chunk.page_number is not None:
        parts.append(f"p.{chunk.page_number}")

    if chunk.sheet_name:
        parts.append(f"sheet:{chunk.sheet_name}")
        if chunk.cell_range:
            parts.append(f"cells:{chunk.cell_range}")

    if not parts:
        parts.append(f"lines {chunk.line_start}-{chunk.line_end}")

    return "  ".join(parts)
