"""ROCm SMI JSON adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from buildguard.monitoring.amd_smi import _number
from buildguard.monitoring.base import BaseHardwareMonitor, GPUStats, HardwareSnapshot

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _find(raw: dict[str, Any], *needles: str) -> Any:
    for key, value in raw.items():
        lowered = key.lower()
        if all(needle in lowered for needle in needles):
            return value
    return None


def _memory_mb(raw: dict[str, Any], *needles: str) -> float | None:
    value = _number(_find(raw, *needles))
    if value is None:
        return None
    key = next(
        (key.lower() for key in raw if all(needle in key.lower() for needle in needles)),
        "",
    )
    return value / (1024 * 1024) if "(b)" in key or "bytes" in key else value


def parse_rocm_smi_json(output: str) -> list[GPUStats]:
    """Parse rocm-smi --json output."""
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise TypeError("rocm-smi JSON root must be an object")
    result: list[GPUStats] = []
    for card, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        result.append(
            GPUStats(
                name=str(_find(raw, "card", "series") or _find(raw, "device", "name") or card),
                utilization_percent=_number(_find(raw, "gpu", "use")),
                memory_used_mb=_memory_mb(raw, "vram", "used"),
                memory_total_mb=_memory_mb(raw, "vram", "total"),
                temperature_celsius=_number(_find(raw, "temperature")),
                power_watts=_number(_find(raw, "power")),
            )
        )
    return result


class RocmSmiMonitor(BaseHardwareMonitor):
    """Collect GPU metrics through rocm-smi."""

    def __init__(self, command_timeout_seconds: float = 5.0, runner: Runner = subprocess.run) -> None:
        super().__init__()
        self.command_timeout_seconds = command_timeout_seconds
        self.runner = runner

    def snapshot(self) -> HardwareSnapshot:
        executable = shutil.which("rocm-smi")
        if not executable:
            return HardwareSnapshot(source="rocm-smi", available=False, error="rocm-smi not found")
        try:
            result = self.runner(
                [executable, "--showallinfo", "--json"],
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                return HardwareSnapshot(
                    source="rocm-smi", available=False, error=result.stderr.strip() or "command failed"
                )
            return HardwareSnapshot(source="rocm-smi", gpus=parse_rocm_smi_json(result.stdout))
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
            return HardwareSnapshot(source="rocm-smi", available=False, error=str(exc))
