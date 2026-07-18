from cortex.bench.embed_probe import EmbedProbe
from cortex.bench.gpu_sensor import GpuSensor


class _ExplodingEmbedderFactory:
    def __init__(self, bad_backend: str = "gpu") -> None:
        self.bad_backend = bad_backend

    def __call__(self, backend: str = "gpu"):
        if backend == self.bad_backend:
            raise RuntimeError("CUDA not available")
        return _StubCpuEmbedder()


class _StubCpuEmbedder:
    def embed(self, texts):
        return [[0.0] * 384 for _ in texts]


def test_gpu_probe_reports_unavailable_when_factory_raises():
    factory = _ExplodingEmbedderFactory("gpu")
    probe = EmbedProbe(
        text_pool=["q"] * 4,
        batch_size=4,
        mode="radeon",
        embedder_factory=factory,
    )
    assert probe.available is False
    count, elapsed = probe.probe_once()
    assert count == 0
    assert elapsed == 0.0


def test_cpu_probe_still_works_when_gpu_factory_raises():
    factory = _ExplodingEmbedderFactory("gpu")
    probe = EmbedProbe(
        text_pool=["q"] * 4,
        batch_size=4,
        mode="cpu",
        embedder_factory=factory,
    )
    assert probe.available is True
    count, elapsed = probe.probe_once()
    assert count == 4
    assert elapsed > 0


def test_gpu_sensor_returns_zero_when_no_gpu(monkeypatch):
    sensor = GpuSensor()

    class _FakeTorchCuda:
        @staticmethod
        def is_available():
            return False

    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCuda, raising=False)
    snap = sensor.snapshot()
    assert snap == {"mem_util_pct": 0.0}
