"""Deterministic local retrieval over bundled scientific Markdown documents."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Iterable


_TOKEN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9+_.-]*")
_URL = re.compile(r"https?://[^\s)>]+")


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    title: str
    content: str
    source_path: str
    source_urls: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeHit:
    document_id: str
    title: str
    excerpt: str
    source_path: str
    source_urls: tuple[str, ...]
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "source_path": self.source_path,
            "source_urls": list(self.source_urls),
            "score": self.score,
        }


class LocalKnowledgeBase:
    """Small transparent TF-IDF retriever; no model or network is required."""

    def __init__(self, documents: Iterable[KnowledgeDocument]) -> None:
        self.documents = tuple(documents)
        self._document_tokens = {
            document.document_id: _tokens(document.content)
            for document in self.documents
        }

    @classmethod
    def from_directory(cls, directory: str | Path) -> "LocalKnowledgeBase":
        root = Path(directory)
        documents = []
        for path in sorted(root.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            title = path.stem.replace("_", " ").title()
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            documents.append(
                KnowledgeDocument(
                    document_id=path.stem,
                    title=title,
                    content=content,
                    source_path=str(path),
                    source_urls=tuple(dict.fromkeys(_URL.findall(content))),
                )
            )
        return cls(documents)

    def search(self, query: str, limit: int = 5) -> list[KnowledgeHit]:
        query_terms = set(_tokens(query))
        if not query_terms or limit <= 0 or not self.documents:
            return []
        document_count = len(self.documents)
        document_frequency = {
            term: sum(
                term in set(self._document_tokens[document.document_id])
                for document in self.documents
            )
            for term in query_terms
        }
        hits: list[KnowledgeHit] = []
        for document in self.documents:
            tokens = self._document_tokens[document.document_id]
            counts = {term: tokens.count(term) for term in query_terms}
            matched = {term for term, count in counts.items() if count}
            if not matched:
                continue
            score = sum(
                (1.0 + math.log(counts[term]))
                * (math.log((document_count + 1) / (document_frequency[term] + 1)) + 1.0)
                for term in matched
            ) / math.sqrt(max(len(tokens), 1))
            excerpt = self._best_excerpt(document.content, matched)
            hits.append(
                KnowledgeHit(
                    document_id=document.document_id,
                    title=document.title,
                    excerpt=excerpt,
                    source_path=document.source_path,
                    source_urls=document.source_urls,
                    score=round(score, 8),
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.document_id))
        return hits[:limit]

    @staticmethod
    def _best_excerpt(content: str, query_terms: set[str]) -> str:
        candidates = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "Source:"))
        ]
        if not candidates:
            return content.strip()[:500]
        best = max(
            candidates,
            key=lambda line: sum(term in set(_tokens(line)) for term in query_terms),
        )
        return best[:500]
