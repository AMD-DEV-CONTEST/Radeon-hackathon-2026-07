from __future__ import annotations

import math
import re
from hashlib import sha256
from dataclasses import dataclass
from pathlib import Path

from privateops.models import Evidence

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
CHINESE_RE = re.compile(r"^[\u4e00-\u9fff]+$")
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css", ".log"}
MAX_DOCUMENT_BYTES = 1_000_000


@dataclass
class Document:
    source: str
    text: str
    tokens: list[str]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0).lower()
        tokens.append(token)
        if CHINESE_RE.fullmatch(token) and len(token) > 1:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


class DocumentStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.documents = self._load_documents()

    def _load_documents(self) -> list[Document]:
        if not self.root.exists():
            return []
        docs: list[Document] = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size <= MAX_DOCUMENT_BYTES:
                text = _read_text(path)
                docs.append(Document(str(path.relative_to(self.root)), text, tokenize(text)))
        return docs

    def refresh(self) -> None:
        self.documents = self._load_documents()

    def search(self, query: str, limit: int = 4) -> list[Evidence]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        query_set = set(query_tokens)
        ranked: list[Evidence] = []
        total_docs = max(len(self.documents), 1)

        for doc in self.documents:
            if not doc.tokens:
                continue
            doc_set = set(doc.tokens)
            overlap = query_set.intersection(doc_set)
            if not overlap:
                continue
            score = 0.0
            for token in overlap:
                docs_with_token = sum(1 for candidate in self.documents if token in set(candidate.tokens))
                idf = math.log((1 + total_docs) / (1 + docs_with_token)) + 1
                score += doc.tokens.count(token) * idf
            score += len(overlap) / len(query_set)
            snippet = self._snippet(doc.text, overlap)
            digest = sha256(f"{doc.source}\0{snippet}".encode("utf-8")).hexdigest()[:12]
            ranked.append(Evidence(doc.source, snippet, round(score, 4), f"ev-{digest}"))

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def _snippet(self, text: str, terms: set[str], window: int = 180) -> str:
        lower = text.lower()
        first = min((lower.find(term) for term in terms if lower.find(term) >= 0), default=0)
        start = max(first - 40, 0)
        snippet = text[start : start + window].replace("\n", " ").strip()
        return snippet + ("..." if start + window < len(text) else "")
