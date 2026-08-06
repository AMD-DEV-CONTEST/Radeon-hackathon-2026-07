"""NVIDIA SMI telemetry adapter."""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from collections.abc import Callable

from buildguard.monitoring.amd_smi import _number
from buildguard.monitoring.base import BaseHardwareMonitor, GPUStats, HardwareSnapshot

Runner = Callable[..., subprocess.CompletedProcess[str]]
_QUERY_FIELDS = (
    "name",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "power.draw",
)


def parse_nvidia_smi_csv(output: str) -> list[GPUStats]:
    """Parse the stable no-units CSV output produced by nvidia-smi."""
    result: list[GPUStats] = []
    for row in csv.reader(io.StringIO(output)):
        if not row or not any(value.strip() for value in row):
            continue
        values = [value.strip() for value in row]
        values.extend([""] * (len(_QUERY_FIELDS) - len(values)))
        result.append(
            GPUStats(
                name=values[0] or None,
                utilization_percent=_number(values[1]),
                memory_used_mb=_number(values[2]),
                memory_total_mb=_number(values[3]),
                temperature_celsius=_number(values[4]),
                power_watts=_number(values[5]),
            )
        )
    return result


class NvidiaSmiMonitor(BaseHardwareMonitor):
    """Collect real GPU metrics through nvidia-smi when it is installed."""

    def __init__(self, command_timeout_seconds: float = 5.0, runner: Runner = subprocess.run) -> None:
        super().__init__()
        self.command_timeout_seconds = command_timeout_seconds
        self.runner = runner

    def snapshot(self) -> HardwareSnapshot:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return HardwareSnapshot(source="nvidia-smi", available=False, error="nvidia-smi not found")
        try:
            result = self.runner(
                [
                    executable,
                    f"--query-gpu={','.join(_QUERY_FIELDS)}",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                return HardwareSnapshot(
                    source="nvidia-smi",
                    available=False,
                    error=result.stderr.strip() or "command failed",
                )
            gpus = parse_nvidia_smi_csv(result.stdout)
            if not gpus:
                return HardwareSnapshot(
                    source="nvidia-smi", available=False, error="nvidia-smi returned no GPU rows"
                )
            return HardwareSnapshot(source="nvidia-smi", gpus=gpus)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return HardwareSnapshot(source="nvidia-smi", available=False, error=str(exc))
