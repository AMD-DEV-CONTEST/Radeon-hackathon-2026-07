import numpy as np
import pytest

hnswlib = pytest.importorskip("hnswlib")

from cortex.node.vector_index import HNSWIndex


def make_data(n: int = 100, dim: int = 384, seed: int = 0) -> tuple[np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    vecs = rng.normal(size=(n, dim)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    ids = [f"a{i}" for i in range(n)]
    return vecs, ids


def test_hnsw_add_search_save_load(tmp_path) -> None:
    vecs, ids = make_data()
    idx = HNSWIndex(dim=384)
    for v, art_id in zip(vecs, ids):
        idx.add(art_id, v)
    assert idx.size() == 100
    q = vecs[0]
    hits = idx.search(q, top_k=5)
    found = [a for a, _ in hits]
    assert "a0" in found
    p = tmp_path / "vectors"
    idx.save(p)
    idx2 = HNSWIndex(dim=384)
    idx2.load(p)
    assert idx2.size() == 100
    hits2 = idx2.search(q, top_k=5)
    assert hits2[0][0] == "a0"


def test_faiss_gpu_or_skip() -> None:
    pytest.importorskip("faiss")
    from cortex.node.vector_index import FAISSGPUIndex
    vecs, ids = make_data(50, seed=7)
    idx = FAISSGPUIndex(dim=384)
    for v, art_id in zip(vecs, ids):
        idx.add(art_id, v)
    assert idx.size() == 50
    hits = idx.search(vecs[0], top_k=5)
    assert hits[0][0] == "a0"
