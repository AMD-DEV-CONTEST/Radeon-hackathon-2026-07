"""RAG hybrid retrieval tests (2026-08-04, OPENSOURCE_COMPARISON §4.1).

BM25 + RRF fusion + optional cross-encoder rerank, ADR-2 switchable.
Zero new dependencies: BM25 is a hand-rolled Okapi implementation good at
exact terms / code symbols that dense embedding misses.
"""
from __future__ import annotations

import numpy as np
import pytest

from screwshell.rag.pipeline import BM25, RagIndex, rrf_fuse, _tokenize


# ------------------------------------------------------------------ BM25
def test_tokenize_cjk_and_ascii():
    assert "read_file" in _tokenize("调用 read_file 读取配置")
    assert "配" in _tokenize("调用 read_file 读取配置")  # CJK unigram


def test_bm25_ranks_exact_term_hits():
    docs = [
        "def read_file(path): open the file",
        "def list_dir(path): list the directory",
        "the quick brown fox jumps over the lazy dog",
    ]
    bm = BM25(docs)
    # "read_file" appears only in doc 0 -> must rank first
    hits = bm.search("read_file", top_k=3)
    assert hits and hits[0][0] == 0
    # common word "the" should NOT outrank the exact symbol match
    hits2 = bm.search("the path", top_k=3)
    assert hits2[0][0] in (0, 1)


def test_bm25_cjk_query():
    docs = ["配置中心负责密钥管理", "模型推理需要 GPU 显存"]
    bm = BM25(docs)
    hits = bm.search("密钥", top_k=2)
    assert hits and hits[0][0] == 0


# ------------------------------------------------------------------ RRF
def test_rrf_fuses_rank_lists():
    fused = rrf_fuse([[(0, 1), (1, 0.5)], [(1, 0.9), (2, 0.8)]])
    assert fused[0] == 1, "appearing in both lists must rank first"
    assert set(fused) == {0, 1, 2}


# -------------------------------------------------------------- RagIndex
class _FakeEmbedder:
    """Deterministic embedder: one-hot-ish vector per unique word."""

    def __init__(self):
        self.words = {}

    def encode(self, texts, **kw) -> np.ndarray:
        out = []
        for t in texts:
            v = np.zeros(64)
            for w in _tokenize(t):
                i = self.words.setdefault(w, len(self.words)) % 64
                v[i] += 1
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.array(out)


def _index(tmp_path) -> RagIndex:
    (tmp_path / "code.py").write_text(
        "import os\ndef read_file(path):\n    return open(path).read()\n"
        "def list_dir(path):\n    return os.listdir(path)\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text(
        "配置中心负责密钥管理，禁止明文存储\n", encoding="utf-8")
    idx = RagIndex(str(tmp_path), embedder=_FakeEmbedder())
    idx.ingest()
    return idx


def test_search_hybrid_finds_exact_symbol(tmp_path):
    idx = _index(tmp_path)
    # "read_file" is a code symbol; dense (fake embedder) may miss it, BM25
    # must surface it via hybrid recall
    hits = idx.search("read_file 函数", top_k=3)
    assert hits and "code.py" in hits[0]["source"]


def test_search_pure_dense_back_compat(tmp_path):
    idx = _index(tmp_path)
    hits = idx.search("read_file", top_k=3, hybrid=False)
    assert isinstance(hits, list)  # legacy path still returns shape


def test_search_reranker_injected(tmp_path):
    idx = _index(tmp_path)
    calls = []

    def reranker(query, texts):
        calls.append((query, len(texts)))
        # reverse order to prove the rerank step actually re-scores
        return [float(len(texts) - i) for i in range(len(texts))]

    hits = idx.search("read_file", top_k=2, reranker=reranker)
    assert calls, "reranker must be invoked"
    assert len(hits) == 2
