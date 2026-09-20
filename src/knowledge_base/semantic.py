"""Optional semantic (embedding-based) retrieval layer — the TRUE RAG path.

The default `KnowledgeRetriever` (retriever.py) is a CPU-only keyword/alias
matcher. This module upgrades it to semantic retrieval when an embedding model
is available locally, so a query like "市场横盘时该怎么操作" matches the
Mean-Reversion entry by *meaning*, not by string overlap.

Activation is OPTIONAL and FAIL-SAFE:
- If `sentence_transformers` (and a model) is available, `SemanticRetriever`
  embeds every entry once and ranks by cosine similarity at query time.
- If the dependency or model is missing, importing this module is still safe
  (`SemanticRetriever` raises a clear RuntimeError only when you try to build
  it). The keyword retriever in `retriever.py` remains the active path, so the
  knowledge base never breaks.

Usage
-----
    from src.knowledge_base.semantic import SemanticRetriever, semantic_available
    if semantic_available():
        sr = SemanticRetriever(retriever)          # reranks via embeddings
        ctx = sr.retrieve_as_context("横盘市怎么做")
    else:
        ctx = retriever.retrieve_as_context(...)   # keyword path

No GPU required: a small CPU model (e.g. BAAI/bge-small-en-v1.5, ~130MB) runs
fine on CPU. For Chinese-heavy queries prefer a multilingual model such as
BAAI/bge-m3 or intfloat/multilingual-e5-small.
"""

from __future__ import annotations

import numpy as np

try:
    # Heavy optional dep — guarded so the KB works without it.
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except Exception:  # pragma: no cover - depends on environment
    _HAS_ST = False
    SentenceTransformer = None  # type: ignore


def semantic_available() -> bool:
    """True if an embedding backend is installed."""
    return _HAS_ST


class SemanticRetriever:
    """Wrapper that adds embedding-based semantic ranking over a base retriever.

    The base retriever's keyword results are still used as a cheap first pass;
    this layer reranks (or, if `recall_k` is large, augments) them by cosine
    similarity in embedding space.
    """

    def __init__(
        self,
        base,
        model_name: str = "BAAI/bge-small-en-v1.5",
        recall_k: int = 12,
    ):
        if not _HAS_ST:
            raise RuntimeError(
                "sentence-transformers is not installed; cannot build "
                "SemanticRetriever. The keyword KnowledgeRetriever remains active."
            )
        self.base = base
        self.model_name = model_name
        self.recall_k = recall_k
        self.model = SentenceTransformer(model_name)
        # Embed the corpus once (cheap: ~31 short texts).
        self._corpus_emb = self.model.encode(
            [e.content for e in base._entries],
            normalize_embeddings=True,
        )

    # ── Public API (mirrors KnowledgeRetriever) ─────────────────────────

    def retrieve(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.0,
    ) -> list:
        """Semantic retrieval, optionally fused with keyword recall.

        Returns KnowledgeEntry objects (same type as the keyword retriever).
        """
        # Cheap keyword first pass to bound the candidate set.
        cands = self.base.retrieve(query, max_results=self.recall_k, min_score=0.05)
        if not cands:
            return []
        cand_idx = {id(e): i for i, e in enumerate(self.base._entries)}
        q_emb = self.model.encode([query], normalize_embeddings=True)[0]
        sims = self._corpus_emb @ q_emb  # cosine (vectors normalized)

        scored = []
        for e in cands:
            i = cand_idx[id(e)]
            scored.append((float(sims[i]), e))
        scored.sort(key=lambda x: -x[0])
        return [e for s, e in scored[:max_results] if s >= min_score]

    def retrieve_as_context(
        self,
        query: str,
        max_results: int = 5,
        max_chars: int = 2000,
    ) -> str:
        """Semantic retrieval formatted as an LLM prompt context string."""
        entries = self.retrieve(query, max_results=max_results)
        if not entries:
            return ""
        sections: list[str] = []
        current_category = ""
        total_chars = 0
        for entry in entries:
            if entry.category != current_category:
                current_category = entry.category
                hdr = f"\n## {current_category.title()}"
                if total_chars + len(hdr) > max_chars:
                    break
                sections.append(hdr)
                total_chars += len(hdr)
            text = f"\n### {entry.title}\n{entry.content}"
            if total_chars + len(text) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 50:
                    sections.append(text[:remaining] + "...")
                break
            sections.append(text)
            total_chars += len(text)
        return "\n".join(sections)
