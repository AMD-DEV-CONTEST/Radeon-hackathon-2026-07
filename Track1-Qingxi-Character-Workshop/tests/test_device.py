# character-workshop/tests/test_device.py
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.device import DeviceInfo, detect_device, vram_profile


def test_detect_device_returns_info():
    info = detect_device()
    assert isinstance(info, DeviceInfo)
    assert info.device_type in {"cpu", "cuda", "mps"}
    assert isinstance(info.name, str)
    assert info.vram_gb is None or info.vram_gb >= 0


def test_vram_profile_cpu():
    info = DeviceInfo(device_type="cpu", name="cpu", vram_gb=None, rocm_hint=False)
    assert vram_profile(info) == "cpu"


def test_vram_profile_16_and_24():
    assert vram_profile(DeviceInfo("cuda", "x", 15.0, True)) == "16gb"
    assert vram_profile(DeviceInfo("cuda", "x", 22.0, True)) == "24gb"


def test_mock_env_forces_cpu_label(monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    info = detect_device()
    # MOCK still reports real backend if present, but mock_mode True
    assert info.mock_mode is True