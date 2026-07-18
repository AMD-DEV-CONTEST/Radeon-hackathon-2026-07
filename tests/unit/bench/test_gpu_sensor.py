from cortex.bench.gpu_sensor import GpuSensor


class _FakeTorchCudaNoGpu:
    @staticmethod
    def is_available() -> bool:
        return False

    @staticmethod
    def mem_util_pct() -> float:
        return 0.0


class _FakeTorchCudaHalfUtil:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def mem_util_pct() -> float:
        return 50.0


class _FakeTorchCudaOverUtil:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def mem_util_pct() -> float:
        return 123.4


def test_no_gpu_returns_zero(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaNoGpu)
    sensor = GpuSensor()
    assert sensor.snapshot() == {"mem_util_pct": 0.0}


def test_with_gpu_returns_in_range(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaHalfUtil)
    sensor = GpuSensor()
    snap = sensor.snapshot()
    assert set(snap.keys()) == {"mem_util_pct"}
    assert 0.0 <= snap["mem_util_pct"] <= 100.0
    assert snap["mem_util_pct"] == 50.0


def test_clamps_overflow(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaOverUtil)
    sensor = GpuSensor()
    assert sensor.snapshot()["mem_util_pct"] == 100.0
