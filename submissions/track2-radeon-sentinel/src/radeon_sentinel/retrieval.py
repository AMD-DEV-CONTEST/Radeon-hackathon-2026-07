"""Small dependency-free local runbook retriever."""

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence

from .schemas import Evidence


TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


@dataclass(frozen=True)
class Document:
    source: str
    text: str
    tokens: Sequence[str]


class LocalRetriever:
    def __init__(self, documents: Iterable[Document]) -> None:
        self.documents = list(documents)
        if not self.documents:
            raise ValueError("At least one runbook document is required")

        self._document_frequency: Counter[str] = Counter()
        for document in self.documents:
            self._document_frequency.update(set(document.tokens))
        self._average_length = sum(
            len(document.tokens) for document in self.documents
        ) / len(self.documents)

    @classmethod
    def from_directory(cls, root: Path) -> "LocalRetriever":
        root = Path(root)
        documents: List[Document] = []
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in {".md", ".txt"} or not path.is_file():
                continue
            relative_path = path.relative_to(root)
            if any(part.startswith(".") for part in relative_path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            documents.append(
                Document(
                    source=str(relative_path),
                    text=text,
                    tokens=tokenize(text),
                )
            )
        return cls(documents)

    def search(self, query: str, top_k: int = 3) -> List[Evidence]:
        query_tokens = list(dict.fromkeys(tokenize(query)))
        if not query_tokens:
            return []

        scores: Dict[str, float] = {}
        for document in self.documents:
            frequencies = Counter(document.tokens)
            score = 0.0
            for token in query_tokens:
                frequency = frequencies[token]
                if not frequency:
                    continue
                document_frequency = self._document_frequency[token]
                inverse_document_frequency = math.log(
                    1
                    + (len(self.documents) - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                length_normalization = 1.2 * (
                    0.25
                    + 0.75
                    * len(document.tokens)
                    / max(self._average_length, 1.0)
                )
                score += inverse_document_frequency * (
                    frequency * 2.2
                    / (frequency + length_normalization)
                )
            if score > 0:
                scores[document.source] = score

        ranked = sorted(
            self.documents,
            key=lambda document: scores.get(document.source, 0.0),
            reverse=True,
        )
        evidence: List[Evidence] = []
        for document in ranked:
            score = scores.get(document.source, 0.0)
            if score <= 0 or len(evidence) >= top_k:
                continue
            evidence.append(
                Evidence(
                    source=document.source,
                    excerpt=self._best_excerpt(document.text, query_tokens),
                    score=round(score, 4),
                )
            )
        return evidence

    @staticmethod
    def _best_excerpt(text: str, query_tokens: Sequence[str]) -> str:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", text)
            if paragraph.strip()
        ]
        if not paragraphs:
            return ""
        query_set = set(query_tokens)
        best = max(
            paragraphs,
            key=lambda paragraph: sum(
                1 for token in tokenize(paragraph) if token in query_set
            ),
        )
        compact = " ".join(best.split())
        return compact if len(compact) <= 420 else compact[:417] + "..."
