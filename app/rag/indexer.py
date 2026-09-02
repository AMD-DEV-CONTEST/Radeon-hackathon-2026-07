"""FAISS + BM25 hybrid index with incremental updates.

ProjectIndex
    Builds and persists a dual index for a single project:
    - FAISS IndexFlatIP   (dense  — semantic recall)
    - BM25Okapi            (sparse — keyword recall)

Indexing is *incremental* based on content‑hash snapshots so unchanged
files are never re‑embedded.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from app.config import Settings
from app.rag.chunker import split_document
from app.rag.embedder import create_embedder
from app.rag.manifest import ContentChunk, ParsedDocument
from app.security.paths import ensure_project_path, validate_project_id


def _chinese_tokenize(text: str) -> list[str]:
    """Tokenize for BM25: unigrams + bigrams for CJK, space‑split for ASCII."""
    tokens: list[str] = []
    # Character unigrams for Chinese
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            tokens.append(ch)

    # Character bigrams for Chinese
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if "\u4e00" <= a <= "\u9fff" and "\u4e00" <= b <= "\u9fff":
            tokens.append(a + b)

    # Space‑split for ASCII / mixed content
    for part in text.split():
        clean = part.strip(",.!?;:()[]{}'\"")
        if clean and not all("\u4e00" <= c <= "\u9fff" for c in clean):
            tokens.append(clean.lower())

    return tokens


def _content_fingerprint(chunks: list[ContentChunk]) -> str:
    """Stable fingerprint of chunk content for incremental indexing."""
    hasher = hashlib.sha256()
    for c in chunks:
        hasher.update(c.content.encode("utf-8"))
    return hasher.hexdigest()


class ProjectIndex:
    """Hybrid FAISS + BM25 index scoped to one project."""

    def __init__(
        self,
        project_id: str,
        settings: Settings | None = None,
        *,
        mock_embed_dim: int | None = None,
        embedder=None,
    ):
        self._project_id = validate_project_id(project_id)
        self._settings = settings or Settings()

        self.chunks: list[ContentChunk] = []
        self._embeddings: np.ndarray | None = None
        self._faiss = None          # faiss.IndexFlatIP
        self._bm25 = None           # BM25Okapi
        self._bm25_corpus: list[str] = []
        self._fingerprints: dict[str, str] = {}  # relative_path → content hash

        # Embedder
        self._embedder = embedder or create_embedder(
            mock_dim=mock_embed_dim, project_id=self._project_id, settings=self._settings
        )

        # Storage directory
        self._dir = ensure_project_path(self._settings.vector_db_root, self._project_id)

    # ── public API ─────────────────────────────────────────────────

    def index(self, documents: list[ParsedDocument]) -> int:
        """Index parsed documents.  Returns chunk count."""
        if not documents:
            return 0

        # Chunk every document
        new_chunks: list[ContentChunk] = []
        new_fingerprints: dict[str, str] = {}

        for doc in documents:
            chunks = split_document(doc)
            fp = _content_fingerprint(chunks)
            new_fingerprints[doc.relative_path] = fp

            # Skip unchanged files
            if self._fingerprints.get(doc.relative_path) == fp:
                # Keep existing chunks for this file
                existing = [c for c in self.chunks if c.relative_path == doc.relative_path]
                if existing:
                    new_chunks.extend(existing)
                    continue

            new_chunks.extend(chunks)

        if not new_chunks:
            return 0

        # Detect real changes
        changed = (
            len(new_chunks) != len(self.chunks)
            or new_fingerprints != self._fingerprints
        )

        if not changed:
            return len(self.chunks)

        self.chunks = new_chunks
        self._fingerprints = new_fingerprints

        # Embed
        texts = [c.content for c in self.chunks]
        self._embeddings = self._embedder.embed(texts)

        # Build FAISS
        self._build_faiss()
        # Build BM25
        self._build_bm25(texts)

        return len(self.chunks)

    def is_built(self) -> bool:
        return self._faiss is not None and len(self.chunks) > 0

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def get_chunk(self, idx: int) -> ContentChunk | None:
        """Retrieve chunk by index."""
        if 0 <= idx < len(self.chunks):
            return self.chunks[idx]
        return None

    # ── FAISS ──────────────────────────────────────────────────────

    def _build_faiss(self) -> None:
        import faiss

        vecs = self._embeddings.astype(np.float32).copy()
        faiss.normalize_L2(vecs)
        self._faiss = faiss.IndexFlatIP(vecs.shape[1])
        self._faiss.add(vecs)

    def faiss_search(self, query: str, k: int = 15) -> list[tuple[int, float]]:
        """Return (chunk_idx, similarity_score) pairs."""
        if not self.is_built():
            return []

        import faiss

        q = self._embedder.embed([query])
        faiss.normalize_L2(q)
        scores, indices = self._faiss.search(q, min(k, len(self.chunks)))
        return [
            (int(indices[0][i]), float(scores[0][i]))
            for i in range(len(indices[0]))
            if indices[0][i] >= 0
        ]

    # ── BM25 ───────────────────────────────────────────────────────

    def _build_bm25(self, corpus: list[str]) -> None:
        from rank_bm25 import BM25Okapi

        self._bm25_corpus = list(corpus)
        tokenized = [_chinese_tokenize(t) for t in self._bm25_corpus]
        self._bm25 = BM25Okapi(tokenized)

    def bm25_search(self, query: str, k: int = 15) -> list[tuple[int, float]]:
        """Return (chunk_idx, score) pairs."""
        if self._bm25 is None or not self._bm25_corpus:
            return []

        qt = _chinese_tokenize(query)
        scores = self._bm25.get_scores(qt)
        top = np.argsort(scores)[::-1][: min(k, len(scores))]
        return [(int(i), float(scores[i])) for i in top if scores[i] > 0]

    # ── persistence ────────────────────────────────────────────────

    def save(self) -> None:
        """Persist index to vector_db_root/<project_id>/."""
        if not self.is_built():
            return
        import faiss

        self._dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._faiss, str(self._dir / "faiss.index"))
        np.save(self._dir / "embeddings.npy", self._embeddings)
        # Save chunks as JSON (more portable than pickle)
        with open(self._dir / "chunks.json", "w", encoding="utf-8") as f:
            json.dump(
                [c.model_dump() for c in self.chunks], f, ensure_ascii=False, indent=2
            )
        with open(self._dir / "bm25_corpus.json", "w", encoding="utf-8") as f:
            json.dump(self._bm25_corpus, f, ensure_ascii=False)
        with open(self._dir / "fingerprints.json", "w", encoding="utf-8") as f:
            json.dump(self._fingerprints, f, ensure_ascii=False)

    def load(self) -> bool:
        """Load persisted index.  Returns True on success."""
        faiss_path = self._dir / "faiss.index"
        chunks_path = self._dir / "chunks.json"
        if not faiss_path.is_file() or not chunks_path.is_file():
            return False

        import faiss

        self._faiss = faiss.read_index(str(faiss_path))
        self._embeddings = np.load(self._dir / "embeddings.npy")

        with open(chunks_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            self.chunks = [ContentChunk(**item) for item in raw]

        bm25_path = self._dir / "bm25_corpus.json"
        if bm25_path.is_file():
            with open(bm25_path, "r", encoding="utf-8") as f:
                self._bm25_corpus = json.load(f)
            self._build_bm25(self._bm25_corpus)

        fp_path = self._dir / "fingerprints.json"
        if fp_path.is_file():
            with open(fp_path, "r", encoding="utf-8") as f:
                self._fingerprints = json.load(f)

        return True
