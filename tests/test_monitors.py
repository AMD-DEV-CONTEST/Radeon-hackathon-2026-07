import shutil

import pytest

from buildguard.monitoring.amd_smi import AmdSmiMonitor, parse_amd_smi_json
from buildguard.monitoring.nvidia_smi import parse_nvidia_smi_csv
from buildguard.monitoring.process_monitor import ProcessMonitor
from buildguard.monitoring.rocm_smi import parse_rocm_smi_json


def test_missing_command_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    snapshot = AmdSmiMonitor().snapshot()
    assert not snapshot.available
    assert "not found" in (snapshot.error or "")
    assert ProcessMonitor().snapshot().available


def test_parse_amd_smi_json() -> None:
    result = parse_amd_smi_json(
        '[{"name":"Radeon RX","metrics":{"gfx_activity":75,'
        '"vram_used":1024,"vram_total":16384,"temperature":55,"power":120}}]'
    )
    assert result[0].name == "Radeon RX"
    assert result[0].utilization_percent == 75
    assert result[0].memory_total_mb == 16384


def test_parse_rocm_smi_json() -> None:
    result = parse_rocm_smi_json(
        '{"card0":{"Card series":"Radeon PRO","GPU use (%)":"61%",'
        '"VRAM Total Memory (B)":17179869184,"VRAM Total Used Memory (B)":1073741824,'
        '"Temperature (Sensor edge) (C)":"48.0c","Average Graphics Package Power (W)":"90W"}}'
    )
    assert result[0].name == "Radeon PRO"
    assert result[0].utilization_percent == 61
    assert result[0].temperature_celsius == 48


def test_parse_nvidia_smi_csv() -> None:
    result = parse_nvidia_smi_csv(
        "NVIDIA GeForce GTX 1650, 7, 2538, 4096, 41, 17.31\n"
    )
    assert result[0].name == "NVIDIA GeForce GTX 1650"
    assert result[0].utilization_percent == 7
    assert result[0].memory_used_mb == 2538
    assert result[0].power_watts == 17.31
