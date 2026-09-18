"""AMD SMI JSON adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from buildguard.monitoring.base import BaseHardwareMonitor, GPUStats, HardwareSnapshot

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = "".join(char for char in value if char.isdigit() or char in ".-")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def parse_amd_smi_json(output: str) -> list[GPUStats]:
    """Parse common amd-smi metric JSON shapes without assuming a driver revision."""
    payload = json.loads(output)
    devices = payload if isinstance(payload, list) else payload.get("gpu_data", payload)
    if isinstance(devices, dict):
        devices = list(devices.values())
    if not isinstance(devices, list):
        raise TypeError("amd-smi JSON does not contain a device list")
    result: list[GPUStats] = []
    for raw in devices:
        if not isinstance(raw, dict):
            continue
        values = raw.get("metrics", raw)
        name = raw.get("name") or raw.get("asic", {}).get("market_name")
        result.append(
            GPUStats(
                name=str(name) if name else None,
                utilization_percent=_number(values.get("gfx_activity") or values.get("gpu_usage")),
                memory_used_mb=_number(values.get("vram_used") or values.get("memory_used")),
                memory_total_mb=_number(values.get("vram_total") or values.get("memory_total")),
                temperature_celsius=_number(
                    values.get("temperature") or values.get("temperature_edge")
                ),
                power_watts=_number(values.get("power") or values.get("average_socket_power")),
            )
        )
    return result


class AmdSmiMonitor(BaseHardwareMonitor):
    """Collect GPU metrics through amd-smi."""

    def __init__(self, command_timeout_seconds: float = 5.0, runner: Runner = subprocess.run) -> None:
        super().__init__()
        self.command_timeout_seconds = command_timeout_seconds
        self.runner = runner

    def snapshot(self) -> HardwareSnapshot:
        executable = shutil.which("amd-smi")
        if not executable:
            return HardwareSnapshot(source="amd-smi", available=False, error="amd-smi not found")
        try:
            result = self.runner(
                [executable, "metric", "--json"],
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                return HardwareSnapshot(
                    source="amd-smi", available=False, error=result.stderr.strip() or "command failed"
                )
            return HardwareSnapshot(source="amd-smi", gpus=parse_amd_smi_json(result.stdout))
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
            return HardwareSnapshot(source="amd-smi", available=False, error=str(exc))
