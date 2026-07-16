"""Unit tests for src.core.device.

These tests run without a real GPU — we mock torch to exercise the
detection logic in isolation.
"""
import sys
from unittest import mock

import pytest


def _mock_torch(*, is_available: bool, hip: str | None, cuda: str | None):
    """Build a fake torch module with the given backend hints."""
    fake = mock.MagicMock()
    fake.cuda.is_available.return_value = is_available
    fake.version.hip = hip
    fake.version.cuda = cuda
    return fake


def test_detect_device_cpu_when_torch_says_no_cuda():
    """When torch.cuda.is_available() is False, device kind should be 'cpu'."""
    fake_torch = _mock_torch(is_available=False, hip=None, cuda=None)
    with mock.patch.dict(sys.modules, {"torch": fake_torch}):
        # Re-import inside the patch so it picks up the mock
        from src.core.device import detect_device_kind
        assert detect_device_kind() == "cpu"


def test_detect_device_rocm_when_hip_present():
    """When torch.version.hip is set, device kind should be 'rocm'."""
    fake_torch = _mock_torch(is_available=True, hip="5.7.1", cuda=None)
    with mock.patch.dict(sys.modules, {"torch": fake_torch}):
        from src.core.device import detect_device_kind
        assert detect_device_kind() == "rocm"


def test_detect_device_cuda_when_cuda_present():
    """When torch.version.cuda is set (no hip), device kind should be 'cuda'."""
    fake_torch = _mock_torch(is_available=True, hip=None, cuda="12.1")
    with mock.patch.dict(sys.modules, {"torch": fake_torch}):
        from src.core.device import detect_device_kind
        assert detect_device_kind() == "cuda"


def test_detect_device_ambiguous_falls_back_to_cuda():
    """If torch says GPU is up but no backend reports, log warning and assume CUDA."""
    fake_torch = _mock_torch(is_available=True, hip=None, cuda=None)
    with mock.patch.dict(sys.modules, {"torch": fake_torch}):
        from src.core.device import detect_device_kind
        assert detect_device_kind() == "cuda"


def test_get_device_respects_env_override_cpu(monkeypatch):
    """RADEON_STUDIO_DEVICE=cpu should win over detection."""
    monkeypatch.setenv("RADEON_STUDIO_DEVICE", "cpu")
    fake_torch = _mock_torch(is_available=True, hip="5.7.1", cuda=None)
    with mock.patch.dict(sys.modules, {"torch": fake_torch}):
        from src.core.device import get_device
        assert get_device() == "cpu"


def test_get_device_respects_env_override_rocm(monkeypatch):
    """RADEON_STUDIO_DEVICE=rocm should resolve to torch's 'cuda' alias."""
    monkeypatch.setenv("RADEON_STUDIO_DEVICE", "rocm")
    with mock.patch.dict(sys.modules, {"torch": _mock_torch(is_available=False, hip=None, cuda=None)}):
        from src.core.device import get_device
        assert get_device() == "cuda"
