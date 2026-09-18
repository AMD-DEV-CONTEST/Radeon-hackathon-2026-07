"""Reciprocal-rank fusion."""

from buildguard.rag.schemas import ScoredChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[ScoredChunk]],
    *,
    rrf_k: int = 60,
    top_k: int = 15,
) -> list[ScoredChunk]:
    if rrf_k <= 0 or top_k <= 0:
        raise ValueError("rrf_k and top_k must be positive")
    scores: dict[str, float] = {}
    chunks = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            chunk_id = item.chunk.chunk_id
            chunks[chunk_id] = item.chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return [
        ScoredChunk(
            chunk=chunks[chunk_id],
            score=scores[chunk_id],
            rank=rank,
            source="fusion",
        )
        for rank, chunk_id in enumerate(ordered[:top_k], start=1)
    ]

