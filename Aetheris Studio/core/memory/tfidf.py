"""Small, dependency-free TF-IDF + cosine similarity ranker.

Deliberately not a neural embedding (no ONNX/fastembed/sentence-transformers,
no model download, no extra process) -- skill libraries here are small
(tens to low hundreds of entries), so recomputing TF-IDF over the whole
corpus on every query is cheap and needs no cache-invalidation story. This
is a real upgrade over plain Jaccard (rare/distinctive terms are weighted
higher than common ones), not a placeholder for a "real" embedding model.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable


def _tf(tokens: list[str]) -> Dict[str, float]:
    if not tokens:
        return {}
    counts: Dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    n = len(tokens)
    return {term: count / n for term, count in counts.items()}


def tfidf_scores(
    query_tokens: Iterable[str],
    document_tokens: Dict[str, list[str]],
) -> Dict[str, float]:
    """Cosine similarity between `query_tokens` and each entry of
    `document_tokens` (key -> token list), under TF-IDF weighting computed
    over the corpus formed by the documents plus the query itself (so a
    term that's rare across the actual skill library, not some external
    reference corpus, is what gets weighted up). Returns {key: score in
    [0, 1]}; a key absent from the result had zero token overlap."""
    query_tokens = list(query_tokens)
    if not query_tokens or not document_tokens:
        return {}

    corpus: Dict[str, list[str]] = {"__query__": query_tokens, **document_tokens}
    n_docs = len(corpus)

    df: Dict[str, int] = {}
    for tokens in corpus.values():
        for term in set(tokens):
            df[term] = df.get(term, 0) + 1
    idf = {term: math.log((1 + n_docs) / (1 + count)) + 1.0 for term, count in df.items()}

    def _vector(tokens: list[str]) -> Dict[str, float]:
        tf = _tf(tokens)
        return {term: freq * idf.get(term, 0.0) for term, freq in tf.items()}

    query_vec = _vector(query_tokens)
    q_norm = math.sqrt(sum(w * w for w in query_vec.values()))
    if q_norm == 0:
        return {}

    scores: Dict[str, float] = {}
    for key, tokens in document_tokens.items():
        doc_vec = _vector(tokens)
        if not doc_vec:
            continue
        shared = query_vec.keys() & doc_vec.keys()
        if not shared:
            continue
        dot = sum(query_vec[t] * doc_vec[t] for t in shared)
        d_norm = math.sqrt(sum(w * w for w in doc_vec.values()))
        if d_norm == 0:
            continue
        scores[key] = dot / (q_norm * d_norm)
    return scores
