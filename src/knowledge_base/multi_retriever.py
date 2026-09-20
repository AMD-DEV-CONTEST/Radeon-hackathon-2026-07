"""Multi-path retrieval engine for the quantitative agent.

Pipeline:
  Query → Query expansion →
    ① Keyword retrieval (existing, top_k=6)
    ② BM25 sparse retrieval (top_k=6)
    ③ Dense vector retrieval (top_k=6, optional — degrades to keyword if no embeddings)
  → Merge & deduplicate (≤10 candidates)
  → Cross-encoder reranking (score-based, keep top 4)
  → Confidence gating (score < 0.45 → clear results)
  → Return to LLM context

The confidence gate is a hard gate: if no document passes the threshold,
has_valid_docs=false, and the reasoning agent must output neutral.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from .retriever import KnowledgeRetriever, KnowledgeEntry, retrieve_knowledge as _keyword_retrieve


# ── BM25 Sparse Retriever ──────────────────────────────────────────


class BM25Retriever:
    """BM25 sparse retrieval over knowledge entries.

    Pure Python implementation — no external dependencies.
    Uses term frequency / inverse document frequency with BM25 ranking.
    """

    def __init__(self, entries: list[KnowledgeEntry] | None = None, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._entries = entries or []
        self._doc_tokens: list[list[str]] = []
        self._doc_freqs: list[dict[str, int]] = []
        self._avg_dl: float = 0.0
        self._idf: dict[str, float] = {}
        self._build_index()

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize into lowercase English words + CJK bigrams."""
        text = text.lower()
        en_tokens = re.findall(r"[a-z0-9]+", text)
        cn_chars = re.findall(r"[一-鿿]", text)
        cn_bigrams = [cn_chars[i] + cn_chars[i + 1] for i in range(len(cn_chars) - 1)]
        return en_tokens + cn_bigrams

    def _build_index(self):
        """Build BM25 index: document frequencies, IDF, average document length."""
        self._doc_tokens = []
        self._doc_freqs = []
        df: dict[str, int] = {}  # document frequency

        for entry in self._entries:
            # Combine all searchable text
            text = " ".join(entry.terms) + " " + entry.title + " " + entry.content
            tokens = self._tokenize(text)
            self._doc_tokens.append(tokens)
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            self._doc_freqs.append(tf)
            for term in tf:
                df[term] = df.get(term, 0) + 1

        N = len(self._entries)
        self._avg_dl = sum(len(t) for t in self._doc_tokens) / N if N > 0 else 0
        # BM25 IDF
        self._idf = {
            term: math.log(1 + (N - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def retrieve(self, query: str, top_k: int = 6) -> list[tuple[float, KnowledgeEntry]]:
        """Return list of (score, entry) sorted by BM25 score descending."""
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        scored: list[tuple[float, KnowledgeEntry]] = []
        for i, entry in enumerate(self._entries):
            score = 0.0
            tf = self._doc_freqs[i]
            dl = len(self._doc_tokens[i])
            for term in q_tokens:
                if term not in self._idf:
                    continue
                f = tf.get(term, 0)
                if f == 0:
                    continue
                idf = self._idf[term]
                numerator = f * (self.k1 + 1)
                denominator = f + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1))
                score += idf * numerator / denominator
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]


# ── Cross-Encoder Reranker (heuristic-based) ──────────────────────


class CrossEncoderReranker:
    """Heuristic cross-encoder reranker.

    A real cross-encoder model would score query-doc pairs jointly.
    This implementation uses term overlap + position + category boost
    as a lightweight proxy when no ML model is available.
    """

    def __init__(self, boost_categories: dict[str, float] | None = None):
        self.boost_categories = boost_categories or {
            "risk": 1.2,
            "strategy": 1.1,
            "indicator": 1.0,
            "market": 0.9,
        }

    def score(self, query: str, entry: KnowledgeEntry) -> float:
        """Score a query-entry pair. Returns [0.0, 1.0]."""
        query_lower = query.lower()
        text = (entry.title + " " + entry.content).lower()

        # Term overlap ratio
        q_terms = set(re.findall(r"[a-z0-9]+", query_lower))
        q_cn = set(re.findall(r"[一-鿿]+", query))
        entry_terms = set(entry.terms)

        en_match = len(q_terms & entry_terms) / max(len(q_terms), 1) if q_terms else 0
        cn_match = sum(1 for c in q_cn if any(c in t for t in entry_terms)) / max(len(q_cn), 1) if q_cn else 0

        # Keyword density in content
        keyword_hits = sum(1 for t in entry.terms if t.lower() in text)
        density = min(keyword_hits / max(len(entry.terms), 1), 1.0)

        # Category boost
        cat_boost = self.boost_categories.get(entry.category, 1.0)

        # Weighted combination → normalize to [0, 1]
        raw = (en_match * 0.35 + cn_match * 0.35 + density * 0.30) * cat_boost * entry.weight
        return min(raw, 1.0)


# ── Multi-Retriever (main entry point) ─────────────────────────────


@dataclass
class RetrievalResult:
    """Structured result from multi-path retrieval."""
    reference_docs: list[dict] = field(default_factory=list)
    has_valid_docs: bool = False
    max_confidence_score: float = 0.0
    query: str = ""
    total_candidates: int = 0
    reranked_count: int = 0


