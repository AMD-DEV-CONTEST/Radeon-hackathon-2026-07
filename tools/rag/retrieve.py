from langchain.schema import Document

from .config import DEFAULT_KB_ID, DEFAULT_TOP_K, FUSION_K_CONSTANT
from .hybrid import bm25_search, build_bm25, reciprocal_rank_fusion
from .registry import chunks_as_documents, load_registry
from .reranker import rerank
from .store import load_index


class Retriever:
    """Hybrid BM25 + embedding retrieval with cross-encoder reranking.

    This is the class Track A's RAGTool wrapper instantiates:

        class RAGTool:
            def __init__(self):
                from tools.rag.retrieve import Retriever
                self.retriever = Retriever()
            def query(self, text, top_k=5, kb_id=None):
                return self.retriever.query(text, top_k, kb_id)

    Keep the query() signature exactly as below — it's the contract.
    """

    def __init__(self):
        # kb_id -> (BM25Okapi | None, list[Document]) — avoids rebuilding
        # BM25 from the registry on every single query in a long-running
        # process (e.g. inside the agent).
        self._bm25_cache: dict[str, tuple] = {}

    def invalidate(self, kb_id: str) -> None:
        """Call this after any ingest/delete so the next query rebuilds
        BM25 from the fresh registry instead of serving stale results.
        """
        self._bm25_cache.pop(kb_id, None)

    def _get_bm25(self, kb_id: str):
        if kb_id not in self._bm25_cache:
            registry = load_registry(kb_id)
            chunks = chunks_as_documents(registry)
            self._bm25_cache[kb_id] = build_bm25(chunks)
        return self._bm25_cache[kb_id]

    def query(self, text: str, top_k: int = DEFAULT_TOP_K, kb_id: str | None = None) -> list[dict]:
        kb_id = kb_id or DEFAULT_KB_ID

        index = load_index(kb_id)
        bm25, chunks = self._get_bm25(kb_id)

        if index is None or not chunks:
            return []  # empty KB -> empty result; caller (agent) falls back to web search

        fetch_k = max(top_k * 4, 20)  # over-fetch candidates before reranking

        embedding_hits = index.similarity_search_with_score(text, k=fetch_k)
        bm25_hits = bm25_search(bm25, chunks, text, fetch_k) if bm25 else []

        fused = reciprocal_rank_fusion(bm25_hits, embedding_hits, k_constant=FUSION_K_CONSTANT)
        reranked = rerank(text, fused, top_k=top_k)

        return [_to_passage(doc, score) for doc, score in reranked]


def _to_passage(doc: Document, score: float) -> dict:
    """Matches the CLI contract's query output shape exactly:
    { "text", "source", "page", "score" }
    """
    meta = doc.metadata
    return {
        "text": doc.page_content,
        "source": meta.get("source", "unknown"),
        "page": meta.get("page", 0),
        "score": round(score, 4),
    }