"""Local RAG pipeline: ingest -> chunk -> embed (local GPU) -> retrieve -> cite.

Fully local: embedding model runs on the same Radeon GPU (or CPU fallback),
vectors persisted as .npz + JSON metadata under <workspace>/.screwshell/rag/.
No cloud calls, no external vector DB service.

Embedder default: Qwen/Qwen3-Embedding-0.6B (downloads once to /persistent
HF_HOME). Chunks carry file path + line ranges so every answer can cite
`file#Lstart-Lend`.

Retrieval (2026-08-04, per docs/OPENSOURCE_COMPARISON.md §4.1 — RAGFlow
multi-recall + rerank pattern, ADR-2 switchable):
  * hybrid recall: dense (embedding dot product) ∪ BM25 (zero-dependency
    implementation, good at exact terms / code symbols);
  * rerank: candidate set -> RRF fusion (no extra model) by default, or a
    cross-encoder reranker when one is injected (bge-reranker style).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import numpy as np
except ImportError:  # chunking works without numpy; embed/search need it
    np = None

TEXT_EXT = {".md", ".txt", ".rst", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
            ".toml", ".sh", ".cfg", ".ini", ".csv", ".log"}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _tokenize(text: str) -> list[str]:
    """Tokenize for BM25: ascii words + CJK characters (unigram is enough
    combined with IDF; no external segmenter, zero new deps)."""
    return _TOKEN_RE.findall(text.lower())


class BM25:
    """Zero-dependency Okapi BM25 over the chunk corpus.

    Built once per search over the (small) local corpus; scores exact
    term/code-symbol matches that dense embedding misses.
    """

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self._docs = docs
        self.doc_freq: dict[str, int] = {}
        self.doc_len: list[int] = []
        self.avgdl = 0.0
        n = len(docs)
        for d in docs:
            toks = _tokenize(d)
            self.doc_len.append(len(toks))
            for t in set(toks):
                self.doc_freq[t] = self.doc_freq.get(t, 0) + 1
        self.avgdl = (sum(self.doc_len) / n) if n else 0.0
        self.k1, self.b = k1, b
        self.n = n

    def _idf(self, term: str) -> float:
        df = self.doc_freq.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        q = _tokenize(query)
        if not q or not self.n:
            return []
        out: list[tuple[int, float]] = []
        for i, doc in enumerate(self._docs):
            tf: dict[str, int] = {t: 0 for t in q}
            for t in _tokenize(doc):
                if t in tf:
                    tf[t] += 1
            s = 0.0
            for t in q:
                f = tf[t]
                if f == 0:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                s += self._idf(t) * f * (self.k1 + 1) / denom
            if s > 0:
                out.append((i, s))
        out.sort(key=lambda x: -x[1])
        return out[:top_k]


def rrf_fuse(rank_lists: list[list[tuple[int, float]]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion of multiple candidate rank lists (zero-dep)."""
    fused: dict[int, float] = {}
    for ranks in rank_lists:
        for pos, (idx, _score) in enumerate(ranks):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return [idx for idx, _ in sorted(fused.items(), key=lambda kv: -kv[1])]


@dataclass
class Chunk:
    chunk_id: str
    source: str          # path relative to workspace
    start_line: int
    end_line: int
    text: str


def chunk_file(rel: str, text: str, max_chars: int = 3200,
               overlap_lines: int = 8) -> list[Chunk]:
    """Line-based chunking (~500-1000 tokens) with overlap, keeps line numbers."""
    lines = text.splitlines()
    chunks, buf, buf_start, size = [], [], 1, 0
    i = 1
    for i, line in enumerate(lines, 1):
        buf.append(line)
        size += len(line) + 1
        if size >= max_chars:
            chunks.append(Chunk(f"{rel}::{buf_start}", rel, buf_start, i,
                                "\n".join(buf)))
            keep = buf[-overlap_lines:]
            buf_start = i - len(keep) + 1
            buf, size = list(keep), sum(len(l) + 1 for l in keep)
    if buf and (not chunks or size > sum(len(l) + 1 for l in buf[:overlap_lines])):
        chunks.append(Chunk(f"{rel}::{buf_start}", rel, buf_start,
                            len(lines), "\n".join(buf)))
    return [c for c in chunks if c.text.strip()]


