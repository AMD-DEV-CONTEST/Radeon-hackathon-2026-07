"""Deterministic local RAG over markdown ROCm/vLLM knowledge files."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from pathlib import Path

from .models import Evidence

TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


class LocalRAG:
    """BM25-style retriever for local markdown knowledge documents."""

    def __init__(self, knowledge_path: str | Path = "data/knowledge") -> None:
        self.knowledge_path = Path(knowledge_path)
        self._docs: list[tuple[Path, str, Counter[str]]] = []
        self._load()

    def _load(self) -> None:
        self._docs.clear()
        if not self.knowledge_path.exists():
            return
        for path in sorted(self.knowledge_path.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            self._docs.append((path, text, Counter(tokenize(text))))

    def refresh(self) -> None:
        self._load()

    def search(self, query: str, limit: int = 4) -> list[Evidence]:
        query_terms = tokenize(query)
        if not query_terms or not self._docs:
            return []

        doc_count = len(self._docs)
        avg_len = sum(sum(counts.values()) for _, _, counts in self._docs) / doc_count
        df = Counter(term for term in set(query_terms) for _, _, counts in self._docs if term in counts)
        scored: list[tuple[float, Path, str]] = []
        for path, text, counts in self._docs:
            length = max(1, sum(counts.values()))
            score = 0.0
            for term in query_terms:
                if counts[term] == 0:
                    continue
                idf = math.log(1 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
                numerator = counts[term] * 2.2
                denominator = counts[term] + 1.2 * (0.25 + 0.75 * length / max(avg_len, 1))
                score += idf * numerator / denominator
            if score > 0:
                scored.append((score, path, text))

        return [
            Evidence(
                source=str(path),
                quote=self._best_snippet(text, query_terms),
                score=round(score, 4),
                metadata=self._metadata(text),
            )
            for score, path, text in sorted(scored, key=lambda item: (-item[0], str(item[1])))[:limit]
        ]

    @staticmethod
    def _best_snippet(text: str, query_terms: list[str]) -> str:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not paragraphs:
            return ""
        term_set = set(query_terms)
        best = max(paragraphs, key=lambda paragraph: len(term_set.intersection(tokenize(paragraph))))
        return re.sub(r"\s+", " ", best)[:280]

    @staticmethod
    def _metadata(text: str) -> dict[str, str]:
        metadata: dict[str, str] = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        for field, key in (
            ("Document ID", "document_id"),
            ("Revision", "revision"),
            ("Classification", "classification"),
        ):
            match = re.search(rf"^{re.escape(field)}:\s*(.+?)\s*$", text, re.MULTILINE)
            if match:
                metadata[key] = match.group(1).strip()
        return metadata
