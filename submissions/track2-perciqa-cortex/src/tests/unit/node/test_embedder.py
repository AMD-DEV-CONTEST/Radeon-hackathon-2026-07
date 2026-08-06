import numpy as np

from cortex.node.embedder import Embedder


def test_embed_cpu_returns_float16_normalized() -> None:
    emb = Embedder(model="BAAI/bge-small-en-v1.5", backend="cpu", batch_size=4)
    vecs = emb.embed(["APT29 encoded powershell T1059.001", "lateral movement via SMB"])
    assert vecs.shape == (2, 384)
    assert vecs.dtype == np.float16
    norms = np.linalg.norm(vecs.astype(np.float32), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)


def test_embed_one_shape() -> None:
    emb = Embedder(model="BAAI/bge-small-en-v1.5", backend="cpu", batch_size=4)
    v = emb.embed_one("a finding")
    assert v.shape == (384,)
    assert v.dtype == np.float16


def test_embed_oom_halves_batch_and_invokes_callback(monkeypatch) -> None:
    calls: list[str] = []
    emb = Embedder(model="BAAI/bge-small-en-v1.5", backend="cpu", batch_size=16,
                   on_embed_failed=calls.append)
    real_forward = emb._model.forward

    state = {"count": 0}

    def fake_forward(*a, **k):
        state["count"] += 1
        if state["count"] == 1:
            raise RuntimeError("CUDA out of memory")
        return real_forward(*a, **k)

    monkeypatch.setattr(emb._model, "forward", fake_forward)
    v = emb.embed(["x"])
    assert v.shape == (1, 384)
    assert any("oom:halve_to" in c for c in calls), calls