class LocalEmbedder:
    """Local embedding via transformers (last-token pooling for Qwen3-Embedding)."""

    def __init__(self, model_name: str = "Qwen/Qwen3-Embedding-0.6B",
                 device: Optional[str] = None):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(model_name, padding_side="left")
        self.model = AutoModel.from_pretrained(
            model_name, dtype=torch.bfloat16 if "cuda" in self.device else torch.float32
        ).to(self.device).eval()

    @staticmethod
    def _pool(hidden, mask):
        # last non-pad token (padding_side=left -> simply last position)
        return hidden[:, -1]

    def encode(self, texts: list[str], batch_size: int = 8,
               max_length: int = 2048) -> np.ndarray:
        torch = self.torch
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                enc = self.tok(batch, padding=True, truncation=True,
                               max_length=max_length, return_tensors="pt"
                               ).to(self.device)
                h = self.model(**enc).last_hidden_state
                v = self._pool(h, enc["attention_mask"]).float()
                v = torch.nn.functional.normalize(v, dim=-1)
                out.append(v.cpu().numpy())
        return np.concatenate(out, axis=0)


class RagIndex:
    def __init__(self, workspace: str, store_dir: Optional[str] = None,
                 embedder: Optional[LocalEmbedder] = None):
        self.workspace = Path(workspace).resolve()
        self.store = Path(store_dir or self.workspace / ".screwshell" / "rag")
        self.store.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vecs: Optional[np.ndarray] = None
        self._load()

    # ---------- persistence ----------

    def _load(self):
        meta = self.store / "chunks.json"
        vec = self.store / "vectors.npz"
        if meta.is_file() and vec.is_file():
            with open(meta, encoding="utf-8") as f:
                self.chunks = [Chunk(**c) for c in json.load(f)]
            self.vecs = np.load(vec)["v"]

    def _save(self):
        with open(self.store / "chunks.json", "w", encoding="utf-8") as f:
            json.dump([c.__dict__ for c in self.chunks], f, ensure_ascii=False)
        np.savez_compressed(self.store / "vectors.npz", v=self.vecs)

    # ---------- ingest ----------

    def ingest(self, subdir: str = ".", max_files: int = 400) -> dict:
        assert self.embedder is not None, "embedder required for ingest"
        root = (self.workspace / subdir).resolve()
        t0 = time.time()
        chunks: list[Chunk] = []
        n_files = 0
        for p in sorted(root.rglob("*")):
            if n_files >= max_files:
                break
            if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
                continue
            if any(part.startswith((".", "__")) for part in p.parts):
                continue
            if p.stat().st_size > 1_500_000:
                continue
            rel = os.path.relpath(p, self.workspace)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.extend(chunk_file(rel, text))
            n_files += 1
        if not chunks:
            return {"files": 0, "chunks": 0, "seconds": 0.0}
        vecs = self.embedder.encode([c.text for c in chunks])
        self.chunks, self.vecs = chunks, vecs
        self._save()
        return {"files": n_files, "chunks": len(chunks),
                "seconds": round(time.time() - t0, 1)}

    # ---------- retrieve ----------

    def search(self, query: str, top_k: int = 5, hybrid: bool = True,
               rerank: bool = True,
               reranker: Optional[Callable[[str, list[str]], list[float]]] = None
               ) -> list[dict]:
        """Hybrid recall (dense ∪ BM25) + optional cross-encoder rerank.

        ADR-2 switchable: ``hybrid=False`` keeps the legacy pure-dense path;
        ``rerank=True`` without a ``reranker`` falls back to RRF fusion (zero
        new deps); with a reranker (``Callable[[query, texts], scores]``,
        e.g. bge-reranker cross-encoder) it re-scores the candidate set.
        """
        if self.vecs is None or not self.chunks:
            return []
        assert self.embedder is not None
        q = self.embedder.encode([f"Instruct: Given a search query, retrieve "
                                  f"relevant passages\nQuery: {query}"])[0]
        sims = self.vecs @ q
        dense = sorted(enumerate(sims.tolist()), key=lambda kv: -kv[1])
        pool = dense[:top_k * 4]
        if hybrid:
            bm = BM25([c.text for c in self.chunks])
            bm_top = bm.search(query, top_k=top_k * 4)
            if bm_top:
                pool = [(i, 0.0) for i in rrf_fuse([dense, bm_top])]
        if rerank and reranker is not None and pool:
            texts = [self.chunks[i].text for i, _ in pool]
            scores = reranker(query, texts)
            pool = sorted(zip([i for i, _ in pool], scores),
                          key=lambda kv: -kv[1])
        elif rerank and len(pool) > top_k:
            # no cross-encoder available -> keep the fused (RRF) order, cap
            pass
        pool = pool[:top_k]
        return [{
            "chunk_id": self.chunks[i].chunk_id,
            "source": self.chunks[i].source,
            "start_line": self.chunks[i].start_line,
            "end_line": self.chunks[i].end_line,
            "score": float(s),
            "text": self.chunks[i].text,
        } for i, s in pool]
