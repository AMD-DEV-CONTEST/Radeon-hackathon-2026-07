from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class QueryResult:
    article: Any
    article_id: str
    hybrid_score: float
    trust_score: float
    provenance_summary: dict


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _allowed_scope(article_scope: str, scope_filter: list[str]) -> bool:
    if article_scope == "private":
        return "private" in scope_filter
    if article_scope == "public":
        return "public" in scope_filter or any(s != "private" for s in scope_filter)
    if article_scope.startswith("partner:"):
        return article_scope in scope_filter
    return article_scope in scope_filter


def retrieve(
    store: Any,
    vector_index: Any,
    embedder: Any,
    query_text: str,
    topic_filter: list[str],
    scope_filter: list[str],
    top_k: int,
    min_trust: float,
    deadline_ms: int,
    now: Any | None = None,
) -> list[QueryResult]:
    started = time.monotonic()
    query_vec = embedder.embed_one(normalize_whitespace(query_text))
    over_fetch = max(top_k * 2, top_k)
    candidates = vector_index.search(query_vec, top_k=over_fetch)
    scored: list[QueryResult] = []
    for art_id, cosine in candidates:
        if (time.monotonic() - started) * 1000 > deadline_ms:
            break
        article = store.get(art_id)
        if article is None:
            continue
        if not _allowed_scope(article.scope, scope_filter):
            continue
        if topic_filter and article.type not in topic_filter:
            continue
        trust = float(article.trust_score) if article.trust_score is not None else 0.0
        if trust < min_trust:
            continue
        hybrid = 0.5 * float(cosine) + 0.5 * trust
        summary = {
            "producer_org": getattr(article.provenance, "producer_org", None),
            "timestamp": getattr(article.provenance, "timestamp", None).isoformat() if getattr(article.provenance, "timestamp", None) else None,
            "run_id": getattr(article.provenance, "run_id", None),
            "n_cites": len(getattr(article, "cites", []) or []),
        }
        scored.append(QueryResult(article=article, article_id=art_id, hybrid_score=hybrid, trust_score=trust, provenance_summary=summary))
    scored.sort(key=lambda r: -r.hybrid_score)
    return scored[:top_k]
