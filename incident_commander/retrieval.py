from __future__ import annotations

import re
from collections import Counter

from .models import Evidence

TOKEN_RE = re.compile(r"[a-zA-Z0-9_.:/%-]+")
STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "was", "are", "into"}


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS]


def rank_evidence(query: str, evidence: tuple[Evidence, ...], limit: int = 5) -> tuple[Evidence, ...]:
    query_terms = Counter(tokenize(query))
    scored: list[tuple[float, int, Evidence]] = []
    for index, item in enumerate(evidence):
        terms = Counter(tokenize(f"{item.source} {item.content}"))
        overlap = sum(min(count, terms[token]) for token, count in query_terms.items())
        signal_bonus = sum(
            0.35
            for signal in ("error", "timeout", "latency", "deploy", "rollback", "cpu", "memory", "database")
            if signal in terms
        )
        scored.append((overlap + signal_bonus, -index, item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return tuple(row[2] for row in scored[:limit])

