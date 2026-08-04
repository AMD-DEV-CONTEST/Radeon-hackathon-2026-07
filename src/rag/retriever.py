"""Query the local knowledge base.

Two backends:
- SimpleKeywordRetriever: pure-stdlib keyword scoring, zero dependencies,
  works immediately for development/demo.
- (future) VectorRetriever: chromadb + sentence-transformers, for the real
  submission if there's time to wire it up — same .retrieve() interface,
  so swapping is a one-line change in the orchestrator.
"""
import os
import re
from pathlib import Path


class SimpleKeywordRetriever:
    def __init__(self, kb_dir: str = None):
        self.kb_dir = Path(kb_dir or os.getenv("KNOWLEDGE_BASE_DIR", "./data/knowledge_base"))
        self._docs: list[dict] = []
        self._load()

    def _load(self):
        """Split each .md file into paragraph-level chunks with source tracking."""
        for path in sorted(self.kb_dir.glob("*.md")):
            text = path.read_text()
            chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
            for chunk in chunks:
                self._docs.append({"source": path.name, "text": chunk})

    @staticmethod
    def _tokenize(text: str) -> set:
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        query_tokens = self._tokenize(query)
        scored = []
        for doc in self._docs:
            doc_tokens = self._tokenize(doc["text"])
            overlap = len(query_tokens & doc_tokens)
            if overlap > 0:
                scored.append((overlap, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]


# Alias so orchestrator code can import a stable name regardless of backend
KnowledgeRetriever = SimpleKeywordRetriever
