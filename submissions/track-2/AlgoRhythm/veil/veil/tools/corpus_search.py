"""Auxiliary-corpus retrieval — the RAG leg of the system.

The corpus is what makes a correlational finding checkable. Without it the
Journalist and Insider personas are just speculating; with it, a claim like
"only three people match" is backed by a countable set of passages.

Retrieval is hybrid: dense (bge-small via Qdrant) plus a lexical pass, because
quasi-identifiers are often rare literal strings — a project codename, a date,
a certification number — and embeddings smooth exactly those away.
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from typing import Any

from veil.config import CONFIG
from veil.tools.registry import REGISTRY


@lru_cache(maxsize=1)
def _embedder() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(CONFIG.storage.embedding_model)


@lru_cache(maxsize=1)
def _qdrant() -> Any:
    from qdrant_client import QdrantClient

    return QdrantClient(path=CONFIG.storage.qdrant_path)


def dense_search(query: str, k: int = 5) -> list[dict[str, Any]]:
    vec = _embedder().encode(query, normalize_embeddings=True).tolist()
    hits = _qdrant().search(
        collection_name=CONFIG.storage.collection, query_vector=vec, limit=k
    )
    return [
        {
            "text": h.payload.get("text", ""),
            "source": h.payload.get("source", "?"),
            "score": round(float(h.score), 4),
            "mode": "dense",
        }
        for h in hits
    ]


def lexical_search(query: str, k: int = 5) -> list[dict[str, Any]]:
    """FTS5 over the same chunks. Catches rare literals the embedder blurs."""
    con = sqlite3.connect(CONFIG.storage.db_path)
    try:
        terms = [t for t in re.findall(r"[\w'-]{3,}", query)][:8]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = con.execute(
            "SELECT text, source, bm25(corpus_fts) FROM corpus_fts "
            "WHERE corpus_fts MATCH ? ORDER BY bm25(corpus_fts) LIMIT ?",
            (match, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [
        {"text": r[0], "source": r[1], "score": round(-float(r[2]), 4), "mode": "lexical"}
        for r in rows
    ]


def _fuse(dense: list[dict[str, Any]], lexical: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Reciprocal-rank fusion. No tuning knob, no score normalisation to argue
    about at 3am."""
    scores: dict[str, float] = {}
    keep: dict[str, dict[str, Any]] = {}
    for ranked in (dense, lexical):
        for rank, item in enumerate(ranked, start=1):
            key = item["text"][:200]
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
            keep.setdefault(key, item)
    order = sorted(scores, key=lambda x: scores[x], reverse=True)[:k]
    out = []
    for key in order:
        item = dict(keep[key])
        item["fused_score"] = round(scores[key], 5)
        out.append(item)
    return out


@REGISTRY.register(
    name="corpus_search",
    description=(
        "Search the auxiliary corpus (public records, org material, prior "
        "filings) for passages related to a query. Use this BEFORE asserting "
        "that a detail identifies someone — the returned passages are the "
        "evidence you must cite."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What you are trying to corroborate."},
            "k": {"type": "integer", "description": "Passages to return (default 5, max 10)."},
        },
        "required": ["query"],
    },
)
def corpus_search(query: str, k: int = 5) -> dict[str, Any]:
    k = max(1, min(int(k), 10))
    try:
        dense = dense_search(query, k)
    except Exception as exc:  # noqa: BLE001 - degrade to lexical rather than fail the run
        dense = []
        lex_note = f"dense retrieval unavailable ({type(exc).__name__})"
    else:
        lex_note = None
    lexical = lexical_search(query, k)
    results = _fuse(dense, lexical, k)
    return {
        "query": query,
        "hits": results,
        "hit_count": len(results),
        "note": lex_note,
    }
