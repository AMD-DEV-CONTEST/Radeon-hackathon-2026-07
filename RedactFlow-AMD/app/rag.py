from __future__ import annotations

import math
import re
from collections import Counter


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def chunk_text(text: str, size: int = 620, overlap: int = 100) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _cosine(query: Counter[str], candidate: Counter[str]) -> float:
    shared = set(query) & set(candidate)
    numerator = sum(query[token] * candidate[token] for token in shared)
    query_norm = math.sqrt(sum(value * value for value in query.values()))
    candidate_norm = math.sqrt(sum(value * value for value in candidate.values()))
    if not query_norm or not candidate_norm:
        return 0.0
    return numerator / (query_norm * candidate_norm)


def search(query: str, documents: list[dict[str, str]], limit: int = 6) -> list[dict]:
    query_terms = Counter(tokenize(query))
    hits: list[dict] = []
    for document in documents:
        for chunk in chunk_text(document["content"]):
            score = _cosine(query_terms, Counter(tokenize(chunk)))
            if score > 0:
                hits.append(
                    {
                        "document_id": document["id"],
                        "name": document["name"],
                        "score": round(score, 4),
                        "excerpt": chunk,
                    }
                )
    hits.sort(key=lambda hit: hit["score"], reverse=True)
    return hits[:limit]

