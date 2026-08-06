from rank_bm25 import BM25Okapi

from langchain.schema import Document


def build_bm25(chunks: list[Document]) -> tuple[BM25Okapi | None, list[Document]]:
    """Build a BM25 index over the given chunks. Cheap enough to rebuild
    on demand for hackathon-scale knowledge bases (hundreds of chunks).
    """
    if not chunks:
        return None, []
    tokenized = [c.page_content.lower().split() for c in chunks]
    return BM25Okapi(tokenized), chunks


def bm25_search(
    bm25: BM25Okapi, chunks: list[Document], query: str, k: int
) -> list[tuple[Document, float]]:
    scores = bm25.get_scores(query.lower().split())
    ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
    return ranked[:k]


def reciprocal_rank_fusion(
    bm25_results: list[tuple[Document, float]],
    embedding_results: list[tuple[Document, float]],
    k_constant: int = 60,
) -> list[Document]:
    """Combine two ranked lists by rank position rather than raw score —
    this avoids needing BM25 and cosine-similarity scores to be on a
    comparable scale, which is the main weakness of linear score fusion.
    """
    scores: dict[str, float] = {}
    doc_lookup: dict[str, Document] = {}

    for rank, (doc, _) in enumerate(bm25_results):
        key = doc.page_content
        scores[key] = scores.get(key, 0.0) + 1.0 / (k_constant + rank + 1)
        doc_lookup[key] = doc

    for rank, (doc, _) in enumerate(embedding_results):
        key = doc.page_content
        scores[key] = scores.get(key, 0.0) + 1.0 / (k_constant + rank + 1)
        doc_lookup[key] = doc

    ranked_keys = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [doc_lookup[key] for key, _ in ranked_keys]