class MultiRetriever:
    """Multi-path retrieval engine: keyword + BM25 + dense + reranking.

    Falls back gracefully when optional components (embeddings) are unavailable.
    Implements confidence gating per the LoRA Training Spec.
    """

    CONFIDENCE_THRESHOLD = 0.45  # Below this → has_valid_docs = False
    MAX_FINAL_DOCS = 4
    TOP_K_PER_PATH = 6
    MAX_CANDIDATES = 10

    def __init__(self, entries: list[KnowledgeEntry] | None = None):
        self._keyword = KnowledgeRetriever(entries)
        self._bm25 = BM25Retriever(self._keyword._entries)
        self._reranker = CrossEncoderReranker()

        # Optional dense retriever (degrades gracefully)
        self._dense = None
        try:
            from .semantic import SemanticRetriever, semantic_available
            if semantic_available():
                self._dense = SemanticRetriever(self._keyword)
        except Exception:
            pass

    def retrieve(self, query: str, filter_meta: dict | None = None) -> RetrievalResult:
        """Run multi-path retrieval pipeline.

        Args:
            query: Natural language query.
            filter_meta: Optional metadata filter (strategy, asset, timeframe, version).

        Returns:
            RetrievalResult with reference_docs, has_valid_docs, and confidence.
        """
        if not query.strip():
            return RetrievalResult(query=query)

        # ── Path 1: Keyword retrieval ───────────────────────────
        keyword_results = self._keyword.retrieve(query, max_results=self.TOP_K_PER_PATH)

        # ── Path 2: BM25 retrieval ──────────────────────────────
        bm25_results = self._bm25.retrieve(query, top_k=self.TOP_K_PER_PATH)
        bm25_entries = [entry for _, entry in bm25_results]

        # ── Path 3: Dense retrieval (optional) ──────────────────
        dense_entries: list[KnowledgeEntry] = []
        if self._dense:
            try:
                dense_entries = self._dense.retrieve(query, max_results=self.TOP_K_PER_PATH)
            except Exception:
                pass  # Degrade to keyword+BM25 only

        # ── Merge & deduplicate ─────────────────────────────────
        seen_titles = set()
        candidates: list[KnowledgeEntry] = []
        for entry in keyword_results + bm25_entries + dense_entries:
            if entry.title not in seen_titles:
                seen_titles.add(entry.title)
                candidates.append(entry)
            if len(candidates) >= self.MAX_CANDIDATES:
                break

        if not candidates:
            return RetrievalResult(query=query, total_candidates=0)

        # ── Apply metadata filter if provided ───────────────────
        if filter_meta:
            candidates = self._apply_filter(candidates, filter_meta)

        # ── Cross-encoder reranking ─────────────────────────────
        scored = [(self._reranker.score(query, entry), entry) for entry in candidates]
        scored.sort(key=lambda x: -x[0])

        # ── Confidence gating ───────────────────────────────────
        top_docs = []
        max_score = 0.0
        for score, entry in scored[:self.MAX_FINAL_DOCS]:
            max_score = max(max_score, score)
            top_docs.append({
                "title": entry.title,
                "category": entry.category,
                "content": entry.content[:500],
                "score": round(score, 4),
            })

        has_valid = max_score >= self.CONFIDENCE_THRESHOLD

        return RetrievalResult(
            reference_docs=top_docs if has_valid else [],
            has_valid_docs=has_valid,
            max_confidence_score=round(max_score, 4),
            query=query,
            total_candidates=len(candidates),
            reranked_count=len(top_docs),
        )

    def retrieve_as_context(self, query: str, max_chars: int = 2000) -> str:
        """Retrieve and format as context string for LLM prompt."""
        result = self.retrieve(query)
        if not result.has_valid_docs:
            return ""

        parts: list[str] = []
        total = 0
        for doc in result.reference_docs:
            text = f"### {doc['title']} (score={doc['score']}, category={doc['category']})\n{doc['content']}"
            if total + len(text) > max_chars:
                break
            parts.append(text)
            total += len(text)

        return "\n\n".join(parts) if parts else ""

    def _apply_filter(
        self, entries: list[KnowledgeEntry], filter_meta: dict
    ) -> list[KnowledgeEntry]:
        """Filter entries by metadata (asset, timeframe, strategy)."""
        asset = filter_meta.get("asset", "").lower()
        timeframe = filter_meta.get("timeframe", "").lower()

        if not asset and not timeframe:
            return entries

        filtered = []
        for entry in entries:
            text = (entry.title + " " + entry.content).lower()
            if asset and asset.lower() in text:
                filtered.append(entry)
            elif timeframe and timeframe.lower() in text:
                filtered.append(entry)
            elif not asset and not timeframe:
                filtered.append(entry)

        return filtered if filtered else entries  # Don't over-filter


# ── Module-level convenience ────────────────────────────────────────

_multi_retriever: MultiRetriever | None = None


def retrieve_with_confidence(query: str, filter_meta: dict | None = None) -> RetrievalResult:
    """Retrieve knowledge with confidence gating.

    This is the primary retrieval function for the multi-agent system.
    Returns a RetrievalResult with has_valid_docs flag.
    """
    global _multi_retriever
    if _multi_retriever is None:
        _multi_retriever = MultiRetriever()
    return _multi_retriever.retrieve(query, filter_meta=filter_meta)
