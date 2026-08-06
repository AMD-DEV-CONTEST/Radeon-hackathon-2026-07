from sentence_transformers import CrossEncoder

from langchain.schema import Document

from .config import RERANKER_MODEL_NAME

_reranker: CrossEncoder | None = None


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(RERANKER_MODEL_NAME)
    return _reranker


def rerank(
    question: str, docs: list[Document], top_k: int = 5
) -> list[tuple[Document, float]]:
    """Rerank fused BM25+embedding candidates with a cross-encoder.

    Returns (doc, score) pairs — the score is surfaced in the CLI's JSON
    output so downstream consumers (the agent, the UI debug panel) can
    show a believable relevance number, not just a ranked list.
    """
    if not docs:
        return []
    reranker = get_reranker()
    pairs = [[question, d.page_content] for d in docs]
    scores = reranker.predict(pairs)
    scored = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [(doc, float(score)) for doc, score in scored[:top_k]]