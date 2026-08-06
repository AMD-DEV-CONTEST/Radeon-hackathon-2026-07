import numpy as np

from cortex.bench.embed_probe import EmbedProbe


class _FakeEmbedder:
    def __init__(self, backend: str = "gpu") -> None:
        self.backend = backend
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.zeros((len(texts), 384), dtype=np.float32)


def test_probe_once_returns_batch_size_and_positive_elapsed(monkeypatch):
    fake = _FakeEmbedder("gpu")
    pool = ["APT29 T1059.001 encoded powershell"] * 32
    probe = EmbedProbe(
        text_pool=pool,
        batch_size=16,
        mode="radeon",
        embedder_factory=lambda backend="gpu": fake,
    )
    count, elapsed = probe.probe_once()
    assert count == 16
    assert elapsed >= 0.0
    throughput = count / elapsed if elapsed > 0 else float("inf")
    assert throughput > 0
    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == 16


def test_pool_cycles_when_pool_smaller_than_batch(monkeypatch):
    fake = _FakeEmbedder("cpu")
    pool = ["short pool text"]
    probe = EmbedProbe(
        text_pool=pool,
        batch_size=4,
        mode="cpu",
        embedder_factory=lambda backend="cpu": fake,
    )
    count1, _ = probe.probe_once()
    count2, _ = probe.probe_once()
    assert count1 == 4
    assert count2 == 4
    assert fake.calls[0] == ["short pool text"] * 4
    assert fake.calls[1] == ["short pool text"] * 4


def test_probe_throughput_is_finite_with_instant_embedder(monkeypatch):
    fake = _FakeEmbedder("gpu")
    pool = ["x"] * 8
    probe = EmbedProbe(
        text_pool=pool,
        batch_size=8,
        mode="radeon",
        embedder_factory=lambda backend="gpu": fake,
    )
    count, elapsed = probe.probe_once()
    throughput = count / elapsed if elapsed > 0 else 0.0
    assert count == 8
    assert isinstance(throughput, float)
    assert throughput >= 0
