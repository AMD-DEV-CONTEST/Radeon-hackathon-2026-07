from unittest.mock import patch

import pytest

from cortex.bench.gpu_sensor import GpuSensor


class _FakeTorchCudaNoGpu:
    @staticmethod
    def is_available() -> bool:
        return False

    @staticmethod
    def mem_util_pct() -> float:
        return 0.0

    @staticmethod
    def device_name() -> str:
        return "unknown"


class _FakeTorchCudaHalfUtil:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def mem_util_pct() -> float:
        return 50.0

    @staticmethod
    def device_name() -> str:
        return "AMD Radeon Fake"


class _FakeTorchCudaOverUtil:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def mem_util_pct() -> float:
        return 123.4

    @staticmethod
    def device_name() -> str:
        return "AMD Radeon Fake"


def test_no_gpu_returns_zero(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaNoGpu)
    sensor = GpuSensor()
    assert sensor.snapshot() == {"mem_util_pct": 0.0, "device_name": "none", "backend": "none"}


def test_with_gpu_returns_in_range(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaHalfUtil)
    sensor = GpuSensor()
    snap = sensor.snapshot()
    assert set(snap.keys()) == {"mem_util_pct", "device_name", "backend"}
    assert 0.0 <= snap["mem_util_pct"] <= 100.0
    assert snap["mem_util_pct"] == 50.0
    assert snap["backend"] == "torch"


def test_clamps_overflow(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaOverUtil)
    sensor = GpuSensor()
    assert sensor.snapshot()["mem_util_pct"] == 100.0


class _FakeTorchCudaZeroUtil:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def mem_util_pct() -> float:
        return 0.0

    @staticmethod
    def device_name() -> str:
        return "AMD Radeon Fake"


def test_rocm_smi_fallback_when_torch_returns_zero(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaZeroUtil)
    sensor = GpuSensor()
    with patch("cortex.bench.gpu_sensor.subprocess.check_output") as mock:
        raw = b'{"card0": {"VRAM Total Memory (B)": 68719476736, ' \
              b'"VRAM Total Used Memory (B)": 21474836480}}'
        mock.return_value = raw
        snap = sensor.snapshot()
    assert 0.0 < snap["mem_util_pct"] <= 100.0
    assert snap["mem_util_pct"] == pytest.approx(31.25, rel=0.1)
    assert snap["backend"] == "rocm-smi"


def test_rocm_smi_fallback_returns_zero_on_failure(monkeypatch):
    monkeypatch.setattr("cortex.bench.gpu_sensor.torch_cuda", _FakeTorchCudaZeroUtil)
    sensor = GpuSensor()
    with patch("cortex.bench.gpu_sensor.subprocess.check_output") as mock:
        mock.side_effect = Exception("no rocm-smi")
        snap = sensor.snapshot()
    assert snap["mem_util_pct"] == 0.0
