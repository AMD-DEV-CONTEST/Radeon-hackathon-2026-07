from __future__ import annotations

import json

from .database import Database
from .embeddings import HashEmbedding, cosine_similarity
from .schemas import RetrievalHit
from .utils import tokenize


_QUERY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "tell",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "个",
    "了",
    "什么",
    "吗",
    "哪",
    "哪些",
    "是",
    "有",
    "的",
    "请",
}


def _meaningful_query_tokens(query: str) -> list[str]:
    return [
        token
        for token in dict.fromkeys(tokenize(query))
        if token not in _QUERY_STOP_WORDS
    ][:16]


class HybridRetriever:
    def __init__(self, database: Database, embedding: HashEmbedding | None = None):
        self.database = database
        self.embedding = embedding or HashEmbedding()

    def search(self, query: str, limit: int = 8) -> list[RetrievalHit]:
        tokens = _meaningful_query_tokens(query)
        expression = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        lexical_rows = (
            self.database.search_fts(expression, limit=max(limit * 3, 20))
            if expression
            else []
        )
        lexical: dict[str, float] = {}
        rows_by_id: dict[str, dict] = {}
        raw_lexical = [max(0.0, -float(row["rank"] or 0.0)) for row in lexical_rows]
        strongest_lexical = max(raw_lexical, default=0.0)
        for position, (row, relevance) in enumerate(zip(lexical_rows, raw_lexical), 1):
            lexical[row["chunk_id"]] = (
                relevance / strongest_lexical
                if strongest_lexical > 0
                else 1.0 / position
            )
            rows_by_id[row["chunk_id"]] = row

        query_vector = self.embedding.embed(" ".join(tokens))
        vectors: dict[str, float] = {}
        for row in self.database.list_embedding_rows():
            if row["model_id"] != self.embedding.model_id:
                continue
            score = max(0.0, cosine_similarity(query_vector, json.loads(row["vector_json"])))
            # Hash embeddings are a deterministic lexical baseline, not a
            # semantic model. A vector-only match can therefore be a hash
            # collision and must not introduce an unrelated source.
            if isinstance(self.embedding, HashEmbedding) and row["chunk_id"] not in lexical:
                continue
            vectors[row["chunk_id"]] = score
            rows_by_id.setdefault(row["chunk_id"], row)

        hits: list[RetrievalHit] = []
        for chunk_id, row in rows_by_id.items():
            lexical_score = lexical.get(chunk_id, 0.0)
            vector_score = vectors.get(chunk_id, 0.0)
            combined = lexical_score * 0.6 + vector_score * 0.4
            if combined <= 0:
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=chunk_id,
                    card_id=row.get("card_id"),
                    card_title=row.get("card_title"),
                    text=row["text"],
                    source_url=row["canonical_url"],
                    immutable_url=row["immutable_url"],
                    start_line=int(row["start_line"]),
                    end_line=int(row["end_line"]),
                    lexical_score=lexical_score,
                    vector_score=vector_score,
                    score=combined,
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:limit]
